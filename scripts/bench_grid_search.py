#!/usr/bin/env python3
"""bench_grid_search — Cherche la meilleure config rerank PR sur les 9 LECO.

Réutilise les top-N binaires DÉJÀ calculés (un seul embed par question, puis
on teste plusieurs (top_k_underlying, w_pr) sur le même pool). Coût marginal
nul vs un seul run.

Output: kb_artifacts/grid_search_results.json
"""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

for _pkg, _parts in [
    ("lucie_v1_standalone", ["lucie_v1_standalone"]),
    ("lucie_v1_standalone.knowledge_legifrance", ["lucie_v1_standalone", "knowledge_legifrance"]),
]:
    if _pkg not in sys.modules:
        m = types.ModuleType(_pkg)
        m.__path__ = [str(_REPO_ROOT.joinpath(*_parts))]  # type: ignore[attr-defined]
        sys.modules[_pkg] = m

import numpy as np  # noqa: E402

from lucie_v1_standalone.knowledge_legifrance.kb_compact.constants import LONG_BITS  # noqa: E402
from lucie_v1_standalone.knowledge_legifrance.kb_compact.embedder import (  # noqa: E402
    Embedder, EmbedderConfig, binary_quantize,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.pagerank import read_pagerank_f32  # noqa: E402
from lucie_v1_standalone.knowledge_legifrance.kb_compact.sig_reader import load_index, load_sigs  # noqa: E402
from lucie_v1_standalone.knowledge_legifrance.refs_extractor import extract_refs_from_behavior  # noqa: E402


def resolve_refs(refs, db_path: Path) -> list[str]:
    if not refs:
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        ids: list[str] = []
        for prefix, num in refs:
            canon = "".join(c for c in f"{prefix}{num}".upper() if not c.isspace() and c != ".")
            cur.execute(
                "SELECT id FROM articles WHERE etat='VIGUEUR' AND "
                "REPLACE(REPLACE(UPPER(num),' ',''),'.','') = ?", (canon,))
            for row in cur.fetchall():
                ids.append(row[0])
        return ids
    finally:
        conn.close()


def pr_rerank(rows: np.ndarray, popcount: np.ndarray, pagerank: np.ndarray,
              w_pop: float, w_pr: float) -> list[int]:
    if len(rows) == 0:
        return []
    pop_max = float(popcount.max()) if popcount.max() > 0 else 1.0
    pop_norm = 1.0 - (popcount.astype(np.float32) / pop_max)
    pr_scores = pagerank[rows].astype(np.float32)
    pr_log = np.log1p(pr_scores * 1e6)
    pr_max = float(pr_log.max()) if pr_log.max() > 0 else 1.0
    pr_norm = pr_log / pr_max
    combined = w_pop * pop_norm + w_pr * pr_norm
    order = np.argsort(combined)[::-1]
    return [int(rows[i]) for i in order]


def main() -> int:
    artifacts = Path("kb_artifacts")
    db_path = Path.home() / "Library" / "Application Support" / "Beaume" / "legifrance" / "legi.sqlite"

    print("Loading artifacts ...")
    header, _, sigs_long = load_sigs(artifacts / "sigs_mrl.bin")
    index = load_index(artifacts / "sigs_mrl.index.cbor")
    article_to_row = index["article_to_row"]
    _, pagerank = read_pagerank_f32(artifacts / "pagerank.f32")

    print("Loading bench ...")
    bench = json.loads(Path("bench/swiss_watch_50.json").read_text())

    print("Loading embedder ...")
    embedder = Embedder(EmbedderConfig(model_name="BAAI/bge-m3", seed=42, auto_download=True))

    # Pré-calcul : pour chaque question matchable, popcount complet + expected_rows
    cached: list[dict] = []
    for q in bench:
        refs = extract_refs_from_behavior(q.get("expected_behavior", ""))
        if not refs:
            continue
        expected_aids = resolve_refs(refs, db_path)
        expected_rows = {article_to_row[a] for a in expected_aids if a in article_to_row}
        if not expected_rows:
            continue
        print(f"  embed {q['id']}")
        qv = embedder.embed_one(q["prompt"])
        qs = binary_quantize(qv[np.newaxis, :], LONG_BITS)[0]
        xor = np.bitwise_xor(sigs_long, qs[np.newaxis, :])
        popcount_full = np.unpackbits(xor, axis=1).sum(axis=1)
        cached.append({
            "qid": q["id"],
            "popcount_full": popcount_full,
            "expected_rows": expected_rows,
        })

    n = len(cached)
    print(f"\n{n} questions matchables\n")

    # Grid search
    top_k_grid = [50, 100, 200, 500, 1000]
    w_pr_grid = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]

    results = []
    print(f"{'top_k':>6} | " + " | ".join(f"w_pr={w:.1f}" for w in w_pr_grid))
    for top_k in top_k_grid:
        row = []
        for w_pr in w_pr_grid:
            w_pop = 1.0 - w_pr
            hits = 0
            details: list[bool] = []
            for c in cached:
                # Top-K binaire
                pop = c["popcount_full"]
                top_idx = np.argpartition(pop, top_k)[:top_k]
                top_rows = top_idx[np.argsort(pop[top_idx])]
                # Rerank PR
                reranked = pr_rerank(top_rows, pop[top_rows], pagerank, w_pop, w_pr)
                top10 = reranked[:10]
                hit = bool(set(top10) & c["expected_rows"])
                details.append(hit)
                if hit:
                    hits += 1
            results.append({
                "top_k_underlying": top_k,
                "w_pop": w_pop,
                "w_pr": w_pr,
                "hits": hits,
                "recall": hits / n,
                "details": {c["qid"]: h for c, h in zip(cached, details)},
            })
            row.append(f"{hits:>2d}/{n}")
        print(f"{top_k:>6} | " + " | ".join(f"{c:>6s}" for c in row))

    # Best config
    best = max(results, key=lambda r: r["recall"])
    print(f"\nBest: top_k={best['top_k_underlying']} w_pr={best['w_pr']} → {best['hits']}/{n} = {best['recall']*100:.2f}%")
    print("Details:")
    for qid, h in best["details"].items():
        mark = "HIT" if h else "MIS"
        print(f"  {mark}  {qid}")

    Path("kb_artifacts/grid_search_results.json").write_text(
        json.dumps({"n_matchable": n, "results": results, "best": best}, indent=2,
                   ensure_ascii=False, default=str)
    )
    print("\nFull results saved → kb_artifacts/grid_search_results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
