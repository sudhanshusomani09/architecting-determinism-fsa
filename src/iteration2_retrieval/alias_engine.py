"""Deterministic Phase 2 Alias Engine: Taxonomy Normalization & Macro-Zone Routing.

Standardizes fragmented industrial audit records across three deterministic passes:
  1. Regex String Normalization: Strips equipment capacities (KVA/MVA/KV), line tags,
     parenthetical suffixes, and plural variations.
  2. Macro-Zone Priority Routing: Maps site-specific room titles into 5 strict
     Macro-Zones (Utility, Process, Storage, Admin, Others) and clean UI area clusters.
  3. Parent-Child Component Mapping: Maps 200+ raw auditor component variants into
     15 Master Categories while preserving exact child asset names for reporting.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

# ==========================================
# 1. TAXONOMY CONFIGURATION MATRICES
# ==========================================
ZONE_PRIORITY_RULES: list[tuple[str, list[str]]] = [
    (
        "Utility",
        [
            "substation", "transformer", "generator", "compressor", "pump", "mcc",
            "panel", "cellar", "dg", "wtp", "hydrant", "tunnel", "battery", "ups",
        ],
    ),
    (
        "Process",
        [
            "mill", "crusher", "kiln", "mixer", "packing", "plant", "boiler",
            "preheater", "loading", "tippler", "hangar", "manufacturing",
            "machining", "esp", "cbs", "conveyor",
        ],
    ),
    (
        "Storage",
        [
            "yard", "silo", "warehouse", "stockpile", "godown", "hopper", "shed",
            "bulk", "tank", "bin", "store", "dike", "containment",
        ],
    ),
    (
        "Admin",
        [
            "office", "canteen", "security", "hospital", "medical", "clinic",
            "control", "room", "laboratory", "training", "admin", "hod", "ohc",
        ],
    ),
    ("Others", ["helipad", "petrol", "parking", "road", "outside", "boundary"]),
]

COMPONENT_CATEGORY_MAP: dict[str, list[str]] = {
    "Fire Detection & Alarm Systems (FDAS)": [
        "automatic detection system",
        "automatic fire detection & alarm system",
        "automatic fire detection & alarm system (smoke detectors)",
        "automatic fire detection system",
        "automatic fire detection system (beam detector)",
        "automatic fire detection and alarm system",
        "automatic fire detection and alarm system (smoke detectors)",
        "automatic fire detectors",
        "beam detection system",
        "beam detector",
        "conveyor fire detection system",
        "fire detection",
        "fire detection & alarm system",
        "fire detection system",
        "fire detection system & pfe",
        "fire detection and alarm system",
        "fire detection and alarm system (fdas)",
        "fire extinguishers and fdas",
        "heat detection system",
        "smoke detector",
        "smoke detectors",
        "manual call point",
    ],
    "Gas Leak Detection Systems": [
        "h2 detection system",
        "hydrogen detection system",
        "hydrogen gas detection system",
        "lel gas detectors",
        "lel gas leak detection system",
    ],
    "Portable Fire Extinguishers (PFE)": [
        "portable fire extinguisher",
        "portable fire extinguisher (co2 and dcp type)",
        "portable fire extinguisher (co2 type)",
        "portable fire extinguisher (foam type)",
        "portable fire extinguisher (pfe)",
        "portable fire extinguishers",
        "portable fire extinguishers (pfes)",
        "portable fire extinguishers (foam type)",
        "sand buckets",
    ],
    "Hydrant & Hose Systems": [
        "external hydrant",
        "external hydrant (spacing)",
        "external hydrant outlet",
        "external hydrant system",
        "external hydrant system and portable extinguishers",
        "fire brigade inlet connection",
        "hose box",
        "hose reel",
        "hose reels",
        "hydrant & monitor",
        "hydrant accessibility",
        "hydrant coverage",
        "hydrant height",
        "hydrant network",
        "hydrant network and spacing",
        "hydrant pipe size",
        "hydrant point",
        "hydrant system",
        "hydrant system (hose boxes)",
        "internal hydrant",
        "internal hydrant system",
        "internal hydrants",
    ],
    "Automatic Sprinkler Systems": [
        "automatic fire sprinkler system",
        "automatic sprinkler system",
        "automatic sprinkler systems",
        "fire sprinkler system",
        "sprinkler system",
        "sprinkler system design (calculation errors)",
        "sprinkler system design (design density)",
        "sprinkler system design (hazard classification & pump capacities)",
        "sprinkler system design (hazard classification)",
        "sprinkler system design (k-factor)",
    ],
    "Fixed Water Spray & Monitor Systems": [
        "hvws (high velocity water spray) system",
        "hvws system",
        "mvws system",
        "mvws for coal conveyor",
        "medium velocity water spray (mvws) system",
        "medium velocity water spray system",
        "water monitor",
        "water monitors",
        "water spray system",
        "foam monitor",
    ],
    "Gas & Special Suppression Systems": [
        "co2 purging system",
        "fire suppression system",
        "fire suppression system (nitrogen injection system)",
        "fire suppression systems",
        "gas suppression system",
        "kitchen hood suppression system",
        "local flooding system",
        "panel flooding system",
        "lel in panel flooding system",
        "transformer protection system",
        "transformer protection system (nitrogen injection system)",
    ],
    "Fire Water Pumping Systems": [
        "diesel engine pump set",
        "diesel transfer pumps",
        "fire pumps",
        "fire water pumps",
        "pump capacities",
        "pump control panel",
        "pump detail plate",
        "pump testing and periodical maintenance",
        "pump casing",
        "pump suction",
        "pump pressure settings",
        "pressure setting",
    ],
    "Pump Room Fittings & Piping": [
        "air vessel",
        "check valve",
        "concentric reducer for pump suction",
        "concentric reducer on pump suction",
        "eccentric reducer on pump suction",
        "gate valve",
        "gland couplings",
        "gland packing",
        "inspection test line",
        "isolation valve",
        "isolation valves",
        "non-return valve",
        "os&y (outside screw & yoke) gate valves on suction side",
        "os&y valve",
        "p&id for pump room",
        "p&id layout plan",
        "pressure gauges/switches",
        "pressure relief line",
        "pressure relief valve",
        "pressure gauge and switches calibration",
        "reducer on pump suction",
        "test line",
        "valves",
        "y-strainers",
        "strainers",
    ],
    "Fire Water Storage Tanks": [
        "fire water storage tank cleaning",
        "fire water tank",
        "fire water tank cleaning",
        "fire water tanks",
        "primming tank",
        "priming tank",
        "level indicator",
        "water level indicator",
        "water level indicator on fire water storage tank",
    ],
    "Secondary Containment & Dykes": [
        "day tanks",
        "diesel storage",
        "dike walls",
        "dyke for diesel storage",
        "secondary containment",
        "secondary containment tank",
        "secondary containment tank for diesel tank",
        "spill containment tank",
        "hsd tank",
    ],
    "Passive Fire Protection (PFP)": [
        "baffle wall",
        "baffle walls",
        "cable protection",
        "cable sealants",
        "fire door",
        "fire rated door",
        "fire rated partition",
        "fire rated partition and door",
        "passive fire protection",
        "pipe and cable trenches",
        "false ceiling",
        "electrical cable management",
    ],
    "Life Safety & Egress": [
        "emergency exit",
        "emergency exit & exit signage",
        "emergency exit & exit signages",
        "emergency exit and exit signage",
        "emergency exit and exit signages",
        "emergency exit and signages",
        "emergency exits",
        "emergency lighting",
        "emergency lights",
        "emergency response plan",
        "escape route marking and signages",
        "evacuation plan",
        "documentation",
    ],
    "Electrical Safety & Hazardous Area Compliance": [
        "bonding and earthing",
        "electrical equipment",
        "flame proof equipment",
        "flame proof light",
        "flameproof electrical equipment",
        "flameproof equipment",
        "lightening protection",
        "lightning protection",
        "prv discharge (spray dryer png manifold)",
        "transformers",
        "mv panels",
        "calibration",
    ],
    "General Layout & Housekeeping": [
        "clearances",
        "general observation",
        "general observation (halogen lights)",
        "general observation (housekeeping)",
        "general observation (pipe trenches, cables)",
        "housekeeping/clearance",
        "presence of combustible materials",
        "pump room drainage",
        "drainpipe trench",
        "vegetation management",
        "walkway clearances",
    ],
}

LINGUISTIC_FIXES: dict[str, str] = {
    "substations": "substation",
    "transformers": "transformer",
    "generators": "generator",
    "compressors": "compressor",
    "pumps": "pump",
    "panels": "panel",
    "cellars": "cellar",
    "yards": "yard",
    "silos": "silo",
    "warehouses": "warehouse",
    "stockpiles": "stockpile",
    "godowns": "godown",
    "hoppers": "hopper",
    "sheds": "shed",
    "tanks": "tank",
    "bins": "bin",
    "stores": "store",
    "offices": "office",
    "canteens": "canteen",
    "hospitals": "hospital",
    "clinics": "clinic",
    "laboratories": "laboratory",
    "rooms": "room",
    "tunnels": "tunnel",
}

RAW_TO_PARENT_COMP_MAP: dict[str, str] = {
    child.strip().lower(): parent
    for parent, children in COMPONENT_CATEGORY_MAP.items()
    for child in children
}


# ==========================================
# 2. CORE NORMALIZATION FUNCTIONS
# ==========================================
def clean_and_normalize_area(text: str) -> str:
    """Strips capacities, line numbers, parenthetical notes, and plurals."""
    if not text:
        return ""

    cleaned = text.lower().replace("&", " and ")
    cleaned = re.sub(r"\(.*?\)", "", cleaned)
    cleaned = re.sub(r"\bline[- ]?\d+\b", "", cleaned)
    cleaned = re.sub(r"\bb\d+\b", "", cleaned)
    cleaned = re.sub(
        r"\b[\d/]+\s*(kva|mva|kv|v|a|amp|ampere|mtr|hp|mmbtu|w|kg|lt|m)\b",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\d+", "", cleaned)
    cleaned = re.sub(r"[^a-z\s]", " ", cleaned)
    words = [LINGUISTIC_FIXES.get(w, w) for w in cleaned.split()]
    return " ".join(words)


def route_macro_zone(cleaned_area_text: str) -> str:
    """Routes a normalized area name into one of 5 strict Macro-Zones."""
    for zone, keywords in ZONE_PRIORITY_RULES:
        if any(keyword in cleaned_area_text for keyword in keywords):
            return zone
    return "Others"


def cluster_micro_area(raw_area_text: str) -> str:
    """Semantically clusters site-specific room titles into standardized UI buckets."""
    if not raw_area_text:
        return "General Area"

    text = clean_and_normalize_area(raw_area_text)
    padded = f" {text} "

    if "compressor" in text:
        return "Compressor Room"
    if " dg " in padded or "diesel generator" in text:
        return "DG Room"
    if "pump" in text and "fire" in text:
        return "Fire Water Pump Room"
    if "pump" in text:
        return "General Pump Room"
    if "mcc" in text or "panel" in text:
        return "Electrical Panel / MCC Room"
    if "substation" in text or "switchyard" in text:
        return "Electrical Substation"
    if "transformer" in text or "trafo" in text:
        return "Transformer Yard"
    if "battery" in text or "ups" in text:
        return "Battery / UPS Room"
    if "warehouse" in text or "store" in text or "godown" in text:
        return "Warehouse & Storage"
    if "boiler" in text:
        return "Boiler House"
    if "cable" in text and any(tok in text for tok in ("gallery", "cellar", "trench")):
        return "Cable Gallery / Cellar"
    if "canteen" in text or "kitchen" in text:
        return "Canteen / Kitchen"
    if "laboratory" in text or " lab " in padded:
        return "Laboratory"
    if "office" in text or "admin" in text:
        return "Admin / Office Building"
    if "control" in text and "room" in text:
        return "Control Room"

    return text.title() if text else "General Area"


def route_component_category(raw_component_text: str) -> str:
    """Maps a raw component string into one of 15 Master Categories."""
    if not raw_component_text:
        return "General Layout & Housekeeping"
    lookup_key = raw_component_text.strip().lower()
    return RAW_TO_PARENT_COMP_MAP.get(lookup_key, "General Layout & Housekeeping")


def normalize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Applies Macro-Zone routing, UI micro-area clustering, category mapping, and doc IDs."""
    normalized: list[dict[str, Any]] = []
    for idx, rec in enumerate(records, start=1):
        item = rec.copy()
        raw_area = item.get("micro_area", "")
        cleaned_area = clean_and_normalize_area(raw_area)

        item["macro_zone"] = route_macro_zone(cleaned_area)
        item["clean_micro_area"] = cluster_micro_area(raw_area)
        item["component_category"] = route_component_category(item.get("component", ""))
        item["doc_id"] = item.get("doc_id") or f"OBS_{idx:04d}"
        normalized.append(item)

    return normalized


# ==========================================
# 3. CLI ENTRYPOINT
# ==========================================
def run_alias_pipeline(input_path: Path, output_path: Path) -> list[dict[str, Any]]:
    """Loads raw JSON extract, runs full normalization, and writes routed JSON."""
    raw_data = json.loads(input_path.read_text(encoding="utf-8"))
    routed_data = normalize_records(raw_data)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(routed_data, indent=4, ensure_ascii=False), encoding="utf-8"
    )

    zone_counts: dict[str, int] = {}
    for row in routed_data:
        z = row["macro_zone"]
        zone_counts[z] = zone_counts.get(z, 0) + 1

    print("=" * 50)
    print("PHASE 2 ALIAS ENGINE COMPLETE")
    print("=" * 50)
    print(f"Total Observations Processed : {len(routed_data)}")
    print(f"Macro-Zone Distribution      : {zone_counts}")
    print(f"Output Saved To              : {output_path}")
    print("=" * 50)
    return routed_data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize raw FSA JSON extracts via the deterministic Alias Engine."
    )
    parser.add_argument("--input", type=Path, default=Path("data/sample_routed_extract.json"))
    parser.add_argument("--output", type=Path, default=Path("data/routed_master_extract.json"))
    args = parser.parse_args()
    run_alias_pipeline(args.input, args.output)


if __name__ == "__main__":
    main()
