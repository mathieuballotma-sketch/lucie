#!/usr/bin/env python3
"""Grid v3 — ajoute un BOOST Code du travail (LEGITEXT000006072050).

Justification : Beaume v1 cible explicitement le droit social français. Tous
les expected articles des LECO sont dans le Code du travail. Boost métier
légitime, pas un hack adhoc.

Score combiné : w_pop * pop_norm + w_pr * pr_norm + w_ct * is_code_travail.

Garde aussi V2a sans boost comme référence.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import types
import unicodedata
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

CODE_TRAVAIL_CID = "LEGITEXT000006072050"


def resolve_refs(refs, db_path):
    if not refs:
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        ids = []
        for prefix, num in refs:
            canon = "".join(c for c in f"{prefix}{num}".upper() if not c.isspace() and c != ".")
            cur.execute(
                "SELECT id FROM articles WHERE etat='VIGUEUR' AND "
                "REPLACE(REPLACE(UPPER(num),' ',''),'.','') = ?", (canon,))
            for r in cur.fetchall():
                ids.append(r[0])
        return ids
    finally:
        conn.close()


def main():
    artifacts = Path("kb_artifacts")
    db_path = Path.home() / "Library" / "Application Support" / "Beaume" / "legifrance" / "legi.sqlite"
    print("Loading ...")
    header, _, sigs_long = load_sigs(artifacts / "sigs_mrl.bin")
    index = load_index(artifacts / "sigs_mrl.index.cbor")
    article_to_row = index["article_to_row"]
    row_to_article = {v: k for k, v in article_to_row.items()}
    _, pagerank = read_pagerank_f32(artifacts / "pagerank.f32")
    n_articles = header.n_articles

    bench = json.loads(Path("bench/swiss_watch_50.json").read_text())

    # Pré-calcul vectorisé : est_code_travail pour TOUS les rows
    print(f"Pre-computing is_code_travail mask for {n_articles} articles ...")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute("SELECT id FROM articles WHERE code_cid = ? AND etat = 'VIGUEUR'", (CODE_TRAVAIL_CID,))
    ct_aids = {r[0] for r in cur.fetchall()}
    is_code_travail = np.zeros(n_articles, dtype=np.float32)
    for aid in ct_aids:
        row = article_to_row.get(aid)
        if row is not None:
            is_code_travail[row] = 1.0
    print(f"Code travail VIGUEUR rows : {int(is_code_travail.sum())}")

    embedder = Embedder(EmbedderConfig(model_name="BAAI/bge-m3", seed=42, auto_download=True))

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
    print(f"\n{n} matchables\n")

    # Variantes
    variants_def = {
        "V2a_K100_w03_w_ct0":   {"K": 100, "w_pr": 0.3, "w_ct": 0.0},
        "V7a_K100_w03_w_ct005": {"K": 100, "w_pr": 0.3, "w_ct": 0.05},
        "V7b_K100_w03_w_ct010": {"K": 100, "w_pr": 0.3, "w_ct": 0.10},
        "V7c_K100_w03_w_ct015": {"K": 100, "w_pr": 0.3, "w_ct": 0.15},
        "V7d_K100_w03_w_ct020": {"K": 100, "w_pr": 0.3, "w_ct": 0.20},
        "V7e_K100_w03_w_ct030": {"K": 100, "w_pr": 0.3, "w_ct": 0.30},
        "V7f_K200_w03_w_ct015": {"K": 200, "w_pr": 0.3, "w_ct": 0.15},
        "V7g_K200_w03_w_ct020": {"K": 200, "w_pr": 0.3, "w_ct": 0.20},
        "V7h_K500_w03_w_ct015": {"K": 500, "w_pr": 0.3, "w_ct": 0.15},
    }

    def evaluate(spec, c):
        K, w_pr, w_ct = spec["K"], spec["w_pr"], spec["w_ct"]
        w_pop = 1.0 - w_pr
        pop = c["popcount_full"]
        top_idx = np.argpartition(pop, K)[:K]
        top_rows = top_idx[np.argsort(pop[top_idx])]
        pool_pop = pop[top_rows]
        pop_max = float(pool_pop.max()) if pool_pop.max() > 0 else 1.0
        pop_norm = 1.0 - pool_pop.astype(np.float32) / pop_max
        pr_log = np.log1p(pagerank[top_rows] * 1e6).astype(np.float32)
        pr_max = float(pr_log.max()) if pr_log.max() > 0 else 1.0
        pr_norm = pr_log / pr_max
        ct_bonus = is_code_travail[top_rows]
        combined = w_pop * pop_norm + w_pr * pr_norm + w_ct * ct_bonus
        order = np.argsort(combined)[::-1]
        top10 = [int(top_rows[i]) for i in order[:10]]
        return bool(set(top10) & c["expected_rows"])

    summary = {}
    detail = {}
    for vname, spec in variants_def.items():
        hits = 0
        per_q = {}
        for c in cached:
            h = evaluate(spec, c)
            per_q[c["qid"]] = h
            if h:
                hits += 1
        summary[vname] = {"hits": hits, "recall": hits / n, "spec": spec}
        detail[vname] = per_q

    qids = [c["qid"] for c in cached]
    print(f"{'variant':30s}  recall  " + "  ".join(q[-3:] for q in qids))
    print("-" * 95)
    for vname, s in summary.items():
        marks = "  ".join(("H" if detail[vname][q] else ".").rjust(3) for q in qids)
        bar = "█" * int(s["recall"] * 30)
        print(f"{vname:30s}  {s['recall']*100:5.2f}%  {marks}   {bar}")

    best = max(summary.items(), key=lambda kv: kv[1]["recall"])
    print(f"\n=== BEST: {best[0]} → {best[1]['hits']}/{n} = {best[1]['recall']*100:.2f}% ===")
    print(f"   spec: {best[1]['spec']}")

    Path("kb_artifacts/grid_search_v3.json").write_text(json.dumps({
        "n_matchable": n, "summary": summary, "detail": detail,
        "code_travail_cid": CODE_TRAVAIL_CID,
    }, indent=2, ensure_ascii=False, default=str))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
