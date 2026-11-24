"""Automated Unit Test Suite for Iteration 3 Pilot Parser & MAS Reference Blueprints.

Run with:
    pytest tests/test_iteration3_blueprint.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.iteration3_mas_blueprint.ast_repl_sandbox import (
    ASTSecurityViolation,
    evaluate_contextual_contract,
    evaluate_mathematical_contract,
    evaluate_statutory_contract,
    safe_evaluate_expression,
)
from src.iteration3_mas_blueprint.intake_schemas import (
    FacilityIntakeState,
    MasterFacilityEnvelope,
    MicroZoneSpec,
    PrerequisiteChecklist,
)
from src.iteration3_mas_blueprint.qa_contracts import (
    AdjudicationFlag,
    ContextOfUse,
    ContextualContract,
    MathematicalContract,
    SoftwareIntegrityLevel,
    StatutoryContract,
)
from src.iteration3_mas_blueprint.xhtml_code_parser import (
    parse_is_standard_v4,
    run_deterministic_audit_suite,
)


# ==========================================
# 1. XHTML PARSER & 5-TEST AUDIT SUITE
# ==========================================
def test_xhtml_parser_unfolds_tables_and_passes_5_tests(tmp_path: Path) -> None:
    sample_xhtml = """<?xml version="1.0" encoding="UTF-8"?>
    <html><body>
      <p class="head2">1 SCOPE</p>
      <p><span style="font-weight:bold">1.1</span> This pilot standard specifies portable fire extinguisher selection.</p>
      <p class="head2">2 EXTINGUISHER SELECTION</p>
      <p><span style="font-weight:bold">2.1</span> Extinguishers shall be selected according to fire class and occupancy.</p>
      <div id="tbl_001" class="tblscroll">
        <p class="table_label_caption1">Table 1 Extinguisher Suitability Matrix</p>
        <table>
          <tr><th>Fire Class</th><th>Primary Agent</th><th>Primary Agent</th></tr>
          <tr><td rowspan="2">Class B</td><td>Mechanical Foam</td><td>CO2</td></tr>
          <tr><td>DCP</td><td>Clean Agent</td></tr>
          <tr><td colspan="3">NOTE - Foam shall not be used on energized electrical equipment.</td></tr>
        </table>
      </div>
      <p><span style="font-weight:bold">2.1.1</span> Travel distance to any extinguisher shall not exceed 15 m.</p>
      <p class="head2">BUREAU OF INDIAN STANDARDS</p>
      <p>Copyright notice excluded from parsing.</p>
    </body></html>
    """
    xhtml_file = tmp_path / "sample_standard.xhtml"
    xhtml_file.write_text(sample_xhtml, encoding="utf-8")

    db = parse_is_standard_v4(xhtml_file, "IS 2190:PILOT")
    audit = run_deterministic_audit_suite(xhtml_file, db)

    assert audit["all_structural_tests_passed"] is True
    assert audit["word_recovery_pct"] >= 95.0
    assert audit["json_table_count"] == 1
    assert db["tables"][0]["headers"] == ["Fire Class", "Primary Agent", "Primary Agent_1"]
    assert len(db["tables"][0]["structured_data"]) == 2
    # Verify rowspan propagated "Class B" into row 2
    assert db["tables"][0]["structured_data"][1]["Fire Class"] == "Class B"
    assert len(db["tables"][0]["table_notes"]) == 1
    # Verify foreign-key link attached to clause 2.1
    clause_2_1 = [c for c in db["clauses"] if c["clause_number"] == "2.1"][0]
    assert "tbl_001" in clause_2_1["linked_tables"]


# ==========================================
# 2. INTAKE & SCOPING AGENT CONTRACTS
# ==========================================
def test_intake_schema_flags_missing_baseline_and_electrical_hazard() -> None:
    state = FacilityIntakeState(
        prerequisites=PrerequisiteChecklist(
            submitted_documents=["Overall Site Plot Plan", "Electrical Single Line Diagram (SLD)"]
        ),
        envelope=MasterFacilityEnvelope(
            facility_id="Facility Alpha",
            occupancy_classification="Group G-2 (Moderate Hazard Industrial)",
            construction_vintage_year=2012,
            independent_islands_count=2,
            gross_built_up_area_m2=18500.0,
            h_max_m=16.5,
            subterranean_levels_count=1,
            external_perimeter_m=620.0,
            static_fire_water_tank_liters=None,  # Missing baseline -> halts Orchestrator
        ),
        micro_zones=[
            MicroZoneSpec(
                zone_name="Main Substation",
                macro_zone="Utility",
                electrical_voltage_class="MV (1kV-33kV)",
                water_sprinklers_installed=True,  # Fatal hazard!
                clear_ceiling_height_m=11.2,
                beam_depth_pct_of_ceiling=12.5,
                false_ceiling_void_depth_mm=900.0,
                hydrocarbon_liquid_volume_liters=1000.0,
                transformer_rating_mva=16.0,
                transformer_oil_volume_liters=3500.0,
            )
        ],
    )

    summary = state.summarize_readiness()
    assert summary["orchestrator_ready"] is False
    assert len(summary["rfi"]["missing_mandatory_rfi"]) == 11
    assert any("ORCHESTRATOR_HALT" in t for t in summary["global_triggers"])
    assert any("NBC_2016_HIGH_RISE" in t for t in summary["global_triggers"])

    sub_triggers = summary["zonal_triggers"]["Main Substation"]
    assert any("[FATAL_HAZARD]" in t for t in sub_triggers)
    assert any("IS_2189_CL_6_3_3" in t for t in sub_triggers)
    assert any("IS_2189_CL_6_3_2_F" in t for t in sub_triggers)
    assert any("IS_2189_CL_6_3_2_T" in t for t in sub_triggers)
    assert any("1100.0 L" in t for t in sub_triggers)
    assert any("NIFPS" in t for t in sub_triggers)


# ==========================================
# 3. AST PYTHON REPL SANDBOX SECURITY
# ==========================================
@pytest.mark.parametrize(
    "malicious_expr",
    [
        "__import__('os').system('echo pwned')",
        "eval('2 + 2')",
        "().__class__.__base__.__subclasses__()",
        "open('/etc/passwd').read()",
        "[x for x in range(10)]",
    ],
)
def test_ast_sandbox_blocks_code_injection(malicious_expr: str) -> None:
    with pytest.raises(ASTSecurityViolation):
        safe_evaluate_expression(malicious_expr, {"x": 1.0})


# ==========================================
# 4. ASME V&V 20 VERIFICATION VS VALIDATION
# ==========================================
def test_hazen_williams_passes_verification_and_validation() -> None:
    # Q=1000 L/min, C=120 (galvanized steel), d=100 mm
    expected_p = 6.05e5 * (1000.0 ** 1.85) * (120.0 ** -1.85) * (100.0 ** -4.87)
    contract = MathematicalContract(
        original_text="Friction loss is 0.006125 bar/m for 1000 L/min in 100 mm galvanized steel pipe.",
        target_variable="pressure_drop_bar_per_m",
        equation_type="hazen_williams",
        input_parameters={"Q": 1000.0, "C": 120.0, "d": 100.0},
        claimed_result=round(expected_p, 6),
        context_of_use=ContextOfUse(
            fluid_temp_c=10.0,
            flow_velocity_m_s=2.1,
            pipe_material="galvanized_steel",
            is_water_mist_system=False,
        ),
    )
    report = evaluate_mathematical_contract(contract)
    assert report.verification_passed is True
    assert report.validation_passed is True
    assert report.flag == AdjudicationFlag.PASSED
    assert report.requires_human_adjudication is False


def test_hazen_williams_math_hallucination_triggers_fatal_error() -> None:
    contract = MathematicalContract(
        original_text="Claimed friction loss is 0.15 bar/m.",
        target_variable="pressure_drop_bar_per_m",
        equation_type="hazen_williams",
        input_parameters={"Q": 1000.0, "C": 120.0, "d": 100.0},
        claimed_result=0.15,  # Hallucinated value
        context_of_use=ContextOfUse(fluid_temp_c=10.0, flow_velocity_m_s=2.1),
    )
    report = evaluate_mathematical_contract(contract)
    assert report.verification_passed is False
    assert report.flag == AdjudicationFlag.FATAL_ERROR
    assert report.requires_human_adjudication is True


def test_hazen_williams_valid_math_but_invalid_physics_triggers_contextual_failure() -> None:
    expected_p = 6.05e5 * (1000.0 ** 1.85) * (120.0 ** -1.85) * (100.0 ** -4.87)
    contract = MathematicalContract(
        original_text="Water mist system calculated via Hazen-Williams at 9.2 m/s.",
        target_variable="pressure_drop_bar_per_m",
        equation_type="hazen_williams",
        input_parameters={"Q": 1000.0, "C": 120.0, "d": 100.0},
        claimed_result=round(expected_p, 6),
        context_of_use=ContextOfUse(
            fluid_temp_c=22.0,
            flow_velocity_m_s=9.2,
            pipe_material="galvanized_steel",
            is_water_mist_system=True,
        ),
    )
    report = evaluate_mathematical_contract(contract)
    # Math verified, Physics validation failed -> [CONTEXTUAL FAILURE]
    assert report.verification_passed is True
    assert report.validation_passed is False
    assert report.flag == AdjudicationFlag.CONTEXTUAL_FAILURE
    assert report.requires_human_adjudication is True


def test_zero_inference_rule_halts_on_missing_parameters() -> None:
    contract = MathematicalContract(
        original_text="Dyke volume is 1100 L.",
        target_variable="dyke_volume_liters",
        equation_type="dyke_containment_110",
        input_parameters={},  # Missing tank_volume_liters
        claimed_result=1100.0,
    )
    report = evaluate_mathematical_contract(contract)
    assert report.calculated_result is None
    assert report.flag == AdjudicationFlag.FATAL_ERROR


# ==========================================
# 5. STATUTORY VERBATIM & TRACK B SEMANTIC CHECKS
# ==========================================
def test_statutory_verbatim_pass_and_hallucination_halt() -> None:
    truth = "A listed outside screw and yoke (OS&Y) gate valve shall be installed in the suction pipe."
    good = StatutoryContract(
        original_text="NFPA 20 requires OS&Y valves.",
        referenced_standard="NFPA 20",
        clause_number="4.16.5.1",
        quoted_text="A listed outside screw and yoke (OS&Y) gate valve shall be installed in the suction pipe.",
    )
    assert evaluate_statutory_contract(good, truth).flag == AdjudicationFlag.PASSED

    hallucinated = StatutoryContract(
        original_text="Butterfly valves are allowed.",
        referenced_standard="NFPA 20",
        clause_number="99.99",
        quoted_text="Butterfly valves may be used freely.",
    )
    assert evaluate_statutory_contract(hallucinated, None).flag == AdjudicationFlag.FATAL_ERROR


def test_track_b_semantic_thresholds() -> None:
    high = ContextualContract(
        claim_statement="Friction increases with flow rate to the 1.85 power in Schedule 40 steel.",
        engineering_domain="Hydraulics",
        sil=SoftwareIntegrityLevel.SIL_2,
        cosine_similarity=0.91,
        contains_bounding_parameters=True,
    )
    assert evaluate_contextual_contract(high).flag == AdjudicationFlag.PASSED

    simplified = ContextualContract(
        claim_statement="Long pipes reduce water pressure due to friction.",
        engineering_domain="Hydraulics",
        sil=SoftwareIntegrityLevel.SIL_2,
        cosine_similarity=0.81,
        contains_bounding_parameters=False,
    )
    assert evaluate_contextual_contract(simplified).flag == AdjudicationFlag.OVERSIMPLIFICATION

    wrong = ContextualContract(
        claim_statement="Increasing pipe diameter increases friction loss.",
        engineering_domain="Hydraulics",
        sil=SoftwareIntegrityLevel.SIL_2,
        cosine_similarity=0.52,
    )
    assert evaluate_contextual_contract(wrong).flag == AdjudicationFlag.FATAL_ERROR
