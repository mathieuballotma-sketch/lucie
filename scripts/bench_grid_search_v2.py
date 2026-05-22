#!/usr/bin/env python3
"""Grid v2 — teste si filtrer les non-codifiés EARLY pousse LECO-001 dans top-10.

Variante : top-K binaire → FILTRE codifié L./R./D./A. → rerank PR → top-10.
Combiné avec un grid sur top_k et w_pr.

Plus une option BM25 mergée dans le pool initial.
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

_CODE_NUM_RE = re.compile(r"^[LRDA]\.?\s*\d{1,5}(-\d{1,4})?\s*$")

_STOPWORDS = {
    "le", "la", "les", "un", "une", "des", "de", "du", "au", "aux",
    "et", "ou", "ni", "que", "qui", "quoi", "dont", "où", "ce", "ces",
    "est", "sont", "etre", "être", "ete", "été",
    "pour", "par", "sur", "sous", "dans", "avec", "sans", "vers", "chez",
    "en", "se", "sa", "son", "ses", "leur", "leurs", "il", "elle", "on",
    "ne", "pas", "plus", "moins", "mais", "donc", "car",
    "comment", "pourquoi", "quel", "quelle", "quels", "quelles",
    "selon", "ainsi", "encore", "aussi",
}
_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)


def sanitize_for_fts5(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    tokens = _WORD_RE.findall(text.lower())
    keep, seen = [], set()
    for t in tokens:
        if len(t) < 3 or t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        keep.append(f'"{t}"')
    if not keep:
        keep.append('"droit"')
    return " OR ".join(keep)


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


def pr_rerank(rows, popcount, pagerank, w_pop, w_pr):
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


def main():
    artifacts = Path("kb_artifacts")
    db_path = Path.home() / "Library" / "Application Support" / "Beaume" / "legifrance" / "legi.sqlite"
    print("Loading ...")
    header, _, sigs_long = load_sigs(artifacts / "sigs_mrl.bin")
    index = load_index(artifacts / "sigs_mrl.index.cbor")
    article_to_row = index["article_to_row"]
    row_to_article = {v: k for k, v in article_to_row.items()}
    _, pagerank = read_pagerank_f32(artifacts / "pagerank.f32")

    bench = json.loads(Path("bench/swiss_watch_50.json").read_text())

    # Connexion DB unique pour récupérer num par article_id (cache)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur_main = conn.cursor()
    num_cache: dict[str, str] = {}

    def get_num(aid: str) -> str:
        if aid in num_cache:
            return num_cache[aid]
        cur_main.execute("SELECT num FROM articles WHERE id=?", (aid,))
        row = cur_main.fetchone()
        num_cache[aid] = (row[0] if row else "") or ""
        return num_cache[aid]

    def is_codified_row(row: int) -> bool:
        aid = row_to_article.get(row)
        if aid is None:
            return False
        return bool(_CODE_NUM_RE.match(get_num(aid).strip()))

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

        # BM25 top-100
        fts_query = sanitize_for_fts5(q["prompt"])
        cur_main.execute(
            "SELECT a.id FROM articles_fts f JOIN articles a ON a.rowid=f.rowid "
            "WHERE articles_fts MATCH ? AND a.etat='VIGUEUR' "
            "ORDER BY bm25(articles_fts) LIMIT 100", (fts_query,))
        bm25_rows = [article_to_row[r[0]] for r in cur_main.fetchall() if r[0] in article_to_row]

        cached.append({
            "qid": q["id"],
            "popcount_full": popcount_full,
            "expected_rows": expected_rows,
            "bm25_rows": bm25_rows,
        })

    n = len(cached)
    print(f"\n{n} questions matchables\n")

    # Variantes testées
    variants_def = {
        # Baseline reference
        "V1_binary_only_top10": {},
        # PR rerank tunings
        "V2a_binary_pr_K100_w03": {"pool": "binary", "K": 100, "w_pr": 0.3, "filter_codified": False},
        "V2b_binary_pr_K50_w02":  {"pool": "binary", "K": 50,  "w_pr": 0.2, "filter_codified": False},
        # NEW: filter codified EARLY
        "V5a_codified_K100_w03": {"pool": "binary", "K": 100, "w_pr": 0.3, "filter_codified": True},
        "V5b_codified_K200_w02": {"pool": "binary", "K": 200, "w_pr": 0.2, "filter_codified": True},
        "V5c_codified_K500_w03": {"pool": "binary", "K": 500, "w_pr": 0.3, "filter_codified": True},
        "V5d_codified_K100_w05": {"pool": "binary", "K": 100, "w_pr": 0.5, "filter_codified": True},
        # NEW: pool = union binary + bm25, filter codified
        "V6a_union_codified_K100_w03": {"pool": "union", "K": 100, "w_pr": 0.3, "filter_codified": True},
        "V6b_union_codified_K200_w03": {"pool": "union", "K": 200, "w_pr": 0.3, "filter_codified": True},
    }

    def evaluate(spec: dict, c: dict) -> bool:
        if not spec:  # V1 baseline
            top10 = np.argsort(c["popcount_full"])[:10].tolist()
            return bool(set(top10) & c["expected_rows"])

        K = spec["K"]
        pop = c["popcount_full"]
        # Construire le pool
        top_idx = np.argpartition(pop, K)[:K]
        top_rows_binary = top_idx[np.argsort(pop[top_idx])].tolist()
        if spec["pool"] == "union":
            pool = list(dict.fromkeys(top_rows_binary + c["bm25_rows"][:K]))
        else:
            pool = top_rows_binary

        # Filtrer codified si demandé
        if spec.get("filter_codified", False):
            pool = [r for r in pool if is_codified_row(r)]

        if not pool:
            return False

        # Rerank PR
        pool_arr = np.array(pool, dtype=np.int64)
        # Popcount du pool : pour rows pas dans binary_top_K, on prend pop_full[row]
        pool_pop = pop[pool_arr]
        reranked = pr_rerank(pool_arr, pool_pop, pagerank,
                             1.0 - spec["w_pr"], spec["w_pr"])
        return bool(set(reranked[:10]) & c["expected_rows"])

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
        summary[vname] = {"hits": hits, "recall": hits / n}
        detail[vname] = per_q

    # Print
    qids = [c["qid"] for c in cached]
    print(f"\n{'variant':35s}  recall   " + "  ".join(q[-3:] for q in qids))
    print("-" * 100)
    for vname, s in summary.items():
        marks = "  ".join(("H" if detail[vname][q] else ".").rjust(3) for q in qids)
        bar = "█" * int(s["recall"] * 30)
        print(f"{vname:35s}  {s['recall']*100:5.2f}%  {marks}    {bar}")

    best = max(summary.items(), key=lambda kv: kv[1]["recall"])
    print(f"\n=== BEST : {best[0]} → {best[1]['hits']}/{n} = {best[1]['recall']*100:.2f}% ===")

    Path("kb_artifacts/grid_search_v2.json").write_text(json.dumps({
        "n_matchable": n,
        "summary": summary,
        "detail": detail,
    }, indent=2, ensure_ascii=False))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
