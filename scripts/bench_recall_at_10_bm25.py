#!/usr/bin/env python3
"""bench_recall_at_10_bm25 — Diagnostic Sprint K-1 : recall@10 pur BM25 (FTS5).

Mesure ce qu'on obtient en ignorant complètement les signatures binaires et en
n'utilisant que l'index full-text SQLite (articles_fts). Sert à isoler la
contribution lexicale vs sémantique. Non destiné à la production, additif diag.

Sortie : kb_artifacts/recall_at_10_bm25.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lucie_v1_standalone.knowledge_legifrance.refs_extractor import extract_refs_from_behavior  # noqa: E402

logger = logging.getLogger(__name__)


# Stopwords français + tokens trop courts qui ajoutent du bruit au BM25
_STOPWORDS = {
    "le", "la", "les", "un", "une", "des", "de", "du", "au", "aux",
    "et", "ou", "ni", "que", "qui", "quoi", "dont", "où", "ce", "ces",
    "est", "sont", "etre", "être", "ete", "été", "sera", "serait",
    "pour", "par", "sur", "sous", "dans", "avec", "sans", "vers", "chez",
    "en", "se", "sa", "son", "ses", "leur", "leurs", "il", "elle", "on",
    "ne", "pas", "ni", "non", "plus", "moins", "mais", "donc", "car",
    "comment", "pourquoi", "quel", "quelle", "quels", "quelles",
    "selon", "ainsi", "encore", "aussi", "egalement", "également",
    "the", "of", "and", "or", "to", "in", "is", "are",
}

_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)


def sanitize_for_fts5(text: str) -> str:
    """Construit une query FTS5 sûre depuis un prompt en langue naturelle.

    - Normalise NFC
    - Casse en tokens alphanumériques uniquement
    - Filtre stopwords + tokens de longueur < 3
    - Joint par OR (FTS5 fait un AND implicite sinon, trop strict pour BM25)
    - Échappe chaque token en "<token>" (FTS5 phrase, neutralise les opérateurs)
    """
    text = unicodedata.normalize("NFC", text)
    tokens = _WORD_RE.findall(text.lower())
    keep: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        if len(t) < 3:
            continue
        if t in _STOPWORDS:
            continue
        if t in seen:
            continue
        seen.add(t)
        # Phrase-quote pour neutraliser les opérateurs FTS5 (AND, OR, NOT, NEAR, *)
        keep.append(f'"{t}"')
    if not keep:
        keep.append('"droit"')  # fallback minimal pour ne jamais envoyer une query vide
    return " OR ".join(keep)


def resolve_refs_to_article_ids(refs, db_path: Path) -> list[str]:
    """Identique à la fonction du bench principal (réutilisée par sécurité)."""
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
                "REPLACE(REPLACE(UPPER(num),' ',''),'.','') = ?",
                (canon,),
            )
            for row in cur.fetchall():
                ids.append(row[0])
        return ids
    finally:
        conn.close()


def bm25_top_k(conn: sqlite3.Connection, fts_query: str, k: int) -> list[str]:
    """Top-k article_ids par BM25 sur articles_fts (VIGUEUR uniquement)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT a.id
        FROM articles_fts f
        JOIN articles a ON a.rowid = f.rowid
        WHERE articles_fts MATCH ?
          AND a.etat = 'VIGUEUR'
        ORDER BY bm25(articles_fts)
        LIMIT ?
        """,
        (fts_query, k),
    )
    return [row[0] for row in cur.fetchall()]


@dataclass
class BM25Result:
    qid: str
    category: str
    expected_refs: list[list[str]]
    expected_article_ids: list[str]
    top10_aids: list[str]
    hit_at_10: bool
    top30_aids: list[str]
    hit_at_30: bool
    fts_query: str
    skipped_reason: str | None


def run_bench(
    *,
    bench_path: Path,
    db_path: Path,
    output_path: Path,
    top_k_max: int = 30,
) -> int:
    bench = json.loads(bench_path.read_text())
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    results: list[BM25Result] = []
    n_matchable = 0
    n_hit_10 = 0
    n_hit_30 = 0
    latencies: list[float] = []
    t_start = time.monotonic()

    for q in bench:
        qid = q.get("id", "?")
        category = q.get("category", "?")
        expected_behavior = q.get("expected_behavior", "")
        prompt = q.get("prompt", "")

        refs = extract_refs_from_behavior(expected_behavior)
        if not refs:
            results.append(BM25Result(
                qid=qid, category=category,
                expected_refs=[], expected_article_ids=[],
                top10_aids=[], hit_at_10=False,
                top30_aids=[], hit_at_30=False,
                fts_query="", skipped_reason="no_expected_refs_in_behavior",
            ))
            continue
        expected_aids = resolve_refs_to_article_ids(refs, db_path)
        if not expected_aids:
            results.append(BM25Result(
                qid=qid, category=category,
                expected_refs=[list(r) for r in refs],
                expected_article_ids=[],
                top10_aids=[], hit_at_10=False,
                top30_aids=[], hit_at_30=False,
                fts_query="", skipped_reason="refs_not_resolvable_in_kb",
            ))
            continue

        fts_query = sanitize_for_fts5(prompt)
        t0 = time.perf_counter()
        top30 = bm25_top_k(conn, fts_query, top_k_max)
        latencies.append((time.perf_counter() - t0) * 1000)
        top10 = top30[:10]

        expected_set = set(expected_aids)
        hit10 = bool(set(top10) & expected_set)
        hit30 = bool(set(top30) & expected_set)

        n_matchable += 1
        if hit10:
            n_hit_10 += 1
        if hit30:
            n_hit_30 += 1

        results.append(BM25Result(
            qid=qid, category=category,
            expected_refs=[list(r) for r in refs],
            expected_article_ids=expected_aids,
            top10_aids=top10,
            hit_at_10=hit10,
            top30_aids=top30,
            hit_at_30=hit30,
            fts_query=fts_query,
            skipped_reason=None,
        ))

    elapsed = time.monotonic() - t_start
    conn.close()

    recall_10 = n_hit_10 / n_matchable if n_matchable else 0.0
    recall_30 = n_hit_30 / n_matchable if n_matchable else 0.0

    lat = sorted(latencies)
    lat_stats = {
        "p50": lat[len(lat) // 2] if lat else 0.0,
        "p95": lat[int(len(lat) * 0.95)] if lat else 0.0,
        "mean": sum(lat) / len(lat) if lat else 0.0,
        "n_samples": len(lat),
    }

    report = {
        "schema_version": 1,
        "method": "bm25_only_fts5",
        "n_questions_total": len(bench),
        "n_questions_matchable": n_matchable,
        "n_hit_at_10": n_hit_10,
        "n_hit_at_30": n_hit_30,
        "recall_at_10": recall_10,
        "recall_at_30": recall_30,
        "latency_ms_per_query": lat_stats,
        "wall_clock_seconds": elapsed,
        "questions": [asdict(r) for r in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    logger.info("===== BM25-ONLY BENCH =====")
    logger.info("matchable=%d  recall@10=%.2f%%  recall@30=%.2f%%",
                n_matchable, recall_10 * 100, recall_30 * 100)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="K-1 diag — recall pur BM25 FTS5")
    p.add_argument("--bench", type=Path, default=Path("bench/swiss_watch_50.json"))
    p.add_argument(
        "--db",
        type=Path,
        default=Path.home() / "Library" / "Application Support" / "Beaume" / "legifrance" / "legi.sqlite",
    )
    p.add_argument("--output", type=Path, default=Path("kb_artifacts/recall_at_10_bm25.json"))
    p.add_argument("--top-k-max", type=int, default=30)
    p.add_argument("--log-level", type=str, default="INFO")
    args = p.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    return run_bench(
        bench_path=args.bench,
        db_path=args.db,
        output_path=args.output,
        top_k_max=args.top_k_max,
    )


if __name__ == "__main__":
    sys.exit(main())
