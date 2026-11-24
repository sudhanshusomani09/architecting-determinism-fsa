"""Deterministic Word (.docx) Audit Matrix Compiler & Site Photo Processor.

Implements the Delivery Generator pipeline:
  - Auto-orients (EXIF) and crops site photos to uniform 512x500 JPEGs via Pillow.
  - Sanitizes markdown/control artifacts from JSON payloads before Jinja2 injection.
  - Groups queued audit findings alphabetically by facility Area (A., B., C., ...).
  - Applies RichText compliance status colors and Risk Category hex cell shading.
  - Compiles an editable Section 6 Word table into an in-memory BytesIO stream.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage, RichText
from PIL import Image, ImageOps

DEFAULT_TEMPLATE_PATH = Path("templates/consultancy_master_template.docx")

STATUS_COLORS: dict[str, str] = {
    "complied": "00B050",
    "partially complied": "FFC000",
    "non-complied": "FF0000",
    "non-conclusive": "7F7F7F",
}

RISK_BG_COLORS: dict[str, str] = {
    "HIGH": "FF0000",
    "MEDIUM": "ED7D31",
    "LOW": "FFC000",
}


def sanitize_text(value: Any) -> str:
    """Strips markdown artifacts and XML-unsafe control characters prior to rendering."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"null", "none", "n/a", "--"}:
        return ""
    text = re.sub(r"[*_`#]+", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.strip()


def process_image(uploaded_file: Any, target_size: tuple[int, int] = (512, 500)) -> io.BytesIO:
    """EXIF-transposes and crops an uploaded photo to uniform report dimensions."""
    img = Image.open(uploaded_file)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img = ImageOps.fit(img, target_size, Image.Resampling.LANCZOS)
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="JPEG", quality=85)
    img_byte_arr.seek(0)
    return img_byte_arr


def _parse_risk(
    raw_risk: str, comp_status: str, explicit_sub_tag: str = "N/A"
) -> tuple[str, str, str]:
    """Normalizes risk labels like 'HIGH (H)' or 'Medium (M)' into (level, sub_tag, hex_bg)."""
    if comp_status.strip().lower() == "complied" or "COMPLIED" in raw_risk.upper():
        return "--", "", "FFFFFF"

    upper = raw_risk.strip().upper()
    level = "--"
    for candidate in ("HIGH", "MEDIUM", "LOW"):
        if upper.startswith(candidate):
            level = candidate
            break

    bg_hex = RISK_BG_COLORS.get(level, "FFFFFF")

    match = re.search(r"\(([A-Z,\s]+)\)", upper)
    if explicit_sub_tag and explicit_sub_tag.upper() != "N/A":
        sub_tag = f"({explicit_sub_tag.strip().upper()})"
    elif match:
        sub_tag = f"({match.group(1).strip()})"
    else:
        sub_tag = ""

    return level, sub_tag, bg_hex


def _format_recommendation(raw_rec: str) -> str:
    """Prepends formal recommendation phrasing only if not already present."""
    clean = sanitize_text(raw_rec)
    if not clean:
        return ""
    lower = clean.lower()
    if lower.startswith(
        ("it is recommended", "it is advisable", "provide ", "install ", "ensure ", "replace ")
    ):
        return clean
    return f"It is recommended that {clean[0].lower()}{clean[1:]}" if len(clean) > 1 else clean


def compile_audit_report(
    observations: list[dict[str, Any]],
    template_path: Path | str = DEFAULT_TEMPLATE_PATH,
) -> io.BytesIO:
    """Compiles a list of queued observations into a formatted Word (.docx) BytesIO stream."""
    tpl_path = Path(template_path)
    if not tpl_path.exists():
        raise FileNotFoundError(
            f"Master Word template not found at '{tpl_path}'. "
            "Run 'python scripts/build_blank_template.py' to generate an anonymized template."
        )

    doc = DocxTemplate(str(tpl_path))
    grouped_data: dict[str, list[dict[str, Any]]] = {}

    for idx, obs in enumerate(observations, start=1):
        area_key = sanitize_text(
            obs.get("area_name")
            or obs.get("clean_micro_area")
            or obs.get("micro_area")
            or "GENERAL AREA"
        ).upper()
        grouped_data.setdefault(area_key, [])

        comp_status = sanitize_text(
            obs.get("comp_status_raw") or obs.get("compliance_status") or "Non-Complied"
        )
        rt_comp = RichText()
        status_hex = STATUS_COLORS.get(comp_status.lower(), "FF0000")
        rt_comp.add(comp_status, color=status_hex, bold=True)

        risk_level, risk_sub, bg_hex = _parse_risk(
            raw_risk=str(obs.get("risk_raw") or obs.get("risk_category") or "MEDIUM"),
            comp_status=comp_status,
            explicit_sub_tag=str(obs.get("sub_tag_raw", "N/A")),
        )

        inline_imgs: list[InlineImage] = []
        for img_stream in obs.get("raw_images", []):
            img_stream.seek(0)
            inline_imgs.append(InlineImage(doc, img_stream, width=Mm(25.6), height=Mm(25.0)))

        grouped_data[area_key].append(
            {
                "s_no": obs.get("s_no") or f"{idx}.",
                "system_name": sanitize_text(
                    obs.get("system_name") or obs.get("component") or "General System"
                ),
                "compliance_status": rt_comp,
                "observation_text": sanitize_text(
                    obs.get("observation_text") or obs.get("observation")
                ),
                "recommendation_text": _format_recommendation(
                    obs.get("rec_text_raw") or obs.get("recommendation") or ""
                ),
                "standard_quote_text": sanitize_text(
                    obs.get("standard_quote_text") or obs.get("standard_quote") or ""
                ),
                "reference_standard": sanitize_text(
                    obs.get("reference_standard")
                    or obs.get("standard_reference")
                    or "Good Engineering Practice"
                ),
                "risk_level": risk_level,
                "risk_sub_tag": risk_sub,
                "risk_bg_color": bg_hex,
                "remarks": sanitize_text(obs.get("remarks") or ""),
                "inline_images": inline_imgs,
            }
        )

    final_areas = [
        {
            "area_letter": f"{chr(65 + i)}.",
            "area_name": area_name,
            "observations": obs_list,
        }
        for i, (area_name, obs_list) in enumerate(grouped_data.items())
    ]

    doc.render({"grouped_areas": final_areas})

    output_stream = io.BytesIO()
    doc.save(output_stream)
    output_stream.seek(0)
    return output_stream
