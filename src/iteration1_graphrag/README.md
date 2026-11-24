# Iteration 1 Archive: Observation-Anchored Hybrid GraphRAG (Neo4j Hourglass)

This directory preserves the original 6-stage Proof-of-Concept built in June 2026 to test whether legacy Fire Safety Audit (`.docx`) reports could be compiled into an observation-anchored Neo4j Knowledge Graph.

## Pipeline Architecture
1. **`step1_ingestion.py`** — Parses `.docx` compliance matrices via dynamic header hunting, nested table flattening, and italic-run quote separation.
2. **`step2_gemini_structuring.py`** — Maps raw CSV rows into strict `ComplianceNode` Pydantic schemas with disk checkpointing and HTTP 429 cooldowns.
3. **`step3_consensus_engine.py`** — Detects historical auditor contradictions, routing Status/Standard conflicts to a HITL quarantine queue and escalating Risk disagreements via the **High-Water Mark** protocol.
4. **`step4_taxonomy_compiler.py`** — Compresses chaotic observations per component into a maximum of 5 standardized `FailureMode` nodes.
5. **`step5_neo4j_hourglass_injection.py`** — Builds the Hourglass ontology in Neo4j (`Area -> Component -> FailureMode -> MitigationRule -> Standard`).
6. **`step6_agentic_ui.py`** — Streamlit prototype using a zero-temperature LLM strictly as a semantic router over valid Neo4j `FailureMode` pathways.

## Why Iteration 1 Was Superseded
As documented in **Section 2.5** of the companion whitepaper (`docs/whitepaper/Architecting_Determinism_FSA_Whitepaper.pdf`), anchoring the ontology on historical audit reports exposed five structural failure modes:
- Free-tier API rate-limit walls (175-day ingestion bottleneck for 3,500+ nodes).
- **The Ambiguity Trap (GIGO):** Unscalable manual adjudication of contradictory historical ratings and omitted citations.
- **Vector Blur:** High linguistic similarity between legally opposite components (e.g., Butterfly Valve vs. OS&Y Gate Valve on pump suction).
- **Flat Schema Brittleness** and **Site-Naming Ontology Drift** across facilities.

These findings directly motivated the pivot to **Iteration 2 (`src/iteration2_retrieval/`)** and **Iteration 3 (`src/iteration3_mas_blueprint/`)**.
