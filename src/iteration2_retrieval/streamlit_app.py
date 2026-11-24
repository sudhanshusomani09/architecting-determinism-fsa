"""Iteration 2 Live Prototype: Dual-Mode Hybrid Retrieval, Delta-Edit HITL & Word Export.

Run locally with:
    streamlit run src/iteration2_retrieval/streamlit_app.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.iteration2_retrieval.docxtpl_exporter import (
    DEFAULT_TEMPLATE_PATH,
    compile_audit_report,
    process_image,
)
from src.iteration2_retrieval.hybrid_rrf_engine import TwoStageHybridSearchEngine

DEFAULT_DB_PATH = REPO_ROOT / "data" / "sample_routed_extract.json"
HITL_LOG_PATH = REPO_ROOT / "data" / "hitl_training_logs.json"


# ==========================================
# 1. PAGE CONFIG & SESSION STATE
# ==========================================
st.set_page_config(page_title="FSA Automation | Two-Stage Retrieval", layout="wide")
st.title("Fire Safety Audit Automation — Two-Stage Retrieval Engine")
st.caption(
    "Iteration 2 Prototype: Metadata-Fenced Hybrid RRF (60% Vector / 40% BM25) "
    "+ Cross-Encoder Reranking + HITL Delta-Edit Logger + DocxTpl Export"
)

st.session_state.setdefault("report_queue", [])
st.session_state.setdefault("search_results", None)
st.session_state.setdefault("last_query", "")
st.session_state.setdefault("editing_item", None)


# ==========================================
# 2. CACHED ENGINE & HITL LOGGER
# ==========================================
@st.cache_resource(
    show_spinner="Loading Two-Stage Retrieval Models (Bi-Encoder + Cross-Encoder)..."
)
def load_engine(db_path_str: str) -> TwoStageHybridSearchEngine:
    return TwoStageHybridSearchEngine.from_json(db_path_str, load_cross_encoder=True)


def log_hitl_validation(
    raw_query: str,
    original_item: dict[str, Any],
    edited_item: dict[str, Any],
) -> None:
    """Silently records engineer-approved delta edits to crowd-source clean training pairs."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "raw_query": raw_query,
        "source_doc_id": original_item.get("doc_id"),
        "macro_zone": edited_item.get("macro_zone"),
        "clean_micro_area": edited_item.get("clean_micro_area"),
        "component": edited_item.get("component"),
        "compliance_status": edited_item.get("compliance_status"),
        "risk_category": edited_item.get("risk_category"),
        "final_observation": edited_item.get("observation"),
        "final_recommendation": edited_item.get("recommendation"),
        "standard_reference": edited_item.get("standard_reference"),
        "reviewer_remarks": edited_item.get("remarks", ""),
    }
    logs: list[dict[str, Any]] = []
    if HITL_LOG_PATH.exists():
        try:
            logs = json.loads(HITL_LOG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logs = []
    logs.append(entry)
    HITL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    HITL_LOG_PATH.write_text(json.dumps(logs, indent=4, ensure_ascii=False), encoding="utf-8")


db_path = DEFAULT_DB_PATH
if not db_path.exists():
    st.error(f"Database file not found at {db_path}. Please verify your data/ directory.")
    st.stop()

engine = load_engine(str(db_path))
all_zones = sorted({e.get("macro_zone", "Others") for e in engine.database})


# ==========================================
# 3. DUAL-MODE SEARCH INTERFACE
# ==========================================
tab_deep, tab_guided = st.tabs(
    ["Deep Auditor Search (Two-Stage)", "Metadata-Fenced Guided Audit"]
)

with tab_deep:
    c1, c2 = st.columns([4, 1])
    with c1:
        deep_query = st.text_input(
            "Enter field shorthand query (e.g., 'missing foam pfe dg room' or 'butterfly valve suction')",
            key="deep_search_bar",
        )
    with c2:
        st.write("")
        st.write("")
        run_deep = st.button(
            "Search", key="btn_deep_search", use_container_width=True, type="primary"
        )

    if run_deep and deep_query.strip():
        with st.spinner("Executing Hybrid RRF + Cross-Encoder Reranking..."):
            st.session_state.search_results = engine.search(
                query=deep_query,
                top_n=5,
                use_cross_encoder=True,
                exclude_complied=True,
            )
            st.session_state.last_query = deep_query
            st.session_state.editing_item = None

with tab_guided:
    g1, g2, g3 = st.columns(3)
    with g1:
        sel_zone = st.selectbox("1. Macro-Zone", all_zones)
    zone_areas = sorted(
        {
            e.get("clean_micro_area", "General Area")
            for e in engine.database
            if e.get("macro_zone") == sel_zone
        }
    )
    with g2:
        sel_area = st.selectbox("2. Standardized Area", ["All Areas"] + zone_areas)
    area_cats = sorted(
        {
            e.get("component_category", "General Layout & Housekeeping")
            for e in engine.database
            if e.get("macro_zone") == sel_zone
            and (sel_area == "All Areas" or e.get("clean_micro_area") == sel_area)
        }
    )
    with g3:
        sel_cat = st.selectbox("3. Component Category", ["All Categories"] + area_cats)

    guided_query = st.text_input(
        "Optional defect note within selected fence (leave blank to browse all):",
        key="guided_query_bar",
    )
    if st.button("Retrieve Fenced Matches", key="btn_guided_search", type="primary"):
        with st.spinner("Filtering fenced metadata bucket..."):
            st.session_state.search_results = engine.search(
                query=guided_query,
                top_n=5,
                use_cross_encoder=bool(guided_query.strip()),
                exclude_complied=True,
                macro_zone=sel_zone,
                clean_micro_area=None if sel_area == "All Areas" else sel_area,
                component_category=None if sel_cat == "All Categories" else sel_cat,
            )
            st.session_state.last_query = f"[{sel_zone} > {sel_area} > {sel_cat}] {guided_query}"
            st.session_state.editing_item = None

st.markdown("---")


# ==========================================
# 4. RANKED RESULTS & DELTA-EDIT MODAL
# ==========================================
main_col, edit_col = st.columns([3, 2])

with main_col:
    if st.session_state.search_results is not None:
        if not st.session_state.search_results:
            st.warning("No unique non-compliant matches found for this query/filter.")
        else:
            st.success(
                f"Top {len(st.session_state.search_results)} deduplicated matches compiled:"
            )
            for i, res in enumerate(st.session_state.search_results):
                header = (
                    f"Rank #{i + 1}: {res.get('component', 'General')} "
                    f"({res.get('macro_zone', 'Facility')})"
                )
                with st.expander(header, expanded=(i == 0)):
                    m1, m2 = st.columns(2)
                    with m1:
                        st.markdown(
                            f"**Location:** {res.get('macro_zone', 'N/A')} > "
                            f"{res.get('clean_micro_area', res.get('micro_area', 'N/A'))}"
                        )
                        st.markdown(f"**Risk Level:** `{res.get('risk_category', 'N/A')}`")
                    with m2:
                        st.markdown(f"**Standard:** `{res.get('standard_reference', 'N/A')}`")
                        if "cross_encoder_score" in res:
                            st.markdown(
                                f"**Rerank Score:** `{res['cross_encoder_score']}` "
                                f"(RRF: `{res.get('rrf_score', 'N/A')}`)"
                            )

                    st.markdown(f"**Observation:** {res.get('observation', 'N/A')}")
                    st.markdown(f"**Recommendation:** {res.get('recommendation', 'N/A')}")

                    if res.get("system_efficacy_context"):
                        st.info(f"**Efficacy Context:** {res['system_efficacy_context']}")

                    if st.button("Customize & Add to Queue", key=f"edit_btn_{i}"):
                        st.session_state.editing_item = res
                        st.rerun()

with edit_col:
    if st.session_state.editing_item:
        item = st.session_state.editing_item
        with st.container(border=True):
            st.markdown(f"#### Delta-Edit: {item.get('component', 'Item')}")
            st.caption(f"Standard Reference: {item.get('standard_reference', 'N/A')}")

            with st.form(key="delta_edit_form"):
                edited_area = st.text_input(
                    "Audit Area Heading",
                    value=item.get("clean_micro_area") or item.get("micro_area") or "GENERAL AREA",
                )
                edited_obs = st.text_area(
                    "Observation", value=item.get("observation", ""), height=120
                )
                edited_rec = st.text_area(
                    "Recommendation", value=item.get("recommendation", ""), height=120
                )

                c_stat, c_risk, c_sub = st.columns(3)
                status_opts = ["Non-Complied", "Partially Complied", "Complied"]
                with c_stat:
                    edited_status = st.selectbox("Compliance Status", status_opts, index=0)
                with c_risk:
                    risk_opts = ["HIGH", "MEDIUM", "LOW"]
                    raw_r = str(item.get("risk_category", "MEDIUM")).upper()
                    r_idx = next((idx for idx, r in enumerate(risk_opts) if raw_r.startswith(r)), 1)
                    edited_risk = st.selectbox("Risk Tier", risk_opts, index=r_idx)
                with c_sub:
                    edited_sub = st.selectbox("Nature Tag", ["H", "B", "S", "N/A"], index=0)

                edited_remarks = st.text_input(
                    "Senior Review Remarks (Optional)",
                    placeholder="Log site-specific doubts or client notes...",
                )
                uploaded_photos = st.file_uploader(
                    "Attach Site Photos (Auto-cropped to 512x500)",
                    type=["png", "jpg", "jpeg"],
                    accept_multiple_files=True,
                )

                submitted = st.form_submit_button(
                    "Save to Queue & Log HITL", use_container_width=True
                )

            if submitted:
                processed_imgs = [process_image(p) for p in (uploaded_photos or [])]
                final_item = item.copy()
                final_item.update(
                    {
                        "area_name": edited_area.upper(),
                        "system_name": item.get("component", "General System"),
                        "observation": edited_obs,
                        "recommendation": edited_rec,
                        "compliance_status": edited_status,
                        "risk_raw": edited_risk,
                        "sub_tag_raw": edited_sub,
                        "risk_category": (
                            f"{edited_risk} ({edited_sub})" if edited_sub != "N/A" else edited_risk
                        ),
                        "remarks": edited_remarks,
                        "raw_images": processed_imgs,
                    }
                )
                log_hitl_validation(st.session_state.last_query, item, final_item)
                st.session_state.report_queue.append(final_item)
                st.session_state.editing_item = None
                st.rerun()

        if st.button("Cancel Editing", use_container_width=True):
            st.session_state.editing_item = None
            st.rerun()


# ==========================================
# 5. SIDEBAR: ACTIVE QUEUE & DOCXTPL EXPORT
# ==========================================
with st.sidebar:
    st.header(f"Active Report Queue ({len(st.session_state.report_queue)})")

    if not st.session_state.report_queue:
        st.info("Queue is empty. Search and customize findings to build an audit report.")
    else:
        for idx, q_item in enumerate(st.session_state.report_queue, start=1):
            with st.expander(f"{idx}. {q_item.get('area_name')} — {q_item.get('system_name')}"):
                st.write(f"**Risk:** {q_item.get('risk_category')}")
                st.write(f"**Photos:** {len(q_item.get('raw_images', []))}")
                st.write(f"**Obs:** {q_item.get('observation', '')[:80]}...")

        st.markdown("---")
        template_file = REPO_ROOT / DEFAULT_TEMPLATE_PATH
        if template_file.exists():
            try:
                docx_stream = compile_audit_report(st.session_state.report_queue, template_file)
                st.download_button(
                    label="Export Word Audit Matrix (.docx)",
                    data=docx_stream.getvalue(),
                    file_name=f"FSA_Audit_Report_{len(st.session_state.report_queue)}_Observations.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    type="primary",
                )
            except Exception as exc:
                st.error(f"Export error: {exc}")
        else:
            st.warning(
                "Blank template missing. Run `python scripts/build_blank_template.py` to enable .docx export."
            )

        if st.button("Clear Queue", use_container_width=True):
            st.session_state.report_queue = []
            st.rerun()
