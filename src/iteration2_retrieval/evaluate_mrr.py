"""Scientific Retrieval Benchmarking Suite (Stratified Sampling + MRR Grid Search).

Reproduces the Iteration 2 retrieval evaluation methodology:
  1. sample-template:  Stratified round-robin sampling across Macro-Zone x Category buckets.
  2. generate-queries: Batched synthetic messy-auditor query generator (20 rows/prompt).
  3. benchmark:        Sweeps Vector/BM25 RRF weights (0% to 100%) and compares Stage 1
                       Hybrid RRF against Stage 2 Cross-Encoder MRR & Top-1 Hits.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.iteration2_retrieval.hybrid_rrf_engine import TwoStageHybridSearchEngine

load_dotenv()


def sample_stratified_observations(
    database: list[dict[str, Any]],
    sample_size: int,
    exclude_ids: set[str] | None = None,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Selects non-compliant observations evenly across Macro-Zone x Category buckets."""
    rng = random.Random(seed)
    excluded = exclude_ids or set()
    buckets: dict[str, list[dict[str, Any]]] = {}

    for entry in database:
        doc_id = entry.get("doc_id", "")
        if doc_id in excluded:
            continue
        if str(entry.get("compliance_status", "")).strip().lower() in {"complied", "complied."}:
            continue
        key = f"{entry.get('macro_zone', 'General')} || {entry.get('component_category', 'General')}"
        buckets.setdefault(key, []).append(entry)

    sampled: list[dict[str, Any]] = []
    bucket_keys = sorted(buckets.keys())

    while len(sampled) < sample_size and bucket_keys:
        for key in list(bucket_keys):
            if buckets[key]:
                pick = rng.randrange(len(buckets[key]))
                sampled.append(buckets[key].pop(pick))
                if len(sampled) >= sample_size:
                    break
            else:
                bucket_keys.remove(key)

    return sampled


def cmd_sample_template(args: argparse.Namespace) -> None:
    database = json.loads(args.db.read_text(encoding="utf-8"))
    sampled = sample_stratified_observations(database, sample_size=args.count, seed=args.seed)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["doc_id", "macro_zone", "component", "actual_observation", "auditor_query"])
        for entry in sampled:
            writer.writerow(
                [
                    entry.get("doc_id", ""),
                    entry.get("macro_zone", ""),
                    entry.get("component", ""),
                    entry.get("observation", ""),
                    "",
                ]
            )
    print(f"[DONE] Wrote {len(sampled)} stratified template rows to {args.output}.")


def cmd_generate_queries(args: argparse.Namespace) -> None:
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is required for synthetic query generation.")

    client = genai.Client(api_key=api_key)
    database = json.loads(args.db.read_text(encoding="utf-8"))

    existing_rows: list[dict[str, str]] = []
    used_ids: set[str] = set()
    if args.existing_csv and args.existing_csv.exists():
        with args.existing_csv.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing_rows.append(row)
                if row.get("doc_id"):
                    used_ids.add(row["doc_id"])

    samples = sample_stratified_observations(
        database, sample_size=args.count, exclude_ids=used_ids, seed=args.seed
    )
    chunk_size = args.batch_size
    chunks = [samples[i : i + chunk_size] for i in range(0, len(samples), chunk_size)]
    generated_rows: list[dict[str, str]] = []

    for c_idx, chunk in enumerate(chunks, start=1):
        print(f"[*] Processing batch {c_idx}/{len(chunks)} ({len(chunk)} items)...")
        prompt_lines = [
            "You are a hurried fire safety auditor on an industrial site.",
            "For EACH observation below, write a short, messy 4-to-7-word search query "
            "using common acronyms (PFE, DG, MCC, FDAS, etc.) with no punctuation.",
            "OUTPUT FORMAT: Return EXACTLY one line per observation in the same order, "
            "separated by newlines. Do not include numbering or bullets.\n",
        ]
        for i, item in enumerate(chunk, start=1):
            prompt_lines.append(
                f"Observation {i}: Component: {item.get('component', '')} | "
                f"Text: {item.get('observation', '')}"
            )

        try:
            resp = client.models.generate_content(
                model=args.model, contents="\n".join(prompt_lines)
            )
            lines = [ln.strip() for ln in resp.text.strip().splitlines() if ln.strip()]
        except Exception as exc:
            print(f"   [!] Batch {c_idx} failed ({exc}); using fallback queries.")
            lines = []

        for i, item in enumerate(chunk):
            if i < len(lines):
                query = re.sub(r"^\d+[\.\)\-]\s*", "", lines[i].lower())
            else:
                query = f"missing {item.get('component', '').lower()}"

            generated_rows.append(
                {
                    "doc_id": item.get("doc_id", ""),
                    "macro_zone": item.get("macro_zone", ""),
                    "component": item.get("component", ""),
                    "actual_observation": item.get("observation", ""),
                    "auditor_query": query,
                }
            )

        if c_idx < len(chunks):
            time.sleep(args.rpm_delay)

    all_rows = existing_rows + generated_rows
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["doc_id", "macro_zone", "component", "actual_observation", "auditor_query"],
        )
        writer.writeheader()
        for row in all_rows:
            writer.writerow(
                {
                    "doc_id": row.get("doc_id", ""),
                    "macro_zone": row.get("macro_zone", ""),
                    "component": row.get("component", ""),
                    "actual_observation": row.get("actual_observation", ""),
                    "auditor_query": row.get("auditor_query")
                    or row.get("TYPE_AUDITOR_QUERY_HERE", ""),
                }
            )
    print(f"[DONE] Saved {len(all_rows)} benchmark queries to {args.output}.")


def load_ground_truth(csv_path: Path) -> list[dict[str, str]]:
    """Loads target doc_id and query pairs from evaluation CSV."""
    queries: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            q = (row.get("auditor_query") or row.get("TYPE_AUDITOR_QUERY_HERE") or "").strip()
            if q and row.get("doc_id"):
                queries.append({"target_id": row["doc_id"].strip(), "query": q})
    return queries


def cmd_benchmark(args: argparse.Namespace) -> None:
    print(f"[*] Loading database: {args.db}")
    engine = TwoStageHybridSearchEngine.from_json(args.db, load_cross_encoder=True)
    doc_ids = [entry.get("doc_id") for entry in engine.database]
    ground_truth = load_ground_truth(args.queries)

    if not ground_truth:
        raise ValueError(f"No valid test queries found in {args.queries}")

    print(f"[-] Loaded {len(ground_truth)} benchmark queries across {len(doc_ids)} observations.\n")
    print("=" * 60)
    print(" STAGE 1: WEIGHTED RRF HYPERPARAMETER GRID SEARCH")
    print("=" * 60)
    print(f"{'Vector %':<10} | {'BM25 %':<10} | {'Top-1 Hits':<14} | {'MRR Score':<10}")
    print("-" * 60)

    best_mrr = -1.0
    best_vec_weight = 0.60

    for step in range(0, 11):
        vec_w = round(step * 0.1, 2)
        bm25_w = round(1.0 - vec_w, 2)
        total_mrr = 0.0
        top1_hits = 0

        for test in ground_truth:
            sorted_idx, _, _ = engine.rank_stage1_rrf(
                test["query"], vector_weight=vec_w, bm25_weight=bm25_w, rrf_k=args.rrf_k
            )
            target_rank = next(
                (
                    rank
                    for rank, idx in enumerate(sorted_idx, start=1)
                    if doc_ids[idx] == test["target_id"]
                ),
                0,
            )
            if target_rank == 1:
                top1_hits += 1
            if target_rank > 0:
                total_mrr += 1.0 / target_rank

        avg_mrr = total_mrr / len(ground_truth)
        if avg_mrr > best_mrr:
            best_mrr = avg_mrr
            best_vec_weight = vec_w

        print(
            f"{int(vec_w * 100):>3}%{'':<6} | {int(bm25_w * 100):>3}%{'':<6} | "
            f"{top1_hits:>3}/{len(ground_truth):<10} | {avg_mrr:.4f}"
        )

    print("=" * 60)
    print(
        f"Optimal Stage 1 Split : {int(best_vec_weight * 100)}% Vector / "
        f"{int(round((1.0 - best_vec_weight) * 100))}% BM25 (MRR = {best_mrr:.4f})"
    )

    print("\n" + "=" * 60)
    print(f" STAGE 2: CROSS-ENCODER RERANKING (TOP-{args.top_k_net} NET -> SCALPEL)")
    print("=" * 60)

    total_mrr_reranked = 0.0
    top1_reranked = 0

    for test in ground_truth:
        sorted_idx, _, q_expanded = engine.rank_stage1_rrf(
            test["query"],
            vector_weight=best_vec_weight,
            bm25_weight=round(1.0 - best_vec_weight, 2),
            rrf_k=args.rrf_k,
        )
        stage1_rank = next(
            (
                rank
                for rank, idx in enumerate(sorted_idx, start=1)
                if doc_ids[idx] == test["target_id"]
            ),
            0,
        )

        top_pool = sorted_idx[: min(args.top_k_net, len(sorted_idx))]
        if stage1_rank == 0 or stage1_rank > len(top_pool):
            final_rank = stage1_rank
        else:
            cross_inp = [[q_expanded, engine.vector_corpus[idx]] for idx in top_pool]
            cross_scores = engine.cross_encoder.predict(cross_inp)
            reranked_order = np.argsort(cross_scores)[::-1]
            final_rank = next(
                (
                    new_rank
                    for new_rank, pos in enumerate(reranked_order, start=1)
                    if doc_ids[top_pool[pos]] == test["target_id"]
                ),
                stage1_rank,
            )

        if final_rank == 1:
            top1_reranked += 1
        if final_rank > 0:
            total_mrr_reranked += 1.0 / final_rank

    avg_mrr_reranked = total_mrr_reranked / len(ground_truth)
    delta_pct = ((avg_mrr_reranked - best_mrr) / best_mrr * 100.0) if best_mrr > 0 else 0.0

    print(f"Stage 1 (Hybrid RRF)           : MRR = {best_mrr:.4f}")
    print(
        f"Stage 2 (Hybrid + Reranker)    : MRR = {avg_mrr_reranked:.4f} | "
        f"Top-1 = {top1_reranked}/{len(ground_truth)}"
    )
    print(f"Relative MRR Lift              : {delta_pct:+.2f}%")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="MRR Evaluation Suite for FSA Hybrid Retrieval.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_sample = subparsers.add_parser("sample-template", help="Create stratified evaluation CSV.")
    p_sample.add_argument("--db", type=Path, default=Path("data/sample_routed_extract.json"))
    p_sample.add_argument("--output", type=Path, default=Path("data/ground_truth_template.csv"))
    p_sample.add_argument("--count", type=int, default=30)
    p_sample.add_argument("--seed", type=int, default=42)
    p_sample.set_defaults(func=cmd_sample_template)

    p_gen = subparsers.add_parser("generate-queries", help="Batch-generate synthetic auditor queries.")
    p_gen.add_argument("--db", type=Path, default=Path("data/sample_routed_extract.json"))
    p_gen.add_argument("--existing-csv", type=Path, default=None)
    p_gen.add_argument("--output", type=Path, default=Path("data/gold_standard_queries.csv"))
    p_gen.add_argument("--count", type=int, default=100)
    p_gen.add_argument("--batch-size", type=int, default=20)
    p_gen.add_argument("--rpm-delay", type=int, default=15)
    p_gen.add_argument("--model", type=str, default="gemini-2.5-flash")
    p_gen.add_argument("--seed", type=int, default=42)
    p_gen.set_defaults(func=cmd_generate_queries)

    p_bench = subparsers.add_parser(
        "benchmark", help="Run Stage 1 grid search & Stage 2 Cross-Encoder eval."
    )
    p_bench.add_argument("--db", type=Path, default=Path("data/sample_routed_extract.json"))
    p_bench.add_argument("--queries", type=Path, default=Path("data/sample_ground_truth.csv"))
    p_bench.add_argument("--rrf-k", type=int, default=60)
    p_bench.add_argument("--top-k-net", type=int, default=20)
    p_bench.set_defaults(func=cmd_benchmark)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
