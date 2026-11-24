"""Iteration 1 — Stage 2: Pydantic LLM Entity Structuring with Checkpointing.

Reads the Stage 1 CSV and converts each observation into a strict Pydantic
ComplianceNode JSON record using Gemini structured outputs, with row-slice
batching, disk checkpointing every 5 nodes, auto-resume, and HTTP 429 cooldowns.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

load_dotenv()

DEFAULT_MODEL = "gemini-3.1-flash-lite"


class ComplianceNode(BaseModel):
    Component_Name: str = Field(
        description="The specific asset or system being audited. Clean up trailing colons."
    )
    Observation_Summary: str = Field(
        description="A concise, 1-2 sentence summary of the physical observation."
    )
    Historical_Risk: str = Field(
        description="The risk level. Strictly HIGH, MEDIUM, LOW, or NONE."
    )
    Compliance_Status: str = Field(
        description="Strictly Complied, Non-Complied, Partially Complied, or Non-Conclusive."
    )
    Standard_Violated: str = Field(
        description="The specific code/clause violated. Return 'N/A' if Complied."
    )


def _atomic_save(path: Path, payload: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def process_csv_to_json(
    csv_path: Path,
    output_path: Path,
    start_row: int = 0,
    end_row: int | None = None,
    model_name: str = DEFAULT_MODEL,
    rpm_sleep: int = 6,
) -> None:
    """Processes a slice of Stage 1 CSV rows into structured JSON graph nodes."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable is not set.")

    client = genai.Client(api_key=api_key)
    df = pd.read_csv(csv_path)
    effective_end = min(end_row, len(df)) if end_row is not None else len(df)

    structured_graph_data: list[dict[str, Any]] = []
    if output_path.exists():
        try:
            structured_graph_data = json.loads(output_path.read_text(encoding="utf-8"))
            print(f"[*] Recovered {len(structured_graph_data)} existing nodes from {output_path}.")
        except json.JSONDecodeError:
            structured_graph_data = []

    actual_start = start_row + len(structured_graph_data)
    if actual_start >= effective_end:
        print("[SKIP] Target batch slice is already 100% complete.")
        return

    print(f"[*] Resuming Stage 2 structuring from row {actual_start} to {effective_end}...")
    target_batch = df.iloc[actual_start:effective_end]
    nodes_processed_this_run = 0

    for index, row in target_batch.iterrows():
        print(f" -> Node {index + 1}/{len(df)}: [{row['Area']}] -> {row['Component']}")

        prompt = (
            "Extract the structured information from the following audit data.\n\n"
            f"Component: {row['Component']}\n"
            f"Observation: {row['Observation']}\n"
            f"Raw Compliance Status: {row['Compliance_Status']}\n"
            f"Standards Reference: {row['Standard_Reference']}\n"
            f"Risk Category: {row['Risk_Category']}\n"
        )

        for attempt in range(1, 4):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=ComplianceNode,
                        system_instruction=(
                            "You are a strict Data Extraction AI. Map the raw Fire Safety "
                            "Audit text exactly to the JSON schema. Do not hallucinate."
                        ),
                    ),
                )

                json_output = response.parsed.model_dump()
                json_output["Source_File"] = str(row["Source_File"])
                json_output["Parent_Area"] = str(row["Area"])
                json_output["Raw_Recommendation"] = str(row["Recommendation"])
                json_output["Raw_Quote"] = str(row["Standard_Quote"])

                structured_graph_data.append(json_output)
                nodes_processed_this_run += 1

                if nodes_processed_this_run % 5 == 0 or (index + 1) == effective_end:
                    _atomic_save(output_path, structured_graph_data)
                    print(f"   [+] Saved checkpoint ({len(structured_graph_data)} total nodes).")

                time.sleep(rpm_sleep)
                break
            except Exception as exc:
                err = str(exc).lower()
                if "429" in err or "resource_exhausted" in err:
                    print(f"   [!] HTTP 429 rate limit. Cooldown 25s (attempt {attempt})...")
                    time.sleep(25)
                else:
                    print(f"   [!] Transient error: {exc}. Retrying in 15s (attempt {attempt})...")
                    time.sleep(15)

    _atomic_save(output_path, structured_graph_data)
    print(f"[DONE] Saved {len(structured_graph_data)} structured nodes to {output_path}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Iteration 1 Step 2: Structure CSV observations via Gemini Pydantic schema."
    )
    parser.add_argument("--input", type=Path, default=Path("data/iteration1/neo4j_ready_mvp_data.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/iteration1/master_structured_graph.json"))
    parser.add_argument("--start-row", type=int, default=0)
    parser.add_argument("--end-row", type=int, default=None)
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    args = parser.parse_args()

    process_csv_to_json(
        csv_path=args.input,
        output_path=args.output,
        start_row=args.start_row,
        end_row=args.end_row,
        model_name=args.model,
    )


if __name__ == "__main__":
    main()
