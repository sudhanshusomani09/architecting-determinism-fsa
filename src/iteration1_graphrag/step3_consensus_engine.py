"""Iteration 1 — Stage 3: Conflict Resolution & High-Water Mark Consensus Engine.

Addresses the 'Ambiguity Trap' (historical auditor subjectivity across legacy reports):
  1. Groups identical observations by (Parent_Area || Component_Name || Observation_Summary).
  2. Trigger 1 (HITL Quarantine): Routes observations with contradictory Compliance Status
     or Standard Violated citations into a quarantine queue for human adjudication.
  3. Trigger 2 (High-Water Mark): When auditors agree on Status & Standard but disagree
     on Risk Severity (e.g., Medium vs. Low), mathematically escalates to the highest
     risk tier and preserves the vote breakdown.
  4. Trigger 3 (Verified Truth): Unanimous findings pass directly to taxonomy compilation.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

RISK_HIERARCHY: dict[str, int] = {
    "HIGH": 4,
    "MEDIUM": 3,
    "LOW": 2,
    "NONE": 1,
}


def resolve_consensus(
    graph_nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partitions raw structured nodes into verified truth and HITL quarantine queues."""
    component_groups: dict[str, list[dict[str, Any]]] = {}

    for node in graph_nodes:
        tracker_id = (
            f"{node['Parent_Area']} || {node['Component_Name']} || "
            f"{node['Observation_Summary']}"
        )
        component_groups.setdefault(tracker_id, []).append(node)

    truth_graph: list[dict[str, Any]] = []
    quarantine_queue: list[dict[str, Any]] = []

    for nodes in component_groups.values():
        statuses = {n["Compliance_Status"] for n in nodes}
        risks = [n["Historical_Risk"] for n in nodes]
        standards = {n["Standard_Violated"] for n in nodes}

        base_node = nodes[0].copy()
        base_node["Total_Audits_Analyzed"] = len(nodes)

        # TRIGGER 1: Contradictory compliance verdict or statutory citation -> Quarantine
        if len(statuses) > 1 or len(standards) > 1:
            base_node["Consensus_Status"] = "LOGICAL CONFLICT - QUARANTINED"
            base_node["Conflicting_Nodes"] = nodes
            quarantine_queue.append(base_node)
            continue

        # TRIGGER 2: Risk severity disagreement -> High-Water Mark escalation
        unique_risks = set(risks)
        if len(unique_risks) > 1:
            highest_risk = max(risks, key=lambda x: RISK_HIERARCHY.get(str(x).upper(), 0))
            base_node["Consensus_Risk"] = highest_risk
            base_node["Consensus_Status"] = "ESCALATED TRUTH (High-Water Mark)"
            base_node["Vote_Breakdown"] = dict(Counter(risks))
            truth_graph.append(base_node)
        # TRIGGER 3: Unanimous historical consensus
        else:
            base_node["Consensus_Risk"] = risks[0]
            base_node["Consensus_Status"] = "VERIFIED TRUTH"
            truth_graph.append(base_node)

    return truth_graph, quarantine_queue


def run_consensus_engine(
    input_json: Path, truth_output: Path, quarantine_output: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Loads structured nodes, runs consensus resolution, and writes output JSONs."""
    graph_nodes = json.loads(input_json.read_text(encoding="utf-8"))
    truth_graph, quarantine_queue = resolve_consensus(graph_nodes)

    truth_output.parent.mkdir(parents=True, exist_ok=True)
    quarantine_output.parent.mkdir(parents=True, exist_ok=True)

    truth_output.write_text(
        json.dumps(truth_graph, indent=4, ensure_ascii=False), encoding="utf-8"
    )
    quarantine_output.write_text(
        json.dumps(quarantine_queue, indent=4, ensure_ascii=False), encoding="utf-8"
    )

    print("[DONE] Stage 3 Consensus Engine Complete:")
    print(f" -> {len(truth_graph)} nodes verified -> {truth_output}")
    print(f" -> {len(quarantine_queue)} nodes quarantined for HITL -> {quarantine_output}")
    return truth_graph, quarantine_queue


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Iteration 1 Step 3: Resolve historical risk/standard conflicts."
    )
    parser.add_argument("--input", type=Path, default=Path("data/iteration1/master_structured_graph.json"))
    parser.add_argument("--truth-output", type=Path, default=Path("data/iteration1/consensus_truth.json"))
    parser.add_argument("--quarantine-output", type=Path, default=Path("data/iteration1/quarantine_queue.json"))
    args = parser.parse_args()

    run_consensus_engine(args.input, args.truth_output, args.quarantine_output)


if __name__ == "__main__":
    main()
