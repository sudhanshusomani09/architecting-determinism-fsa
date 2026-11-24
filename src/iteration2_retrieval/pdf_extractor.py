"""Two-Phase Vision PDF Extractor with Fault-Tolerant Checkpoint Persistence.

Implements Iteration 2 ingestion pipeline:
  - Phase 1: Uploads audit PDF to Gemini File API and extracts facility metadata
             plus audited micro-areas using a strict Pydantic schema (FacilityIndex).
  - Phase 2: Iterates sequentially over each micro-area using AreaReport to prevent
             context truncation on large multi-hundred-observation reports.
  - Persistence: Atomically commits progress to a checkpoint JSON after every room
             so interrupted runs resume without duplicate API calls.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

load_dotenv()

DEFAULT_MODEL = "gemini-3.1-flash-lite"
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 20
RPM_CRUISE_DELAY = 15
RATE_LIMIT_DELAY = 65


# ==========================================
# 1. PYDANTIC EXTRACTION SCHEMAS
# ==========================================
class FacilityIndex(BaseModel):
    facility_name: str = Field(
        description="Anonymized or reported name of the facility being audited."
    )
    hazard_classification: str = Field(
        description="NBC 2016 Hazard Classification (e.g., Group G-2)."
    )
    list_of_audited_areas: list[str] = Field(
        description="List of specific rooms or micro-areas audited in the report."
    )


class AreaObservation(BaseModel):
    micro_area: str
    component: str
    observation: str
    compliance_status: str
    risk_category: str
    recommendation: str
    standard_reference: str
    system_efficacy_context: str | None = Field(
        default=None,
        description=(
            "If a fire protection system is present but rendered ineffective "
            "due to installation or environment, state it here. Otherwise null."
        ),
    )


class AreaReport(BaseModel):
    observations: list[AreaObservation]


# ==========================================
# 2. STATE PERSISTENCE LAYER
# ==========================================
def load_state(
    output_file: Path, checkpoint_file: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Loads existing extracted observations and checkpoint tracker if present."""
    observations: list[dict[str, Any]] = []
    checkpoint: dict[str, Any] = {"files": {}}

    if output_file.exists():
        try:
            observations = json.loads(output_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            observations = []

    if checkpoint_file.exists():
        try:
            checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            checkpoint = {"files": {}}

    return observations, checkpoint


def save_state(
    checkpoint_file: Path,
    output_file: Path,
    checkpoint: dict[str, Any],
    observations: list[dict[str, Any]],
) -> None:
    """Writes checkpoint state and accumulated observations to disk atomically."""
    checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    tmp_ckpt = checkpoint_file.with_suffix(".tmp")
    tmp_out = output_file.with_suffix(".tmp")

    tmp_ckpt.write_text(
        json.dumps(checkpoint, indent=4, ensure_ascii=False), encoding="utf-8"
    )
    tmp_out.write_text(
        json.dumps(observations, indent=4, ensure_ascii=False), encoding="utf-8"
    )

    os.replace(tmp_ckpt, checkpoint_file)
    os.replace(tmp_out, output_file)


# ==========================================
# 3. TWO-PHASE EXTRACTION ENGINE
# ==========================================
def process_pdf(
    client: genai.Client,
    file_path: Path,
    checkpoint: dict[str, Any],
    all_extracted_observations: list[dict[str, Any]],
    output_file: Path,
    checkpoint_file: Path,
    model_name: str = DEFAULT_MODEL,
    targeted_only: bool = False,
    rpm_delay: int = RPM_CRUISE_DELAY,
) -> None:
    """Runs Phase 1 indexing and Phase 2 sequential area extraction for one PDF."""
    filename = file_path.name

    if filename in checkpoint["files"]:
        file_state = checkpoint["files"][filename]
        if file_state.get("target_areas") and set(file_state["completed_areas"]) == set(
            file_state["target_areas"]
        ):
            print(f"[SKIP] {filename} already fully processed.")
            return
    else:
        checkpoint["files"][filename] = {
            "facility_name": "",
            "hazard_classification": "",
            "target_areas": [],
            "completed_areas": [],
        }

    file_state = checkpoint["files"][filename]

    print(f"\n[*] Uploading {filename} to Gemini File API...")
    uploaded_file = client.files.upload(file=str(file_path))

    print("[*] Processing document", end="")
    while uploaded_file.state.name == "PROCESSING":
        print(".", end="", flush=True)
        time.sleep(2)
        uploaded_file = client.files.get(name=uploaded_file.name)
    print(" Ready.")

    try:
        # --- PHASE 1: FACILITY INDEXING ---
        if not file_state["target_areas"]:
            print(f"[*] Phase 1 - Indexing {filename}...")
            if targeted_only:
                index_prompt = (
                    "Scan this fire safety audit report. Identify the facility name "
                    "and its NBC hazard classification. Then output ONLY the following "
                    "critical micro-areas if present: Fire Pump Room, DG Room, "
                    "Electrical Panel Room, Transformer Area, and Storage/Warehouse Area."
                )
            else:
                index_prompt = (
                    "Scan this fire safety audit report. Identify the facility name, "
                    "its NBC hazard classification, and list all specific rooms/areas "
                    "(micro-areas) audited in Section 6."
                )

            facility_index: dict[str, Any] | None = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    index_response = client.models.generate_content(
                        model=model_name,
                        contents=[uploaded_file, index_prompt],
                        config=types.GenerateContentConfig(
                            temperature=0.0,
                            response_mime_type="application/json",
                            response_schema=FacilityIndex,
                        ),
                    )
                    facility_index = json.loads(index_response.text)
                    break
                except Exception as exc:
                    err = str(exc)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        print(
                            f"   [!] HTTP 429 rate limit. Backing off {RATE_LIMIT_DELAY}s (attempt {attempt})."
                        )
                        time.sleep(RATE_LIMIT_DELAY)
                    else:
                        print(
                            f"   [!] Transient error: {exc}. Retrying in {RETRY_DELAY_SECONDS}s (attempt {attempt})."
                        )
                        time.sleep(RETRY_DELAY_SECONDS)

            if not facility_index:
                print(f"[!] Failed Phase 1 indexing for {filename}. Moving to next file.")
                return

            file_state["facility_name"] = facility_index.get(
                "facility_name", "Unknown Facility"
            )
            file_state["hazard_classification"] = facility_index.get(
                "hazard_classification", "Unknown Classification"
            )
            file_state["target_areas"] = facility_index.get("list_of_audited_areas", [])
            save_state(
                checkpoint_file, output_file, checkpoint, all_extracted_observations
            )
        else:
            print(
                f"[*] Phase 1 cached map loaded ({len(file_state['target_areas'])} mapped areas)."
            )

        fac_metadata = {
            "facility_name": file_state["facility_name"],
            "hazard_classification": file_state["hazard_classification"],
        }

        # --- PHASE 2: SEQUENTIAL MICRO-AREA EXTRACTION ---
        for area in file_state["target_areas"]:
            if area in file_state["completed_areas"]:
                print(f"   -> [SKIP] '{area}' already completed.")
                continue

            print(f"   -> Extracting area: {area}...", end="", flush=True)
            area_prompt = (
                "You are a Lead Fire Safety Engineer. Inspect the uploaded audit report "
                f"and extract all fire safety observations STRICTLY for the area: '{area}'. "
                "Capture Component, Observation, Compliance Status, Risk Category, "
                "Recommendation, and cited IS/NBC/NFPA Standards. Pay special attention "
                "to 'system_efficacy_context' where installed systems are compromised."
            )

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    area_response = client.models.generate_content(
                        model=model_name,
                        contents=[uploaded_file, area_prompt],
                        config=types.GenerateContentConfig(
                            temperature=0.0,
                            response_mime_type="application/json",
                            response_schema=AreaReport,
                        ),
                    )
                    area_data = json.loads(area_response.text)

                    for obs in area_data.get("observations", []):
                        all_extracted_observations.append(
                            {
                                "facility_metadata": fac_metadata,
                                "macro_zone": "",
                                "micro_area": obs.get("micro_area", area),
                                "component": obs.get("component", ""),
                                "observation": obs.get("observation", ""),
                                "compliance_status": obs.get("compliance_status", ""),
                                "risk_category": obs.get("risk_category", ""),
                                "recommendation": obs.get("recommendation", ""),
                                "standard_reference": obs.get("standard_reference", ""),
                                "system_efficacy_context": obs.get(
                                    "system_efficacy_context", None
                                ),
                            }
                        )

                    file_state["completed_areas"].append(area)
                    save_state(
                        checkpoint_file,
                        output_file,
                        checkpoint,
                        all_extracted_observations,
                    )
                    print(" Saved.")
                    break
                except Exception as exc:
                    err = str(exc)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        print(
                            f"\n      [!] HTTP 429 rate limit. Sleeping {RATE_LIMIT_DELAY}s (attempt {attempt})."
                        )
                        time.sleep(RATE_LIMIT_DELAY)
                    elif "503" in err or "UNAVAILABLE" in err:
                        print(
                            f"\n      [!] HTTP 503 unavailable. Retrying in {RETRY_DELAY_SECONDS}s (attempt {attempt})."
                        )
                        time.sleep(RETRY_DELAY_SECONDS)
                    else:
                        print(f"\n      [!] Schema/parse error on '{area}': {exc}")
                        break

            time.sleep(rpm_delay)
    finally:
        client.files.delete(name=uploaded_file.name)
        print(f"[*] Finalized {filename} and cleaned up remote file handle.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Two-phase fault-tolerant Fire Safety Audit PDF extractor."
    )
    parser.add_argument("--pdf-dir", type=Path, default=Path("data/raw_pdfs"))
    parser.add_argument("--output", type=Path, default=Path("data/raw_golden_extract.json"))
    parser.add_argument("--checkpoint", type=Path, default=Path("data/extraction_checkpoint.json"))
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument(
        "--targeted-only",
        action="store_true",
        help="Index only 5 critical utility/storage areas.",
    )
    parser.add_argument("--rpm-delay", type=int, default=RPM_CRUISE_DELAY)
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY environment variable is not set. Add it to your .env file."
        )

    if not args.pdf_dir.exists():
        raise FileNotFoundError(f"PDF directory not found: {args.pdf_dir}")

    client = genai.Client(api_key=api_key)
    all_obs, checkpoint = load_state(args.output, args.checkpoint)

    if all_obs:
        print(f"[*] Resuming from existing extract ({len(all_obs)} observations loaded).")

    pdf_files = sorted(p for p in args.pdf_dir.iterdir() if p.suffix.lower() == ".pdf")
    if not pdf_files:
        print(f"[!] No PDF files found in {args.pdf_dir}.")
        return

    for pdf_path in pdf_files:
        try:
            process_pdf(
                client=client,
                file_path=pdf_path,
                checkpoint=checkpoint,
                all_extracted_observations=all_obs,
                output_file=args.output,
                checkpoint_file=args.checkpoint,
                model_name=args.model,
                targeted_only=args.targeted_only,
                rpm_delay=args.rpm_delay,
            )
        except Exception as exc:
            print(f"[!] Unhandled exception while processing {pdf_path.name}: {exc}")

    print(
        f"\n[DONE] Extraction complete: {len(all_obs)} total observations saved to {args.output}."
    )


if __name__ == "__main__":
    main()
