#!/usr/bin/env python3
"""bench_recall_at_10 — Sprint K-1, mesure recall@10 sur swiss_watch_50.

Pour chaque question matchable :
    1. extract_refs_from_behavior(expected_behavior) → set d'expected_articles
    2. Résoudre chaque (prefix, num) → article_id concret via legi.sqlite
    3. Mapper article_id → row index via sigs_mrl.index.cbor
    4. Embed query via le même modèle → quantize 1024-bit
    5. Top-10 voisins par distance Hamming (brute force NumPy XOR+popcount)
    6. hit = bool(set(top10_rows) ∩ expected_rows)

Filtre les questions sans expected articles extractibles (article_invalid,
oos_*, small_talk) — recall@10 = hits / questions matchables.

Truth rule : si recall@10 < 90%, écrit le résultat tel quel + propose 3 pistes
de remédiation dans le rapport.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np  # noqa: E402

from lucie_v1_standalone.knowledge_legifrance.kb_compact.constants import (  # noqa: E402
    DEFAULT_TOP_K,
    LONG_BITS,
    RECALL_THRESHOLD,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.embedder import (  # noqa: E402
    Embedder,
    EmbedderConfig,
    binary_quantize,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.sig_reader import (  # noqa: E402
    load_index,
    load_sigs,
)
from lucie_v1_standalone.knowledge_legifrance.refs_extractor import extract_refs_from_behavior  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class QuestionResult:
    qid: str
    category: str
    expected_refs: list[list[str]]
    expected_rows: list[int]
    top10_rows: list[int]
    hit: bool
    n_expected_resolvable: int
    skipped_reason: str | None


def _canonicalize(raw: str) -> str:
    return "".join(c for c in raw.upper() if not c.isspace() and c != ".")


def resolve_refs_to_article_ids(
    refs: list[tuple[str, str]],
    db_path: Path,
) -> list[str]:
    """Résout (prefix, num) → article_id via legi.sqlite VIGUEUR.

    Une référence peut correspondre à plusieurs article_id (homonymes sur
    plusieurs codes). On retourne tous les candidats VIGUEUR.
    """
    if not refs:
        return []
    db_uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    try:
        cur = conn.cursor()
        ids: list[str] = []
        for prefix, num in refs:
            canon = _canonicalize(f"{prefix}{num}")
            cur.execute(
                "SELECT id, num FROM articles WHERE etat='VIGUEUR' AND "
                "REPLACE(REPLACE(UPPER(num),' ',''),'.','') = ?",
                (canon,),
            )
            for row in cur.fetchall():
                ids.append(row[0])
        return ids
    finally:
        conn.close()


def hamming_top_k(
    query_sig: np.ndarray,
    sigs_long: np.ndarray,
    k: int,
) -> np.ndarray:
    """Brute force Hamming top-k.

    Args:
        query_sig: [long_bytes] uint8
        sigs_long: [N, long_bytes] uint8
        k: top-k à retourner

    Returns:
        Indices des k articles les plus proches en Hamming.
    """
    if query_sig.ndim != 1:
        raise ValueError("query_sig must be 1-D")
    xor = np.bitwise_xor(sigs_long, query_sig[np.newaxis, :])
    popcount = np.unpackbits(xor, axis=1).sum(axis=1)
    if k >= sigs_long.shape[0]:
        return np.argsort(popcount)
    top = np.argpartition(popcount, k)[:k]
    return top[np.argsort(popcount[top])]


def run_bench(
    *,
    artifacts_dir: Path,
    bench_path: Path,
    db_path: Path,
    output_path: Path,
    model_name: str,
    seed: int,
    auto_download: bool,
    top_k: int,
) -> int:
    bench = json.loads(bench_path.read_text())
    if not isinstance(bench, list):
        raise ValueError(f"Expected list, got {type(bench)}")

    logger.info("Loading signatures from %s ...", artifacts_dir / "sigs_mrl.bin")
    header, _sigs_short, sigs_long = load_sigs(artifacts_dir / "sigs_mrl.bin")
    index = load_index(artifacts_dir / "sigs_mrl.index.cbor")
    article_to_row: dict[str, int] = index["article_to_row"]
    logger.info("Loaded %d signatures, model in header = %s",
                header.n_articles, header.model_name)

    embedder = Embedder(EmbedderConfig(
        model_name=model_name,
        seed=seed,
        auto_download=auto_download,
    ))

    results: list[QuestionResult] = []
    n_matchable = 0
    n_hit = 0
    t_start = time.monotonic()

    for i, q in enumerate(bench, 1):
        qid = q.get("id", f"Q-{i}")
        category = q.get("category", "unknown")
        expected_behavior = q.get("expected_behavior", "")
        prompt = q.get("prompt", "")

        refs = extract_refs_from_behavior(expected_behavior)
        if not refs:
            results.append(QuestionResult(
                qid=qid, category=category,
                expected_refs=[], expected_rows=[],
                top10_rows=[], hit=False,
                n_expected_resolvable=0,
                skipped_reason="no_expected_refs_in_behavior",
            ))
            continue

        expected_article_ids = resolve_refs_to_article_ids(refs, db_path)
        expected_rows: list[int] = []
        for aid in expected_article_ids:
            row = article_to_row.get(aid)
            if row is not None:
                expected_rows.append(row)

        if not expected_rows:
            results.append(QuestionResult(
                qid=qid, category=category,
                expected_refs=[list(r) for r in refs],
                expected_rows=[],
                top10_rows=[], hit=False,
                n_expected_resolvable=0,
                skipped_reason="refs_not_resolvable_in_kb",
            ))
            continue

        query_vec = embedder.embed_one(prompt)
        query_sig = binary_quantize(query_vec[np.newaxis, :], LONG_BITS)[0]
        top_rows = hamming_top_k(query_sig, sigs_long, top_k).tolist()

        hit = bool(set(top_rows) & set(expected_rows))
        n_matchable += 1
        if hit:
            n_hit += 1
        results.append(QuestionResult(
            qid=qid, category=category,
            expected_refs=[list(r) for r in refs],
            expected_rows=expected_rows,
            top10_rows=top_rows,
            hit=hit,
            n_expected_resolvable=len(expected_rows),
            skipped_reason=None,
        ))

    elapsed = time.monotonic() - t_start

    recall = n_hit / n_matchable if n_matchable > 0 else 0.0
    pass_threshold = recall >= RECALL_THRESHOLD

    report = {
        "schema_version": 1,
        "sprint": "K-1",
        "model": model_name,
        "n_questions_total": len(bench),
        "n_questions_matchable": n_matchable,
        "n_questions_hit": n_hit,
        "recall_at_10": recall,
        "threshold": RECALL_THRESHOLD,
        "pass_threshold": pass_threshold,
        "wall_clock_seconds": elapsed,
        "remediation_proposals_if_fail": [
            "Matryoshka 2048-bit (doubler résolution signatures)",
            "Hybride BM25 + binary (combine lexical et sémantique)",
            "Re-rank top-100 par PageRank pour favoriser articles centraux",
        ] if not pass_threshold else None,
        "questions": [asdict(r) for r in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    logger.info("===== BENCH COMPLETE =====")
    logger.info("Matchable questions: %d / %d", n_matchable, len(bench))
    logger.info("Recall@%d: %.1f%% (threshold %.0f%%)",
                top_k, recall * 100, RECALL_THRESHOLD * 100)
    logger.info("Pass: %s", "✓" if pass_threshold else "✗")
    logger.info("Wall: %.1fs", elapsed)
    return 0 if pass_threshold else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sprint K-1 — recall@10 bench")
    p.add_argument("--artifacts", type=Path, default=Path("kb_artifacts"))
    p.add_argument("--bench", type=Path, default=Path("bench/swiss_watch_50.json"))
    p.add_argument("--db", type=Path,
                   default=Path.home() / "Library" / "Application Support" / "Beaume" / "legifrance" / "legi.sqlite")
    p.add_argument("--output", type=Path, default=Path("kb_artifacts/recall_at_10_report.json"))
    p.add_argument("--model", type=str, default=None,
                   help="Override model. Default: read from sigs header")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--auto-download", action="store_true")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p.add_argument("--log-level", type=str, default="INFO")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    if args.model is None:
        from lucie_v1_standalone.knowledge_legifrance.kb_compact.sig_reader import read_header
        hdr = read_header(args.artifacts / "sigs_mrl.bin")
        args.model = hdr.model_name
        logger.info("Using model from sigs header: %s", args.model)

    return run_bench(
        artifacts_dir=args.artifacts,
        bench_path=args.bench,
        db_path=args.db,
        output_path=args.output,
        model_name=args.model,
        seed=args.seed,
        auto_download=args.auto_download,
        top_k=args.top_k,
    )


if __name__ == "__main__":
    sys.exit(main())
