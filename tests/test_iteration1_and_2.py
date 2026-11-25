"""Offline Unit Tests for Iteration 1 Consensus Engine & Iteration 2 Core Modules.

Runs fast with zero network/model downloads to validate deterministic logic:
  - Iteration 1: High-Water Mark risk escalation & HITL quarantine routing.
  - Iteration 2: Alias Engine normalization, 25-acronym Jargon Expander,
                 Complied hard filter, deduplication sieve, and live DocxTpl
                 Word audit report compilation against the anonymized template.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from docx import Document
from PIL import Image

from src.iteration1_graphrag.step3_consensus_engine import resolve_consensus
from src.iteration2_retrieval.alias_engine import (
    clean_and_normalize_area,
    cluster_micro_area,
    normalize_records,
    route_component_category,
    route_macro_zone,
)
from src.iteration2_retrieval.docxtpl_exporter import (
    DEFAULT_TEMPLATE_PATH,
    compile_audit_report,
    process_image,
    sanitize_text,
)
from src.iteration2_retrieval.hybrid_rrf_engine import (
    deduplicate_results,
    expand_engineering_jargon,
)


def test_iteration1_consensus_engine_three_triggers() -> None:
    nodes = [
        {
            "Parent_Area": "Pump Room",
            "Component_Name": "Isolation Valve",
            "Observation_Summary": "Butterfly valve installed on suction.",
            "Compliance_Status": "Non-Complied",
            "Historical_Risk": "HIGH",
            "Standard_Violated": "NFPA 20",
            "Raw_Recommendation": "Replace with OS&Y gate valve.",
            "Raw_Quote": "OS&Y gate valve shall be installed.",
        },
        {
            "Parent_Area": "Pump Room",
            "Component_Name": "Y-Strainer",
            "Observation_Summary": "Missing Y-strainer.",
            "Compliance_Status": "Non-Complied",
            "Historical_Risk": "LOW",
            "Standard_Violated": "IS 15301",
            "Raw_Recommendation": "Provide Y-strainer.",
            "Raw_Quote": "",
        },
        {
            "Parent_Area": "Pump Room",
            "Component_Name": "Y-Strainer",
            "Observation_Summary": "Missing Y-strainer.",
            "Compliance_Status": "Non-Complied",
            "Historical_Risk": "MEDIUM",
            "Standard_Violated": "IS 15301",
            "Raw_Recommendation": "Provide Y-strainer.",
            "Raw_Quote": "",
        },
        {
            "Parent_Area": "DG Room",
            "Component_Name": "Day Tank",
            "Observation_Summary": "No dyke wall.",
            "Compliance_Status": "Non-Complied",
            "Historical_Risk": "HIGH",
            "Standard_Violated": "NBC 2016",
            "Raw_Recommendation": "Build 110% dyke.",
            "Raw_Quote": "",
        },
        {
            "Parent_Area": "DG Room",
            "Component_Name": "Day Tank",
            "Observation_Summary": "No dyke wall.",
            "Compliance_Status": "Partially Complied",
            "Historical_Risk": "MEDIUM",
            "Standard_Violated": "N/A",
            "Raw_Recommendation": "Build 110% dyke.",
            "Raw_Quote": "",
        },
    ]

    truth, quarantine = resolve_consensus(nodes)
    assert len(truth) == 2
    assert len(quarantine) == 1
    y_node = [n for n in truth if n["Component_Name"] == "Y-Strainer"][0]
    assert y_node["Consensus_Risk"] == "MEDIUM"
    assert y_node["Consensus_Status"] == "ESCALATED TRUTH (High-Water Mark)"
    assert quarantine[0]["Consensus_Status"] == "LOGICAL CONFLICT - QUARANTINED"


def test_iteration2_alias_engine_normalizes_sample_dataset() -> None:
    sample_path = Path("data/sample_routed_extract.json")
    assert sample_path.exists()
    records = json.loads(sample_path.read_text(encoding="utf-8"))
    normalized = normalize_records(records)

    assert len(normalized) == 10
    assert clean_and_normalize_area("RAW MILL TRANSFORMER (1600 KVA x 3) LINE-1") == "raw mill transformer"
    assert route_macro_zone("main substation") == "Utility"
    assert cluster_micro_area("DIESEL GENERATOR ROOM (1500 KVA)") == "DG Room"
    assert route_component_category("Y-Strainers") == "Pump Room Fittings & Piping"
    assert normalized[0]["clean_micro_area"] == "Fire Water Pump Room"


def test_iteration2_jargon_expander_and_deduplication_sieve() -> None:
    expanded = expand_engineering_jargon("missing foam pfe in dg room & fdas mcc")
    assert "portable fire extinguisher" in expanded.lower()
    assert "diesel generator" in expanded.lower()
    assert "fire detection and alarm system" in expanded.lower()
    assert "motor control center" in expanded.lower()

    candidates = [
        {"compliance_status": "Complied", "recommendation": "None", "standard_reference": "IS 2190"},
        {"compliance_status": "Non-Complied", "recommendation": "Provide foam PFE.", "standard_reference": "IS 2190"},
        {"compliance_status": "Non-Complied", "recommendation": "Provide foam PFE.", "standard_reference": "IS 2190"},
        {"compliance_status": "Non-Complied", "recommendation": "Install OS&Y gate valve.", "standard_reference": "NFPA 20"},
    ]
    unique = deduplicate_results(candidates, top_n=5, exclude_complied=True)
    assert len(unique) == 2
    assert unique[0]["standard_reference"] == "IS 2190"
    assert unique[1]["standard_reference"] == "NFPA 20"


def test_iteration2_docxtpl_exporter_compiles_valid_word_report() -> None:
    assert sanitize_text("**High** `risk`") == "High risk"
    assert sanitize_text("null") == ""

    # Create an in-memory synthetic JPEG photo to test Pillow cropping & InlineImage injection
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), color=(40, 100, 180)).save(buf, format="JPEG")
    buf.seek(0)
    cropped = process_image(buf)

    sample_obs = [
        {
            "area_name": "FIRE WATER PUMP ROOM",
            "system_name": "Isolation Valve",
            "compliance_status": "Non-Complied",
            "observation": "Butterfly valves installed on pump suction header.",
            "recommendation": "Replace with OS&Y gate valves.",
            "standard_reference": "NFPA 20 Clause 4.16.5.1",
            "risk_raw": "HIGH",
            "sub_tag_raw": "H",
            "remarks": "Verify during next shutdown.",
            "raw_images": [cropped],
        }
    ]

    docx_stream = compile_audit_report(sample_obs, template_path=DEFAULT_TEMPLATE_PATH)
    rendered = Document(docx_stream)
    all_text = "\n".join(
        cell.text for table in rendered.tables for row in table.rows for cell in row.cells
    )
    assert "FIRE WATER PUMP ROOM" in all_text
    assert "Butterfly valves installed on pump suction header." in all_text
    assert "NFPA 20 Clause 4.16.5.1" in all_text
