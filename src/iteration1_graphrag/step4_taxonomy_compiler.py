"""Iteration 1 — Stage 4: Failure Mode Taxonomy Compiler.

Groups diverse historical observation phrasings per component into at most 5
standardized Failure Modes via Gemini Pydantic structured outputs so the Neo4j
Hourglass Knowledge Graph maintains bounded branching factors.
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


class ObservationMapping(BaseModel):
    original_text: str = Field(description="The exact observation text provided.")
    failure_mode: str = Field(
        description="Standardized Failure Mode (e.g., 'Missing/Not Provided', 'Pressure Dropped'). Max 5 words."
    )


class TaxonomyResult(BaseModel):
    mappings: list[ObservationMapping] = Field(description="List of mapped observations.")


def compile_taxonomy(
    input_file: Path,
    output_file: Path,
    model_name: str = DEFAULT_MODEL,
) -> list[dict[str, Any]]:
    """Clusters unique observations per component into canonical Failure Mode labels."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable is not set.")

    client = genai.Client(api_key=api_key)
    graph_nodes: list[dict[str, Any]] = json.loads(input_file.read_text(encoding="utf-8"))

    component_observations: dict[str, set[str]] = {}
    for node in graph_nodes:
        comp = node["Component_Name"]
        obs = node["Observation_Summary"]
        component_observations.setdefault(comp, set()).add(obs)

    print(
        f"[*] Loaded {len(graph_nodes)} nodes across "
        f"{len(component_observations)} unique components."
    )

    master_mapping: dict[str, str] = {}
    for component, observations in component_observations.items():
        obs_list = sorted(observations)
        print(f" -> Mapping [{component}] ({len(obs_list)} unique observations)...")

        if len(obs_list) == 1:
            master_mapping[obs_list[0]] = "Standard Defect"
            continue

        prompt = (
            "You are a Fire Safety Engineering Data Architect.\n"
            f"Analyze the following field observations for the component: '{component}'.\n"
            "Group these observations into a maximum of 5 strict, standardized Failure Modes.\n\n"
            f"Original Observations:\n{json.dumps(obs_list, indent=2)}"
        )

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=TaxonomyResult,
                ),
            )
            for item in response.parsed.mappings:
                master_mapping[item.original_text] = item.failure_mode
            time.sleep(5)
        except Exception as exc:
            err = str(exc)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                print("   [!] HTTP 429 rate limit. Waiting 25s and applying fallback...")
                time.sleep(25)
            else:
                print(f"   [!] Error on {component}: {exc}. Defaulting to 'Standard Defect'.")
            for obs in obs_list:
                master_mapping.setdefault(obs, "Standard Defect")

    for node in graph_nodes:
        node["Failure_Mode"] = master_mapping.get(
            node["Observation_Summary"], "Standard Defect"
        )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(graph_nodes, indent=4, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[DONE] Taxonomy compilation complete: {len(graph_nodes)} nodes -> {output_file}")
    return graph_nodes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Iteration 1 Step 4: Compile Failure Mode taxonomy for Neo4j."
    )
    parser.add_argument("--input", type=Path, default=Path("data/iteration1/consensus_truth.json"))
    parser.add_argument("--output", type=Path, default=Path("data/iteration1/hourglass_ready_nodes.json"))
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    args = parser.parse_args()

    compile_taxonomy(args.input, args.output, model_name=args.model)


if __name__ == "__main__":
    main()
