"""Iteration 3 Blueprint — Agent 5: QA Agent V&V Data Contracts.

ARCHITECTURAL REFERENCE IMPLEMENTATION (Sprint-Ready Blueprint):
Direct Python Pydantic implementation of the Contract-Driven Agentic V-Model
defined in `docs/whitepaper/QA_Agent_SOP.pdf`, aligned with:
  - IEEE 1012 (Software Integrity Levels SIL 1–4 & UUID Requirement Traceability)
  - ASME V&V 40 (Risk-informed Model Influence vs. Decision Consequence)
  - ASME V&V 20 (Strict separation of Verification vs. Physics Validation)

Not yet integrated or tested on live production client audits.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SoftwareIntegrityLevel(str, Enum):
    """IEEE 1012 Software Integrity Levels governing V&V rigor."""

    SIL_4 = "SIL 4 (High Criticality - Life Safety Math)"
    SIL_3 = "SIL 3 (High Criticality - Statutory Compliance)"
    SIL_2 = "SIL 2 (Moderate Criticality - Engineering Case Studies)"
    SIL_1 = "SIL 1 (Low Criticality - Technical Communications)"


class OperationalTrack(str, Enum):
    """Bifurcated V&V operational pathways."""

    TRACK_A = "Track A: Engineering Core (Zero-Tolerance Deterministic)"
    TRACK_B = "Track B: Technical Content Core (Semantic Congruence)"


class AdjudicationFlag(str, Enum):
    """Human-in-the-Loop (HITL) Escalation Taxonomy from QA Agent SOP Section 4."""

    PASSED = "PASSED"
    FATAL_ERROR = "[FATAL ERROR]"
    CONTEXTUAL_FAILURE = "[CONTEXTUAL FAILURE]"
    OVERSIMPLIFICATION = "[OVERSIMPLIFICATION]"


EquationType = Literal[
    "hazen_williams",
    "darcy_weisbach",
    "nfpa_557_fire_load",
    "bernoulli_head",
    "dyke_containment_110",
]


class ContextOfUse(BaseModel):
    """Physical boundary conditions required for ASME V&V 20 Physics Validation."""

    fluid_temp_c: float | None = Field(
        default=None, description="Water temperature in degrees Celsius (Hazen-Williams valid 4-14 C)."
    )
    flow_velocity_m_s: float | None = Field(
        default=None, description="Fluid velocity in m/s (>7.6 m/s invalidates Hazen-Williams per NFPA 750)."
    )
    pipe_material: str | None = Field(
        default=None, description="Pipe material name for deterministic C-factor lookup."
    )
    is_water_mist_system: bool = Field(
        default=False, description="High-pressure water mist systems mandate Darcy-Weisbach (NFPA 750)."
    )


class MathematicalContract(BaseModel):
    """Track A (SIL 4) contract isolating numerical claims for AST REPL verification."""

    claim_id: UUID = Field(default_factory=uuid4)
    original_text: str
    target_variable: str
    equation_type: EquationType
    input_parameters: dict[str, float]
    claimed_result: float
    sil: SoftwareIntegrityLevel = SoftwareIntegrityLevel.SIL_4
    context_of_use: ContextOfUse = Field(default_factory=ContextOfUse)


class StatutoryContract(BaseModel):
    """Track A (SIL 3) contract enforcing 100% verbatim statutory citation checks."""

    claim_id: UUID = Field(default_factory=uuid4)
    original_text: str
    referenced_standard: str = Field(description="e.g., 'NFPA 13', 'NBC 2016', 'IS 15105', 'IS 2190'")
    clause_number: str
    quoted_text: str
    sil: SoftwareIntegrityLevel = SoftwareIntegrityLevel.SIL_3


class ContextualContract(BaseModel):
    """Track B (SIL 1-2) contract evaluating semantic alignment of technical prose."""

    claim_id: UUID = Field(default_factory=uuid4)
    claim_statement: str
    engineering_domain: str
    sil: SoftwareIntegrityLevel = SoftwareIntegrityLevel.SIL_2
    cosine_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    contains_bounding_parameters: bool = True


class ValidationReport(BaseModel):
    """Closed-loop IEEE 1012 Requirement Traceability output from the QA Gateway."""

    claim_id: UUID
    track: OperationalTrack
    sil: SoftwareIntegrityLevel
    verification_passed: bool = Field(
        description="ASME V&V 20 Verification: Did the math or exact citation match?"
    )
    validation_passed: bool = Field(
        description="ASME V&V 20 Validation: Was the physically/legally appropriate model chosen?"
    )
    flag: AdjudicationFlag
    calculated_result: float | None = None
    claimed_result: float | None = None
    absolute_deviation: float | None = None
    diagnostic_trace: str
    requires_human_adjudication: bool
