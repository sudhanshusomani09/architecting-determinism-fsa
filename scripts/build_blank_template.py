"""Generates an Anonymized, Logo-Free Master Word (.docx) Template for DocxTpl.

Creates `templates/consultancy_master_template.docx` wired with the exact Jinja2
`grouped_areas` loop tags expected by `src/iteration2_retrieval/docxtpl_exporter.py`.
"""

from __future__ import annotations

from pathlib import Path
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor


def set_cell_shading(cell, fill_hex: str) -> None:
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading)


def build_template(
    output_path: Path = Path("templates/consultancy_master_template.docx"),
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()

    for section in doc.sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)

    title = doc.add_heading("FIRE SAFETY AUDIT REPORT — SECTION 6", level=1)
    title.runs[0].font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)
    subtitle = doc.add_paragraph(
        "AREA-WISE OBSERVATIONS, STATUTORY ANALYSIS, AND RECOMMENDATIONS"
    )
    subtitle.runs[0].bold = True
    subtitle.runs[0].font.size = Pt(10)

    table = doc.add_table(rows=5, cols=6)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"

    col_widths = [Inches(0.5), Inches(2.2), Inches(2.4), Inches(1.1), Inches(0.8), Inches(0.5)]
    headers = [
        "S.No",
        "Description of System & Evidence",
        "Analysis, Recommendation & Standard Quote",
        "Standard Reference",
        "Risk Category",
        "Remarks",
    ]

    # Row 0: Table Header
    hdr_cells = table.rows[0].cells
    for i, text in enumerate(headers):
        hdr_cells[i].width = col_widths[i]
        p = hdr_cells[i].paragraphs[0]
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        set_cell_shading(hdr_cells[i], "1F4E79")

    # Row 1: Outer Jinja2 row loop start
    row1_cells = table.rows[1].cells
    merged_r1 = row1_cells[0].merge(row1_cells[5])
    merged_r1.text = "{%tr for area in grouped_areas %}"

    # Row 2: Area Banner Row
    row2_cells = table.rows[2].cells
    row2_cells[0].text = "{{ area.area_letter }}"
    merged_area = row2_cells[1].merge(row2_cells[5])
    merged_area.text = "{{ area.area_name }}"
    for c in (row2_cells[0], merged_area):
        set_cell_shading(c, "D9E2F3")
        for run in c.paragraphs[0].runs:
            run.bold = True
            run.font.size = Pt(9.5)

    # Row 3: Inner observation loop start
    row3_cells = table.rows[3].cells
    merged_r3 = row3_cells[0].merge(row3_cells[5])
    merged_r3.text = "{%tr for obs in area.observations %}"

    # Row 4: Observation Data Row
    data_cells = table.rows[4].cells
    data_cells[0].text = "{{ obs.s_no }}"
    data_cells[1].text = (
        "{{ obs.system_name }}\n"
        "{{ obs.observation_text }}\n"
        "{% for img in obs.inline_images %}{{ img }} {% endfor %}"
    )
    data_cells[2].text = (
        "{{ obs.compliance_status }}\n"
        "{{ obs.recommendation_text }}\n"
        "{% if obs.standard_quote_text %}Standard Quote: {{ obs.standard_quote_text }}{% endif %}"
    )
    data_cells[3].text = "{{ obs.reference_standard }}"
    data_cells[4].text = "{{ obs.risk_level }}\n{{ obs.risk_sub_tag }}"
    data_cells[5].text = "{{ obs.remarks }}"

    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), "{{ obs.risk_bg_color }}")
    data_cells[4]._tc.get_or_add_tcPr().append(shd)

    for i, cell in enumerate(data_cells):
        cell.width = col_widths[i]
        for p in cell.paragraphs:
            for run in p.runs:
                run.font.size = Pt(8.5)

    # Row 5 & Row 6: Close inner and outer table-row loops
    end_inner = table.add_row().cells
    end_inner[0].merge(end_inner[5]).text = "{%tr endfor %}"

    end_outer = table.add_row().cells
    end_outer[0].merge(end_outer[5]).text = "{%tr endfor %}"

    doc.save(str(output_path))
    print(f"[DONE] Generated anonymized master template at: {output_path}")


if __name__ == "__main__":
    build_template()
