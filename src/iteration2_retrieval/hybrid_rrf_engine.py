"""Two-Stage Metadata-Fenced Hybrid Retrieval Engine (BM25 + Dense Vector + Cross-Encoder).

Implements the benchmarked Iteration 2 search core:
  - Deterministic Pre-Filter 1: 25-acronym Fire Safety Regex Jargon Expander.
  - Deterministic Pre-Filter 2: Optional Metadata Fencing (Macro-Zone / Area / Category)
                                + Non-Compliance Hard Filter (drops 'Complied' records).
  - Stage 1 (The Net):          Parallel Okapi BM25 + all-MiniLM-L6-v2 fused via
                                weighted Reciprocal Rank Fusion (60% Vector / 40% BM25, k=60).
  - Stage 2 (The Scalpel):      Cross-Encoder (ms-marco-MiniLM-L-6-v2) deep reranking
                                over the Top-20 candidates + Deduplication Sieve.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer, util

DEFAULT_BI_ENCODER = "all-MiniLM-L6-v2"
DEFAULT_CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-6-v2"

JARGON_DICTIONARY: dict[str, str] = {
    r"\bdg\b": "DG (Diesel Generator)",
    r"\bpfe\b": "PFE (Portable Fire Extinguisher)",
    r"\bfdas\b": "FDAS (Fire Detection and Alarm System)",
    r"\bmcc\b": "MCC (Motor Control Center Panel)",
    r"\bwtp\b": "WTP (Water Treatment Plant)",
    r"\bcbs\b": "CBS (Coal Blending Silo Shed)",
    r"\besp\b": "ESP (Electrostatic Precipitator)",
    r"\bhvws\b": "HVWS (High Velocity Water Spray)",
    r"\bmvws\b": "MVWS (Medium Velocity Water Spray)",
    r"\bmcp\b": "MCP (Manual Call Point Fire Alarm)",
    r"\bhsd\b": "HSD (High Speed Diesel Fuel)",
    r"\bhfo\b": "HFO (Heavy Fuel Oil)",
    r"\bpng\b": "PNG (Piped Natural Gas)",
    r"\bprv\b": "PRV (Pressure Relief Valve)",
    r"\bos&y\b": "OS&Y (Outside Screw and Yoke Gate Valve)",
    r"\bp&id\b": "P&ID (Piping and Instrumentation Diagram)",
    r"\blhs\b": "LHS (Linear Heat Sensor Detection Cable)",
    r"\bdcp\b": "DCP (Dry Chemical Powder Extinguisher)",
    r"\bco2\b": "CO2 (Carbon Dioxide Extinguisher)",
    r"\babc\b": "ABC (Dry Chemical Extinguisher)",
    r"\bwhr\b": "WHR (Waste Heat Recovery Boiler)",
    r"\bcpp\b": "CPP (Captive Power Plant)",
    r"\bafr\b": "AFR (Alternative Fuel and Raw Materials)",
    r"\bohc\b": "OHC (Occupational Health Centre Medical)",
    r"\btg\b": "TG (Turbine Generator)",
}


def expand_engineering_jargon(query: str) -> str:
    """Expands domain shorthand acronyms prior to lexical and vector encoding."""
    expanded = query.lower()
    for pattern, replacement in JARGON_DICTIONARY.items():
        expanded = re.sub(pattern, replacement, expanded)
    return expanded


def tokenize_for_bm25(text: str) -> list[str]:
    """Normalizes and tokenizes text for Okapi BM25 scoring."""
    clean = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    return clean.split()


def build_search_document(entry: dict[str, Any]) -> str:
    """Stitches spatial, taxonomy, and observation fields into a single search document."""
    return (
        f"{entry.get('macro_zone', '')} "
        f"{entry.get('clean_micro_area', entry.get('micro_area', ''))} "
        f"{entry.get('component_category', '')} "
        f"{entry.get('component', '')} "
        f"{entry.get('observation', '')}"
    ).strip()


def deduplicate_results(
    candidates: list[dict[str, Any]],
    top_n: int = 5,
    exclude_complied: bool = True,
) -> list[dict[str, Any]]:
    """Deduplication Sieve: filters out Complied items and identical Advice+Standard hashes."""
    final_results: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()

    for item in candidates:
        status = str(item.get("compliance_status", "")).strip().lower()
        if exclude_complied and status in {"complied", "complied."}:
            continue

        rec_sig = str(item.get("recommendation", "")).strip().lower()
        std_sig = str(item.get("standard_reference", "")).strip().lower()
        signature = f"{rec_sig}||{std_sig}"

        if signature not in seen_signatures:
            seen_signatures.add(signature)
            final_results.append(item)

        if len(final_results) >= top_n:
            break

    return final_results


class TwoStageHybridSearchEngine:
    """Offline Two-Stage Hybrid Retrieval Engine (BM25 + Dense RRF + Cross-Encoder)."""

    def __init__(
        self,
        database: list[dict[str, Any]],
        bi_encoder_name: str = DEFAULT_BI_ENCODER,
        cross_encoder_name: str = DEFAULT_CROSS_ENCODER,
        load_cross_encoder: bool = True,
    ) -> None:
        self.database = database
        self.bi_encoder = SentenceTransformer(bi_encoder_name)
        self.cross_encoder = (
            CrossEncoder(cross_encoder_name, max_length=512)
            if load_cross_encoder
            else None
        )

        self.vector_corpus: list[str] = [build_search_document(e) for e in self.database]
        self.bm25_corpus: list[list[str]] = [
            tokenize_for_bm25(doc) for doc in self.vector_corpus
        ]
        self.bm25 = BM25Okapi(self.bm25_corpus)
        self.corpus_embeddings = self.bi_encoder.encode(
            self.vector_corpus, convert_to_tensor=True
        )

    @classmethod
    def from_json(
        cls,
        json_path: Path | str,
        bi_encoder_name: str = DEFAULT_BI_ENCODER,
        cross_encoder_name: str = DEFAULT_CROSS_ENCODER,
        load_cross_encoder: bool = True,
    ) -> "TwoStageHybridSearchEngine":
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
        return cls(
            database=data,
            bi_encoder_name=bi_encoder_name,
            cross_encoder_name=cross_encoder_name,
            load_cross_encoder=load_cross_encoder,
        )

    def _filter_indices(
        self,
        macro_zone: str | None = None,
        clean_micro_area: str | None = None,
        component_category: str | None = None,
        component: str | None = None,
    ) -> list[int]:
        """Applies strict Metadata Fencing before retrieval."""
        valid: list[int] = []
        for idx, entry in enumerate(self.database):
            if macro_zone and entry.get("macro_zone") != macro_zone:
                continue
            if clean_micro_area and entry.get("clean_micro_area") != clean_micro_area:
                continue
            if component_category and entry.get("component_category") != component_category:
                continue
            if component and entry.get("component") != component:
                continue
            valid.append(idx)
        return valid

    def rank_stage1_rrf(
        self,
        query: str,
        vector_weight: float = 0.60,
        bm25_weight: float = 0.40,
        rrf_k: int = 60,
        candidate_indices: list[int] | None = None,
    ) -> tuple[list[int], dict[int, float], str]:
        """Stage 1: Executes parallel BM25 and dense cosine similarity fused via RRF."""
        expanded_query = expand_engineering_jargon(query)
        query_tokens = tokenize_for_bm25(expanded_query)

        indices = (
            candidate_indices
            if candidate_indices is not None
            else list(range(len(self.database)))
        )
        if not indices:
            return [], {}, expanded_query

        all_bm25_scores = self.bm25.get_scores(query_tokens)
        subset_bm25 = np.array([all_bm25_scores[i] for i in indices])
        bm25_order = np.argsort(subset_bm25)[::-1]
        bm25_ranks = {indices[pos]: rank + 1 for rank, pos in enumerate(bm25_order)}

        q_emb = self.bi_encoder.encode(expanded_query, convert_to_tensor=True)
        all_vec_scores = util.cos_sim(q_emb, self.corpus_embeddings)[0].cpu().numpy()
        subset_vec = np.array([all_vec_scores[i] for i in indices])
        vec_order = np.argsort(subset_vec)[::-1]
        vec_ranks = {indices[pos]: rank + 1 for rank, pos in enumerate(vec_order)}

        fused_scores = {
            idx: (bm25_weight * (1.0 / (rrf_k + bm25_ranks[idx])))
            + (vector_weight * (1.0 / (rrf_k + vec_ranks[idx])))
            for idx in indices
        }
        sorted_indices = sorted(indices, key=lambda i: fused_scores[i], reverse=True)
        return sorted_indices, fused_scores, expanded_query

    def search(
        self,
        query: str,
        top_n: int = 5,
        top_k_net: int = 20,
        vector_weight: float = 0.60,
        bm25_weight: float = 0.40,
        rrf_k: int = 60,
        use_cross_encoder: bool = True,
        exclude_complied: bool = True,
        macro_zone: str | None = None,
        clean_micro_area: str | None = None,
        component_category: str | None = None,
        component: str | None = None,
    ) -> list[dict[str, Any]]:
        """Runs the full Two-Stage Retrieve & Re-Rank pipeline with optional metadata fences."""
        fenced_indices = self._filter_indices(
            macro_zone=macro_zone,
            clean_micro_area=clean_micro_area,
            component_category=component_category,
            component=component,
        )
        if not fenced_indices:
            return []

        if not query.strip():
            raw = [self.database[i].copy() for i in fenced_indices]
            return deduplicate_results(
                raw, top_n=top_n, exclude_complied=exclude_complied
            )

        stage1_indices, fused_scores, expanded_query = self.rank_stage1_rrf(
            query=query,
            vector_weight=vector_weight,
            bm25_weight=bm25_weight,
            rrf_k=rrf_k,
            candidate_indices=fenced_indices,
        )

        pool_indices = stage1_indices[: min(top_k_net, len(stage1_indices))]
        ranked_candidates: list[dict[str, Any]] = []

        if use_cross_encoder and self.cross_encoder is not None and pool_indices:
            pairs = [[expanded_query, self.vector_corpus[idx]] for idx in pool_indices]
            cross_scores = self.cross_encoder.predict(pairs)
            reranked_order = np.argsort(cross_scores)[::-1]
            for pos in reranked_order:
                orig_idx = pool_indices[pos]
                item = self.database[orig_idx].copy()
                item["rrf_score"] = round(float(fused_scores[orig_idx]), 5)
                item["cross_encoder_score"] = round(float(cross_scores[pos]), 4)
                ranked_candidates.append(item)
        else:
            for orig_idx in pool_indices:
                item = self.database[orig_idx].copy()
                item["rrf_score"] = round(float(fused_scores[orig_idx]), 5)
                ranked_candidates.append(item)

        return deduplicate_results(
            ranked_candidates,
            top_n=top_n,
            exclude_complied=exclude_complied,
        )
