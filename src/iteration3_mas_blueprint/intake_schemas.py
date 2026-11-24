"""Iteration 3 Blueprint — Agent 1: Intake & Scoping Pydantic Contracts.

ARCHITECTURAL REFERENCE IMPLEMENTATION (Sprint-Ready Blueprint):
First-draft Python realization of the two-tier Intake Schema and 21-document
Prerequisite Matrix specified in Section 4.5 of the whitepaper to resolve the
'Missing Baseline Anomaly'. Not yet tested against live client audit workflows.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ==========================================
# 1. PREREQUISITE DOCUMENT MATRIX (21 DOCS)
# ==========================================
PREREQUISITE_DOCUMENTS: list[tuple[str, bool]] = [
    ("Overall Site Plot Plan", True),
    ("Fire Protection Design Basis Report (DBR)", True),
    ("Fire Water Pump House P&ID Layout", True),
    ("External & Internal Hydrant Network Layout", True),
    ("Automatic Sprinkler Layout & Hydraulic Calculations", True),
    ("Fire Detection & Alarm System (FDAS) Zone Layout", True),
    ("Portable Fire Extinguisher (PFE) Distribution Layout", True),
    ("Valid Local Fire Department NOC", True),
    ("Hazardous Area Classification (HAC) Layout", True),
    ("Electrical Single Line Diagram (SLD)", True),
    ("Transformer & Substation Layout (MVA & Oil Ratings)", True),
    ("Emergency Evacuation & Escape Route Plans", True),
    ("Static Fire Water Tank Capacity & As-Built Drawings", True),
    ("Fire Pump Periodic Testing & Maintenance Logs", False),
    ("Pressure Gauge & Switch Calibration Certificates", False),
    ("Fire Extinguisher Hydro-Testing & Refill Records", False),
    ("Annual Fire Alarm Sensitivity & Maintenance Logs", False),
    ("Emergency Mock Drill & Fire Training Records", False),
    ("Gas Suppression / Clean Agent Cylinder Integrity Certificates", False),
    ("Previous Fire Safety Audit Compliance Closure Report", False),
    ("MSDS / Combustible Inventory & Chemical Storage Manifest", False),
]


class PrerequisiteChecklist(BaseModel):
    """Tracks availability of the 21 prerequisite client documents and generates RFIs."""

    submitted_documents: list[str] = Field(
        default_factory=list,
        description="Document titles successfully received from the client.",
    )

    def generate_rfi(self) -> dict[str, list[str]]:
        """Identifies missing mandatory and advisory documents for an automated RFI."""
        submitted_norm = {d.strip().lower() for d in self.submitted_documents}
        missing_mandatory = [
            doc for doc, mandatory in PREREQUISITE_DOCUMENTS
            if mandatory and doc.lower() not in submitted_norm
        ]
        missing_optional = [
            doc for doc, mandatory in PREREQUISITE_DOCUMENTS
            if not mandatory and doc.lower() not in submitted_norm
        ]
        return {
            "missing_mandatory_rfi": missing_mandatory,
            "missing_advisory_rfi": missing_optional,
        }


# ==========================================
# 2. TIER 1: MASTER FACILITY ENVELOPE
# ==========================================
OccupancyGroup = Literal[
    "Group A (Residential)",
    "Group B (Educational)",
    "Group C (Institutional / Hospital)",
    "Group D (Assembly)",
    "Group E (Business / Office)",
    "Group F (Mercantile)",
    "Group G-1 (Low Hazard Industrial)",
    "Group G-2 (Moderate Hazard Industrial)",
    "Group G-3 (High Hazard Industrial)",
    "Group H (Storage)",
    "Group J (Hazardous)",
]


class MasterFacilityEnvelope(BaseModel):
    """Global facility boundary parameters governing NBC 2016 Part 4 Table 7 compliance."""

    facility_id: str = Field(description="Anonymized facility identifier (e.g., Facility Alpha).")
    occupancy_classification: OccupancyGroup
    construction_vintage_year: int = Field(
        ge=1900, le=2030, description="Year of original construction (governs grandfathering rules)."
    )
    independent_islands_count: int = Field(ge=1, description="Number of segregated building blocks.")
    gross_built_up_area_m2: float = Field(gt=0, description="Total floor plate area in m^2.")
    h_max_m: float = Field(
        gt=0,
        description="Highest building elevation datum (H_max in meters). >15m triggers high-rise rules.",
    )
    subterranean_levels_count: int = Field(ge=0, description="Number of basement levels.")
    external_perimeter_m: float = Field(gt=0, description="External road/hydrant loop perimeter in meters.")
    static_fire_water_tank_liters: float | None = Field(
        default=None,
        ge=0,
        description="Dedicated static fire water tank capacity in liters (null halts Orchestrator).",
    )
    fire_network_architecture: Literal["Separate Hydrant & Sprinkler", "Combined Network"] = (
        "Separate Hydrant & Sprinkler"
    )
    ambient_water_temp_c: float = Field(
        default=25.0, description="Ambient water supply temperature in degrees Celsius."
    )

    def evaluate_global_triggers(self) -> list[str]:
        """Returns proactive statutory triggers derived from global facility boundaries."""
        triggers: list[str] = []
        if self.static_fire_water_tank_liters is None:
            triggers.append("ORCHESTRATOR_HALT: Static fire water tank capacity is null; request baseline data.")
        if self.h_max_m > 15.0:
            triggers.append("NBC_2016_HIGH_RISE: H_max > 15 m triggers high-rise egress, refuge, and riser mandates.")
        if self.subterranean_levels_count > 0:
            triggers.append("NBC_2016_BASEMENT: Subterranean level detected; automatic sprinklers & smoke extraction mandatory.")
        if self.construction_vintage_year < 2016:
            triggers.append("GRANDFATHERING_REVIEW: Pre-2016 vintage; verify applicable legacy vs. NBC 2016 clauses.")
        return triggers


# ==========================================
# 3. TIER 2: MICRO-ZONE ARRAY
# ==========================================
class MicroZoneSpec(BaseModel):
    """Room-level physical and hazard parameters driving deterministic code selection."""

    zone_name: str
    macro_zone: Literal["Utility", "Process", "Storage", "Admin", "Others"]
    zonal_hazard_override: str | None = Field(
        default=None, description="Optional localized hazard elevation (e.g., 'Group G-3 Flammable Store')."
    )
    electrical_voltage_class: Literal["None", "LV (<1kV)", "MV (1kV-33kV)", "HV (>33kV)"] = "None"
    water_sprinklers_installed: bool = False
    clear_ceiling_height_m: float = Field(gt=0)
    beam_depth_pct_of_ceiling: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Structural beam depth as % of clear ceiling height."
    )
    false_ceiling_void_depth_mm: float = Field(default=0.0, ge=0.0)
    storage_stacking_height_m: float = Field(default=0.0, ge=0.0)
    hydrocarbon_liquid_volume_liters: float = Field(default=0.0, ge=0.0)
    gas_hazard_type: Literal["None", "PNG (Lighter than air)", "LPG (Heavier than air)", "Hydrogen (H2)"] = "None"
    transformer_rating_mva: float = Field(default=0.0, ge=0.0)
    transformer_oil_volume_liters: float = Field(default=0.0, ge=0.0)
    compartmentation_rating_min: int = Field(
        default=0, ge=0, description="Fire resistance rating of enclosing walls/doors in minutes."
    )

    @model_validator(mode="after")
    def validate_electrical_water_conflict(self) -> "MicroZoneSpec":
        """Enforces NBC 2016 Part 4 Cl. 5.1.3(m): warns/flags water sprinklers in MV/HV rooms."""
        # Stored as an explicit non-compliance trigger rather than crashing intake
        # so real site defects can still be ingested and flagged as [FATAL ERROR].
        return self

    def evaluate_proactive_triggers(self) -> list[str]:
        """Generates deterministic statutory inspection checklists before field drafting."""
        triggers: list[str] = []

        if self.water_sprinklers_installed and self.electrical_voltage_class in {
            "MV (1kV-33kV)",
            "HV (>33kV)",
        }:
            triggers.append(
                "[FATAL_HAZARD] NBC 2016 Part 4 Cl. 5.1.3(m): Water sprinkler system present in "
                f"{self.electrical_voltage_class} electrical zone; mandate clean-agent suppression."
            )

        if self.clear_ceiling_height_m > 10.0:
            triggers.append(
                "IS_2189_CL_6_3_3: Ceiling height > 10 m disqualifies point smoke detectors; "
                "require optical beam or aspirating detection."
            )

        if self.beam_depth_pct_of_ceiling > 10.0:
            triggers.append(
                "IS_2189_CL_6_3_2_F: Structural beams > 10% of ceiling height; treat each beam bay "
                "as an independent detection compartment."
            )

        if self.false_ceiling_void_depth_mm > 800.0:
            triggers.append(
                "IS_2189_CL_6_3_2_T: False ceiling void > 800 mm; concealed detectors with external "
                "response indicators mandatory."
            )

        if self.storage_stacking_height_m > 3.7:
            triggers.append(
                "IS_15105_NFPA_13: Rack stacking > 3.7 m; evaluate in-rack sprinkler density."
            )

        if self.hydrocarbon_liquid_volume_liters > 0:
            required_dyke = round(self.hydrocarbon_liquid_volume_liters * 1.10, 2)
            triggers.append(
                f"NBC_2016_CL_3_4_6_4: Hydrocarbon tank ({self.hydrocarbon_liquid_volume_liters} L) "
                f"requires >= {required_dyke} L (110%) impervious secondary containment dyke."
            )

        if self.gas_hazard_type in {"PNG (Lighter than air)", "Hydrogen (H2)"}:
            triggers.append(
                f"NFPA_715_NFPA_2: {self.gas_hazard_type} rises; mount LEL/H2 detectors at ceiling level."
            )
        elif self.gas_hazard_type == "LPG (Heavier than air)":
            triggers.append(
                "NFPA_715: LPG is heavier than air; mount LEL detectors near floor level (~300 mm above FFL)."
            )

        if self.transformer_oil_volume_liters > 2000.0 and self.transformer_rating_mva >= 10.0:
            triggers.append(
                "NBC_2016_IS_15325: Oil-filled transformer > 2,000 L & >= 10 MVA; mandate HVWS "
                "or Nitrogen Injection Fire Protection System (NIFPS)."
            )
        elif self.transformer_oil_volume_liters > 2000.0:
            triggers.append(
                "IS_15325: Oil-filled transformer > 2,000 L; evaluate MVWS / HVWS & firewall baffle."
            )

        return triggers


class FacilityIntakeState(BaseModel):
    """Complete JSON State Object produced by Agent 1 (Intake & Scoping) for the Orchestrator."""

    prerequisites: PrerequisiteChecklist
    envelope: MasterFacilityEnvelope
    micro_zones: list[MicroZoneSpec] = Field(min_length=1)

    def summarize_readiness(self) -> dict[str, object]:
        rfi = self.prerequisites.generate_rfi()
        global_triggers = self.envelope.evaluate_global_triggers()
        zonal_triggers = {
            z.zone_name: z.evaluate_proactive_triggers() for z in self.micro_zones
        }
        can_proceed = (
            len(rfi["missing_mandatory_rfi"]) == 0
            and self.envelope.static_fire_water_tank_liters is not None
        )
        return {
            "orchestrator_ready": can_proceed,
            "rfi": rfi,
            "global_triggers": global_triggers,
            "zonal_triggers": zonal_triggers,
        }
