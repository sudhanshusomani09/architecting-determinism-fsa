# Level 3 Reference: Deterministic Fire Engineering Thresholds

Loaded on demand by the Fire Engineering Agent and QA Auditor Agent to prevent token bloat in the base system prompt. *(Summary engineering triggers only; verbatim legal clauses must be queried from locally licensed JSON codebooks.)*

| Domain Parameter | Threshold Condition | Deterministic Trigger | Governing Reference |
| :--- | :--- | :--- | :--- |
| **Building Height (`H_max`)** | `> 15.0 m` | High-rise egress, riser, and static water rules apply | NBC 2016 Part 4 Table 7 |
| **Ceiling Height (Detection)** | `> 10.0 m` | Point smoke detectors disqualified; mandate beam or aspirating detection | IS 2189 Cl. 6.3.3(a) |
| **Ceiling Beam Obstructions** | `> 10%` of ceiling height | Treat each structural beam bay as an isolated detection enclosure | IS 2189 Cl. 6.3.2(f) |
| **False Ceiling Void Depth** | `> 800 mm` | Concealed smoke detectors + external response indicators mandatory | IS 2189 Cl. 6.3.2(t) |
| **Storage Rack Height** | `> 3.7 m` | Evaluate high-piled in-rack automatic sprinkler density | IS 15105 / NFPA 13 |
| **Electrical Zone Suppression** | `MV (1–33 kV)` or `HV (>33 kV)` | Water sprinklers prohibited (`[FATAL ERROR]`); use clean-agent / in-panel suppression | NBC 2016 Part 4 Cl. 5.1.3(m) |
| **Pump Suction Isolation** | Fire pump suction header | Butterfly valves prohibited; listed OS&Y gate valves mandatory | NFPA 20 Cl. 4.16.5.1 / IS 15301 |
| **Hydrocarbon Containment** | Fuel / diesel day tanks | Impervious secondary dyke capacity `>= 110%` of tank volume | NBC 2016 Part 4 Cl. 3.4.6.4 |
| **Transformer Protection** | Oil `> 2,000 L` & Rating `>= 10 MVA` | Mandate HVWS or Nitrogen Injection Fire Protection System (NIFPS) | NBC 2016 / IS 15325 |
| **Gas Leak Detector Mounting** | PNG / Hydrogen vs. LPG | Ceiling-mounted for PNG/H2 (lighter than air); floor-level for LPG (heavier than air) | NFPA 715 / NFPA 2 |
| **Hazen-Williams Physics COU** | Temp `4–14 °C`, Velocity `<= 7.6 m/s` | Outside range or water mist -> `[CONTEXTUAL FAILURE]`; mandate Darcy-Weisbach | ASME V&V 20 / NFPA 750 |
