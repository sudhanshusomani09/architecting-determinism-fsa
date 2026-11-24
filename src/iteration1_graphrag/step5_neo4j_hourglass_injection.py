"""Iteration 1 — Stage 5: Neo4j Hourglass Knowledge Graph Builder.

Ingests taxonomy-compiled compliance nodes into Neo4j using Cypher MERGE
transactions following the Hourglass Ontology:
  (Area)-[:CONTAINS]->(Component)-[:CAN_FAIL_DUE_TO]->(FailureMode)
         -[:TRIGGERS]->(MitigationRule)-[:GOVERNED_BY]->(Standard)

Credentials are loaded strictly from environment variables:
  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


class HourglassGraphBuilder:
    """Manages idempotent Cypher ingestion into the Neo4j Hourglass Knowledge Graph."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self.driver.close()

    def build_graph(self, hourglass_json_path: Path) -> int:
        verified_nodes: list[dict[str, Any]] = json.loads(
            hourglass_json_path.read_text(encoding="utf-8")
        )
        print(f"[*] Loaded {len(verified_nodes)} logic nodes. Connecting to Neo4j...")

        success_count = 0
        with self.driver.session() as session:
            for idx, data in enumerate(verified_nodes, start=1):
                try:
                    session.execute_write(self._create_hourglass_triplets, data)
                    success_count += 1
                except Exception as exc:
                    print(
                        f"   [!] Failed to inject node {idx} "
                        f"({data.get('Component_Name', 'Unknown')}): {exc}"
                    )

        print(f"[DONE] Knowledge Graph online. {success_count} logic chains established.")
        return success_count

    @staticmethod
    def _create_hourglass_triplets(tx: Any, data: dict[str, Any]) -> None:
        comp_name = data["Component_Name"].strip()
        area_name = data["Parent_Area"].strip()
        fail_name = data["Failure_Mode"].strip()

        # Scoped unique IDs prevent cross-contamination across components
        fail_id = f"{comp_name}_{fail_name}"
        rule_id = f"{fail_id}_rule"

        # 1. Top of Hourglass: Area -> Component
        tx.run("MERGE (a:Area {name: $area_name})", area_name=area_name)
        tx.run("MERGE (c:Component {name: $comp_name})", comp_name=comp_name)
        tx.run(
            """
            MATCH (a:Area {name: $area_name})
            MATCH (c:Component {name: $comp_name})
            MERGE (a)-[:CONTAINS]->(c)
            """,
            area_name=area_name,
            comp_name=comp_name,
        )

        # 2. Bottom of Hourglass: Component -> FailureMode -> MitigationRule
        tx.run(
            """
            MERGE (f:FailureMode {id: $fail_id})
            ON CREATE SET f.name = $fail_name, f.component_context = $comp_name
            """,
            fail_id=fail_id,
            fail_name=fail_name,
            comp_name=comp_name,
        )
        tx.run(
            """
            MATCH (c:Component {name: $comp_name})
            MATCH (f:FailureMode {id: $fail_id})
            MERGE (c)-[:CAN_FAIL_DUE_TO]->(f)
            """,
            comp_name=comp_name,
            fail_id=fail_id,
        )
        tx.run(
            """
            MERGE (m:MitigationRule {id: $rule_id})
            SET m.risk_level = $risk,
                m.compliance_status = $status,
                m.recommendation = $rec
            """,
            rule_id=rule_id,
            risk=data.get("Consensus_Risk", data.get("Historical_Risk", "UNKNOWN")),
            status=data["Compliance_Status"],
            rec=data["Raw_Recommendation"],
        )
        tx.run(
            """
            MATCH (f:FailureMode {id: $fail_id})
            MATCH (m:MitigationRule {id: $rule_id})
            MERGE (f)-[:TRIGGERS]->(m)
            """,
            fail_id=fail_id,
            rule_id=rule_id,
        )

        # 3. Statutory Anchor: MitigationRule -> Standard
        standard = data.get("Standard_Violated")
        if standard and str(standard).strip().upper() not in {"N/A", "NAN", "NONE"}:
            base_std = (
                str(standard).split("Clause")[0].split("Section")[0].split("Part")[0].strip()
            )
            tx.run(
                """
                MERGE (s:Standard {name: $base_std})
                SET s.full_citation = $full_std,
                    s.quote = $quote
                """,
                base_std=base_std,
                full_std=str(standard),
                quote=data.get("Raw_Quote", ""),
            )
            tx.run(
                """
                MATCH (m:MitigationRule {id: $rule_id})
                MATCH (s:Standard {name: $base_std})
                MERGE (m)-[:GOVERNED_BY]->(s)
                """,
                rule_id=rule_id,
                base_std=base_std,
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Iteration 1 Step 5: Inject Hourglass compliance triplets into Neo4j."
    )
    parser.add_argument("--input", type=Path, default=Path("data/iteration1/hourglass_ready_nodes.json"))
    args = parser.parse_args()

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    if not all([uri, user, password]):
        raise EnvironmentError(
            "NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD environment variables must be set."
        )

    builder = HourglassGraphBuilder(uri, user, password)
    try:
        builder.build_graph(args.input)
    finally:
        builder.close()


if __name__ == "__main__":
    main()
