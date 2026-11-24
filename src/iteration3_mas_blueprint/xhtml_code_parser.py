"""Deterministic XHTML-to-JSON Statutory Standard Parser & 5-Test QA Audit Suite.

Built to replace fragile PDF Regex parsing (which corrupted multi-column tables and
Annexures during Iteration 2). Empirically validated on Indian Standard IS 2190:2010.

Features:
  - HTML Table Unfolding: Resolves `rowspan` and `colspan` merges into flat relational grids.
  - Footnote Extraction: Isolates `NOTE`/`NOTES` rows into dedicated `table_notes` arrays.
  - Unique Header Disambiguation: Prevents Python dict key overwrites on repeated headers.
  - Relational Linking: Replaces tables in-place with `[[TBL_REF::<id>]]` markers so parent
    clauses preserve exact foreign-key pointers without losing surrounding captions.
  - 5-Test Deterministic Audit Suite: Audits word recovery, clause continuity, table parity,
    hierarchy ancestry, and foreign-key integrity.
"""

from __future__ import annotations

import argparse
import json
import re
import warnings
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

CLAUSE_ID_REGEX = re.compile(r"^([A-Z]-)?\d+(\.\d+)*$")


def normalize_html_table_master(table_tag: Any) -> tuple[list[str], list[dict[str, str]], list[str]]:
    """Unfolds rowspan/colspan HTML tables into normalized relational dictionaries."""
    rows = table_tag.find_all("tr")
    if not rows:
        return [], [], []

    data_rows = []
    table_notes: list[str] = []
    is_note_section = False

    for row in rows:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        first_cell_text = cells[0].get_text(strip=True).upper()
        if first_cell_text.startswith("NOTE"):
            is_note_section = True

        if is_note_section:
            note_text = row.get_text(separator=" ", strip=True)
            if note_text.upper() != "NOTES":
                table_notes.append(note_text)
        else:
            data_rows.append(row)

    max_cols = 0
    for row in data_rows:
        cols = sum(int(cell.get("colspan", 1)) for cell in row.find_all(["td", "th"]))
        max_cols = max(max_cols, cols)

    if not data_rows or max_cols == 0:
        return [], [], table_notes

    grid = [["" for _ in range(max_cols)] for _ in range(len(data_rows))]

    for r_idx, row in enumerate(data_rows):
        c_idx = 0
        for cell in row.find_all(["td", "th"]):
            while c_idx < max_cols and grid[r_idx][c_idx] != "":
                c_idx += 1
            if c_idx >= max_cols:
                break

            rowspan = int(cell.get("rowspan", 1))
            colspan = int(cell.get("colspan", 1))
            text = cell.get_text(separator=" ", strip=True)

            for i in range(r_idx, min(r_idx + rowspan, len(data_rows))):
                for j in range(c_idx, min(c_idx + colspan, max_cols)):
                    grid[i][j] = text
            c_idx += colspan

    # Deduplicate header names to prevent dictionary key collisions
    unique_headers: list[str] = []
    for raw_h in grid[0]:
        base_h = raw_h.strip() if raw_h.strip() else "Blank"
        candidate = base_h
        count = 1
        while candidate in unique_headers:
            candidate = f"{base_h}_{count}"
            count += 1
        unique_headers.append(candidate)

    structured_data = [dict(zip(unique_headers, r)) for r in grid[1:]]
    return unique_headers, structured_data, table_notes


def parse_is_standard_v4(file_path: Path, standard_code: str) -> dict[str, Any]:
    """Parses a structured XHTML statutory standard into a relational JSON schema."""
    raw_xhtml = file_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(raw_xhtml, "lxml")

    database: dict[str, Any] = {
        "document_meta": {"standard_code": standard_code},
        "tables": [],
        "clauses": [],
    }
    node_registry: dict[str, dict[str, Any]] = {}

    # 1. Extract tables and inject inline foreign-key markers
    for idx, table_tag in enumerate(soup.find_all("table")):
        parent_div = table_tag.find_parent("div")
        table_id = (
            parent_div.get("id")
            if parent_div and parent_div.get("id")
            else f"tbl_{idx + 1:03d}"
        )

        caption = "Untitled Table"
        if parent_div:
            cap_tag = parent_div.find("p", class_="table_label_caption1")
            if cap_tag:
                caption = cap_tag.get_text(separator=" ", strip=True)

        headers, structured_data, table_notes = normalize_html_table_master(table_tag)
        database["tables"].append(
            {
                "table_id": table_id,
                "title": caption,
                "headers": headers,
                "structured_data": structured_data,
                "table_notes": table_notes,
            }
        )

        marker = soup.new_tag("p")
        marker.string = f"[[TBL_REF::{table_id}]]"
        table_tag.replace_with(marker)

    # 2. Initialize Preamble node ("0.0" satisfies deterministic clause regex)
    std_slug = standard_code.replace(" ", "_").replace(":", "_")
    current_hierarchy = ["PREAMBLE"]
    preamble_id = f"{std_slug}_CLAUSE_0_0"
    current_node: dict[str, Any] = {
        "node_id": preamble_id,
        "clause_number": "0.0",
        "hierarchy_path": ["PREAMBLE"],
        "full_text": [],
        "linked_tables": [],
    }
    node_registry[preamble_id] = current_node
    database["clauses"].append(current_node)

    # 3. Traverse body children while preserving all headings, captions, and links
    body = soup.find("body") or soup
    for elem in body.children:
        if not hasattr(elem, "name") or elem.name is None:
            continue

        text = elem.get_text(separator=" ", strip=True)
        if not text:
            continue

        if "[[TBL_REF::" in text:
            for t_id in re.findall(r"\[\[TBL_REF::(.*?)\]\]", text):
                if t_id not in current_node["linked_tables"]:
                    current_node["linked_tables"].append(t_id)
            text = re.sub(r"\[\[TBL_REF::.*?\]\]", "", text).strip()
            if not text:
                continue

        classes = elem.get("class", []) or []
        if "head3" in classes or "head2" in classes:
            if "BUREAU OF INDIAN STANDARDS" in text.upper():
                break
            current_hierarchy = [text]

        bold_tag = elem.find("span", style=re.compile(r"font-weight:\s*bold"))
        if bold_tag:
            bold_text = bold_tag.get_text(strip=True)
            if CLAUSE_ID_REGEX.match(bold_text):
                node_id = f"{std_slug}_CLAUSE_{bold_text.replace('.', '_').replace('-', '_')}"
                if node_id in node_registry:
                    current_node = node_registry[node_id]
                else:
                    depth = len(bold_text.split("."))
                    if depth > len(current_hierarchy):
                        current_hierarchy.append(text)
                    else:
                        current_hierarchy = current_hierarchy[: max(depth - 1, 0)] + [text]

                    current_node = {
                        "node_id": node_id,
                        "clause_number": bold_text,
                        "hierarchy_path": list(current_hierarchy),
                        "full_text": [],
                        "linked_tables": [],
                    }
                    node_registry[node_id] = current_node
                    database["clauses"].append(current_node)

        current_node["full_text"].append(text)

    for clause in database["clauses"]:
        clause["full_text"] = "\n".join(clause["full_text"])

    return database


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\b[a-zA-Z0-9_\-\.]{2,}\b", text.lower()))


def run_deterministic_audit_suite(
    xhtml_path: Path, db: dict[str, Any]
) -> dict[str, Any]:
    """Executes the 5-Test Deterministic Knowledge Base Verification Suite."""
    raw_xhtml = xhtml_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(raw_xhtml, "lxml")

    # TEST 1: Lossless Text Coverage Audit
    xhtml_body = soup.find("body") or soup
    for boiler in xhtml_body.find_all(
        lambda tag: tag.name == "p"
        and "bureau of indian standards" in tag.get_text().lower()
    ):
        boiler.decompose()
    source_tokens = _tokenize(xhtml_body.get_text(separator=" ", strip=True))

    json_blocks: list[str] = [c["full_text"] for c in db["clauses"]]
    for tbl in db["tables"]:
        json_blocks.append(tbl["title"])
        json_blocks.extend(tbl.get("headers", []))
        json_blocks.extend(tbl.get("table_notes", []))
        for row in tbl["structured_data"]:
            json_blocks.extend(str(v) for v in row.values())
    json_tokens = _tokenize(" ".join(json_blocks))

    missing_tokens = source_tokens - json_tokens
    recovery_pct = (
        ((len(source_tokens) - len(missing_tokens)) / len(source_tokens)) * 100.0
        if source_tokens
        else 100.0
    )

    # TEST 2: Clause Numbering & Duplicate Audit
    malformed_clauses: list[str] = []
    duplicate_clauses: list[str] = []
    seen: set[str] = set()
    for c in db["clauses"]:
        c_num = c["clause_number"]
        if not CLAUSE_ID_REGEX.match(c_num):
            malformed_clauses.append(c_num)
        if c_num in seen:
            duplicate_clauses.append(c_num)
        seen.add(c_num)

    # TEST 3: Table Matrix Parity Audit
    raw_soup = BeautifulSoup(raw_xhtml, "lxml")
    html_table_count = len(raw_soup.find_all("table"))
    table_mismatches: list[str] = []
    raw_row_fallbacks = 0
    for tbl in db["tables"]:
        expected_cols = len(tbl["headers"])
        for r_idx, row in enumerate(tbl["structured_data"], start=1):
            if "raw_row" in row:
                raw_row_fallbacks += 1
                table_mismatches.append(f"Table '{tbl['table_id']}' row {r_idx} fallback.")
            elif len(row.keys()) != expected_cols:
                table_mismatches.append(f"Table '{tbl['table_id']}' row {r_idx} column mismatch.")

    # TEST 4: Hierarchy Tree Ancestry Audit
    orphaned_clauses = [
        c["clause_number"]
        for c in db["clauses"]
        if not c.get("hierarchy_path")
        or (len(c["clause_number"].split(".")) > 1 and c["clause_number"] != "0.0" and len(c["hierarchy_path"]) < 2)
    ]

    # TEST 5: Relational Foreign Key Integrity Audit
    registered_table_ids = {t["table_id"] for t in db["tables"]}
    broken_links = [
        (c["clause_number"], t_link)
        for c in db["clauses"]
        for t_link in c.get("linked_tables", [])
        if t_link not in registered_table_ids
    ]

    return {
        "word_recovery_pct": round(recovery_pct, 2),
        "missing_tokens_sample": sorted(missing_tokens)[:15],
        "total_clauses": len(db["clauses"]),
        "malformed_clauses": malformed_clauses,
        "duplicate_clauses": duplicate_clauses,
        "html_table_count": html_table_count,
        "json_table_count": len(db["tables"]),
        "raw_row_fallbacks": raw_row_fallbacks,
        "table_mismatches": table_mismatches,
        "orphaned_clauses": orphaned_clauses,
        "broken_table_links": broken_links,
        "all_structural_tests_passed": (
            not malformed_clauses
            and not duplicate_clauses
            and html_table_count == len(db["tables"])
            and not table_mismatches
            and not orphaned_clauses
            and not broken_links
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic XHTML-to-JSON Statutory Standard Parser & QA Audit Suite."
    )
    parser.add_argument("--input", type=Path, required=True, help="Path to source .xhtml standard file.")
    parser.add_argument("--standard-code", type=str, required=True, help="Standard code (e.g., 'IS 2190:2010').")
    parser.add_argument("--output", type=Path, required=True, help="Output path for structured JSON.")
    parser.add_argument("--run-audit", action="store_true", help="Run the 5-Test QA Audit Suite after parsing.")
    args = parser.parse_args()

    master_db = parse_is_standard_v4(args.input, args.standard_code)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(master_db, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"[DONE] Parsed {len(master_db['clauses'])} clauses & {len(master_db['tables'])} tables -> {args.output}")

    if args.run_audit:
        report = run_deterministic_audit_suite(args.input, master_db)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
