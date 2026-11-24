"""Iteration 1 — Stage 1: Dynamic Word (.docx) Audit Matrix & Nested Table Parser.

Parses historical Fire Safety Audit Word reports into a flat staging CSV for
LLM entity extraction. Features:
  - Dynamic Header Hunting: Scans the top 5 rows of every table to bypass merged
    section banners and locate standard column indices.
  - Nested Table Flattening: Extracts embedded sub-tables (e.g., pump capacities,
    pressure setpoints) while removing ghost duplicates from merged cells.
  - Italic-Run Separation: Separates auditor recommendations from italicized
    verbatim statutory quotes inside the Analysis column.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd
from docx import Document


def extract_nested_tables(cell: Any) -> str:
    """Extracts and flattens tables nested inside a Word table cell."""
    nested_text: list[str] = []
    for table in cell.tables:
        for row in table.rows:
            row_data: list[str] = []
            for c in row.cells:
                text = c.text.strip().replace("\n", " ")
                # Prevent ghost duplicates caused by horizontally merged cells
                if text and (not row_data or row_data[-1] != text):
                    row_data.append(text)
            if row_data:
                nested_text.append(" | ".join(row_data))
    return "\n".join(nested_text)


def _find_header_index(header_cells: list[str], candidates: tuple[str, ...]) -> int | None:
    """Finds the first matching column index across spelling/apostrophe variants."""
    normalized = [h.replace("\u2019", "'").strip().upper() for h in header_cells]
    for cand in candidates:
        if cand in normalized:
            return normalized.index(cand)
    return None


def extract_advanced_fsa_tables(directory_path: Path) -> pd.DataFrame:
    """Scans a directory of .docx audit reports and extracts compliance matrices."""
    master_data: list[dict[str, str]] = []
    target_headers = ("DESCRIPTION OF SYSTEM", "RISK CATEGORY")

    if not directory_path.exists():
        raise FileNotFoundError(f"Input directory not found: {directory_path}")

    for filepath in sorted(directory_path.iterdir()):
        if filepath.suffix.lower() != ".docx" or filepath.name.startswith("~"):
            continue

        try:
            doc = Document(str(filepath))
        except Exception as exc:
            print(f"[WARN] Bypassing {filepath.name}. Error: {exc}")
            continue

        for table in doc.tables:
            if not table.rows:
                continue

            # --- DYNAMIC HEADER HUNTING ---
            header_row_idx = -1
            header_cells: list[str] = []
            for idx, row in enumerate(table.rows[:5]):
                cells_text = [
                    cell.text.replace("\u2019", "'").strip().upper()
                    for cell in row.cells
                ]
                if all(h in cells_text for h in target_headers):
                    header_row_idx = idx
                    header_cells = cells_text
                    break

            if header_row_idx == -1:
                continue

            desc_idx = _find_header_index(header_cells, ("DESCRIPTION OF SYSTEM", "DESCRIPTION OF THE SYSTEM"))
            analysis_idx = _find_header_index(header_cells, ("ANALYSIS AND RECOMMENDATION",))
            std_idx = _find_header_index(header_cells, ("STANDARD'S REFERENCE", "STANDARDS REFERENCE", "STANDARD REFERENCE"))
            risk_idx = _find_header_index(header_cells, ("RISK CATEGORY",))

            if None in (desc_idx, analysis_idx, std_idx, risk_idx):
                continue

            col_map = {
                "desc_idx": desc_idx,
                "analysis_idx": analysis_idx,
                "standards_idx": std_idx,
                "risk_idx": risk_idx,
            }

            current_area = "GENERAL / UNCLASSIFIED"

            for row in table.rows[header_row_idx + 1 :]:
                cells = row.cells
                if len(cells) <= max(col_map.values()):
                    continue

                # Merged full-width rows represent Area headers
                row_texts = {c.text.strip() for c in cells if c.text.strip()}
                if len(row_texts) == 1:
                    current_area = next(iter(row_texts))
                    continue

                desc_cell = cells[col_map["desc_idx"]]
                analysis_cell = cells[col_map["analysis_idx"]]
                std_cell = cells[col_map["standards_idx"]]
                risk_cell = cells[col_map["risk_idx"]]

                if not desc_cell.text.strip() or not analysis_cell.text.strip():
                    continue

                # Parse Component vs Observation
                desc_paragraphs = [p for p in desc_cell.paragraphs if p.text.strip()]
                component_text = ""
                observation_text = ""

                if desc_paragraphs:
                    component_text = desc_paragraphs[0].text.strip()
                    observation_text = "\n".join(
                        p.text.strip() for p in desc_paragraphs[1:]
                    )

                if not observation_text and ":" in component_text:
                    left, right = component_text.split(":", 1)
                    component_text = left.strip() + ":"
                    observation_text = right.strip()

                nested_desc = extract_nested_tables(desc_cell)
                if nested_desc:
                    observation_text += "\n[Extracted Table Data]:\n" + nested_desc

                # Parse Compliance Status, Recommendation, and Italicized Standard Quote
                analysis_paragraphs = [
                    p for p in analysis_cell.paragraphs if p.text.strip()
                ]
                compliance_status = ""
                recommendation_lines: list[str] = []
                quote_lines: list[str] = []

                if analysis_paragraphs:
                    compliance_status = analysis_paragraphs[0].text.strip()
                    for p in analysis_paragraphs[1:]:
                        is_italic = any(run.italic for run in p.runs if run.text.strip())
                        if is_italic or quote_lines:
                            quote_lines.append(p.text.strip())
                        else:
                            recommendation_lines.append(p.text.strip())

                recommendation_text = "\n".join(recommendation_lines)
                standard_quote = "\n".join(quote_lines)

                nested_analysis = extract_nested_tables(analysis_cell)
                if nested_analysis:
                    recommendation_text += "\n[Extracted Table Data]:\n" + nested_analysis

                row_dict = {
                    "Source_File": filepath.name,
                    "Area": current_area,
                    "Component": component_text,
                    "Observation": observation_text,
                    "Compliance_Status": compliance_status,
                    "Recommendation": recommendation_text,
                    "Standard_Reference": std_cell.text.strip(),
                    "Standard_Quote": standard_quote,
                    "Risk_Category": risk_cell.text.strip(),
                }

                if not master_data or master_data[-1] != row_dict:
                    master_data.append(row_dict)

    return pd.DataFrame(master_data)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Iteration 1 Step 1: Parse .docx FSA compliance matrices into CSV."
    )
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw_docx"))
    parser.add_argument("--output", type=Path, default=Path("data/iteration1/neo4j_ready_mvp_data.csv"))
    args = parser.parse_args()

    print("[*] Initializing Iteration 1 Ingestion Engine...")
    df_compliance = extract_advanced_fsa_tables(args.input_dir)

    if not df_compliance.empty:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        df_compliance.to_csv(args.output, index=False, encoding="utf-8")
        print(f"[DONE] Extracted {len(df_compliance)} rows -> {args.output}")
    else:
        print("[!] No compliance tables extracted.")


if __name__ == "__main__":
    main()
