#!/usr/bin/env python3
"""build_kb_artifacts — orchestrateur Sprint K-1.

Lit legi.sqlite VIGUEUR → BGE-M3 → produit 3 artefacts dans kb_artifacts/ :
    - sigs_mrl.bin + sigs_mrl.index.cbor (signatures Matryoshka 64+1024 bits)
    - graph.cbor.zst (DAG renvois inter-articles, compressé)
    - pagerank.f32 (PageRank)

Plus :
    - manifest.json : versions, SHAs, model, seed (committable)
    - build_report.json : stats, perf, renvois non résolus (committable)

Usage:
    venv311/bin/python scripts/build_kb_artifacts.py \\
        --db ~/Library/Application\\ Support/Beaume/legifrance/legi.sqlite \\
        --output kb_artifacts/ \\
        --auto-download

Garde-fous :
    - Python ≥ 3.11 strict (pyproject requires-python>=3.11)
    - Aucune écriture dans legi.sqlite (lecture seule)
    - --auto-download OBLIGATOIRE pour télécharger BGE-M3 (2,2 Go)
    - Mode --limit N pour smoke tests
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np  # noqa: E402

from lucie_v1_standalone.knowledge_legifrance.kb_compact import (  # noqa: E402
    DAMPING_PAGERANK,
    DEFAULT_BATCH_SIZE,
    DEFAULT_SEED,
    LONG_BITS,
    MAX_ITER_PAGERANK,
    MODEL_NAME,
    SHORT_BITS,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.constants import (  # noqa: E402
    CHECKPOINT_INTERVAL,
    PYTHON_MIN_MAJOR,
    PYTHON_MIN_MINOR,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.embedder import (  # noqa: E402
    Embedder,
    EmbedderConfig,
    binary_quantize,
    expected_dim_for_model,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.graph_writer import (  # noqa: E402
    GraphBuilder,
    RefResolver,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.pagerank import (  # noqa: E402
    compute_pagerank,
    write_pagerank_f32,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.sig_writer import (  # noqa: E402
    SigBinaryWriter,
    write_index_cbor,
)

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / "Library" / "Application Support" / "Beaume" / "legifrance" / "legi.sqlite"
DEFAULT_OUTPUT = Path("kb_artifacts")


@dataclass
class BuildStats:
    n_articles: int = 0
    n_edges: int = 0
    n_refs_unresolved: int = 0
    n_refs_resolved: int = 0
    n_articles_empty_text: int = 0
    embed_seconds: float = 0.0
    graph_seconds: float = 0.0
    pagerank_seconds: float = 0.0
    total_seconds: float = 0.0
    sigs_bin_bytes: int = 0
    sigs_index_bytes: int = 0
    graph_raw_bytes: int = 0
    graph_compressed_bytes: int = 0
    pagerank_bytes: int = 0
    sha_legi_sqlite: str = ""
    sha_sigs_bin: str = ""
    sha_sigs_index: str = ""
    sha_graph: str = ""
    sha_pagerank: str = ""


@dataclass
class ArticleRow:
    article_id: str
    num_prefix: str
    num_numeric: str
    num: str
    code_cid: str
    texte: str


def check_python_version() -> None:
    if sys.version_info < (PYTHON_MIN_MAJOR, PYTHON_MIN_MINOR):
        raise RuntimeError(
            f"Python ≥ {PYTHON_MIN_MAJOR}.{PYTHON_MIN_MINOR} required, got "
            f"{sys.version_info.major}.{sys.version_info.minor}. "
            f"Run via venv311/bin/python."
        )


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def iter_articles_vigueur(db_path: Path, limit: int | None = None) -> Iterator[ArticleRow]:
    """Stream les articles VIGUEUR depuis legi.sqlite (lecture seule)."""
    db_uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    try:
        cur = conn.cursor()
        query = (
            "SELECT id, COALESCE(num_prefix,''), COALESCE(num_numeric,''), "
            "COALESCE(num,''), COALESCE(code_cid,''), COALESCE(texte,'') "
            "FROM articles WHERE etat='VIGUEUR' ORDER BY id"
        )
        if limit is not None:
            query += f" LIMIT {int(limit)}"
        cur.execute(query)
        for row in cur:
            yield ArticleRow(
                article_id=row[0],
                num_prefix=row[1],
                num_numeric=row[2],
                num=row[3],
                code_cid=row[4],
                texte=row[5],
            )
    finally:
        conn.close()


def count_articles_vigueur(db_path: Path, limit: int | None = None) -> int:
    db_uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM articles WHERE etat='VIGUEUR'")
        total = int(cur.fetchone()[0])
    finally:
        conn.close()
    if limit is not None:
        return min(total, int(limit))
    return total


def build_signatures(
    *,
    db_path: Path,
    output_dir: Path,
    embedder: Embedder,
    n_articles: int,
    corpus_sha: bytes,
    stats: BuildStats,
    limit: int | None,
    short_bits: int,
    long_bits: int,
) -> tuple[dict[str, int], dict[int, tuple[str, str]]]:
    """Pass 1+2 : stream articles → embed → quantize → write streaming.

    Returns:
        article_to_row : dict[article_id, row_index]
        row_to_meta    : dict[row_index, (num, code_cid)] pour le graphe et resolver
    """
    sigs_path = output_dir / "sigs_mrl.bin"

    article_to_row: dict[str, int] = {}
    row_to_meta: dict[int, tuple[str, str]] = {}

    t_start = time.monotonic()

    with SigBinaryWriter(
        sigs_path,
        n_articles=n_articles,
        model_name=embedder.config.model_name,
        seed=embedder.config.seed,
        corpus_sha=corpus_sha,
        short_bits=short_bits,
        long_bits=long_bits,
    ) as writer:
        row = 0
        batch_texts: list[str] = []
        batch_meta: list[tuple[str, str, str]] = []
        last_log_t = t_start
        last_log_row = 0

        def flush_batch() -> int:
            nonlocal row
            if not batch_texts:
                return 0
            vecs = embedder._encode(batch_texts)  # type: ignore[attr-defined]
            short_packed = binary_quantize(vecs, short_bits)
            long_packed = binary_quantize(vecs, long_bits)
            writer.append_batch(short_packed, long_packed)
            for (aid, num, code), _ in zip(batch_meta, range(len(batch_meta))):
                article_to_row[aid] = row
                row_to_meta[row] = (num, code)
                row += 1
            batch_texts.clear()
            batch_meta.clear()
            return short_packed.shape[0]

        for art in iter_articles_vigueur(db_path, limit=limit):
            text = art.texte.strip()
            if not text:
                stats.n_articles_empty_text += 1
                text = f"Article {art.num} (sans texte)."
            batch_texts.append(text)
            batch_meta.append((art.article_id, art.num, art.code_cid))
            if len(batch_texts) >= embedder.config.batch_size:
                flush_batch()
                if row % CHECKPOINT_INTERVAL == 0 or (time.monotonic() - last_log_t) > 30:
                    elapsed = time.monotonic() - t_start
                    rate = (row - last_log_row) / max(0.001, time.monotonic() - last_log_t)
                    eta_sec = (n_articles - row) / max(0.1, row / max(0.001, elapsed))
                    logger.info(
                        "Embed progress: %d/%d (%.1f%%) — batch rate=%.1f art/s — ETA %.0f min",
                        row, n_articles, 100 * row / n_articles, rate, eta_sec / 60,
                    )
                    last_log_t = time.monotonic()
                    last_log_row = row
        flush_batch()

        stats.n_articles = row

    stats.embed_seconds = time.monotonic() - t_start
    stats.sigs_bin_bytes = sigs_path.stat().st_size
    logger.info("Signatures written: %d articles, %.1f Mo, %.1fs",
                stats.n_articles, stats.sigs_bin_bytes / 1e6, stats.embed_seconds)

    index_path = output_dir / "sigs_mrl.index.cbor"
    stats.sigs_index_bytes = write_index_cbor(
        index_path,
        article_to_row=article_to_row,
        corpus_sha=corpus_sha,
    )
    logger.info("Index written: %.1f Mo", stats.sigs_index_bytes / 1e6)
    return article_to_row, row_to_meta


def build_graph(
    *,
    db_path: Path,
    output_dir: Path,
    article_to_row: dict[str, int],
    row_to_meta: dict[int, tuple[str, str]],
    corpus_sha: bytes,
    stats: BuildStats,
    limit: int | None,
) -> None:
    """Pass 3 : reconstruit le resolver, parcourt les articles, écrit le graphe."""
    t_start = time.monotonic()
    resolver = RefResolver()
    for row, (num, code_cid) in row_to_meta.items():
        if num:
            resolver.add_article(row, num, code_cid)
    logger.info("RefResolver built: %d articles indexed", resolver.size)

    builder = GraphBuilder(n_vertices=len(article_to_row))

    for art in iter_articles_vigueur(db_path, limit=limit):
        row = article_to_row.get(art.article_id)
        if row is None:
            continue
        text = art.texte.strip()
        if not text:
            continue
        builder.add_article_edges(row, text, art.code_cid, resolver)

    stats.n_edges = builder.n_edges
    stats.n_refs_resolved = builder.resolved_count
    stats.n_refs_unresolved = builder.unresolved_count

    graph_path = output_dir / "graph.cbor.zst"
    raw_size, compressed_size = builder.write_compressed(graph_path, corpus_sha=corpus_sha)
    stats.graph_raw_bytes = raw_size
    stats.graph_compressed_bytes = compressed_size
    stats.graph_seconds = time.monotonic() - t_start
    logger.info(
        "Graph written: %d edges, raw %.1f Mo, zstd %.1f Mo (ratio %.1fx), %.1fs",
        builder.n_edges, raw_size / 1e6, compressed_size / 1e6,
        raw_size / max(1, compressed_size), stats.graph_seconds,
    )
    # Save edges for PageRank without re-reading
    return builder._edges  # type: ignore[return-value]


def build_pagerank(
    *,
    output_dir: Path,
    n_vertices: int,
    edges: list[tuple[int, int]],
    corpus_sha: bytes,
    stats: BuildStats,
) -> None:
    t_start = time.monotonic()
    result = compute_pagerank(
        n_vertices=n_vertices,
        edges=edges,
        damping=DAMPING_PAGERANK,
        max_iter=MAX_ITER_PAGERANK,
    )
    pr_path = output_dir / "pagerank.f32"
    stats.pagerank_bytes = write_pagerank_f32(
        pr_path,
        scores=result.scores,
        damping=result.damping,
        n_iter_used=result.n_iter_used,
        corpus_sha=corpus_sha,
    )
    stats.pagerank_seconds = time.monotonic() - t_start
    logger.info(
        "PageRank written: %d scores, converged=%s, %.1f Ko, %.1fs",
        n_vertices, result.converged, stats.pagerank_bytes / 1e3, stats.pagerank_seconds,
    )


def write_manifest(output_dir: Path, stats: BuildStats, args: argparse.Namespace) -> None:
    manifest = {
        "schema_version": 1,
        "sprint": "K-1",
        "build_date": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model_name": args.model,
        "seed": args.seed,
        "short_bits": args.short_bits,
        "long_bits": args.long_bits,
        "damping": DAMPING_PAGERANK,
        "max_iter_pagerank": MAX_ITER_PAGERANK,
        "n_articles": stats.n_articles,
        "n_edges": stats.n_edges,
        "limit_applied": args.limit,
        "files": {
            "sigs_mrl.bin": {"bytes": stats.sigs_bin_bytes, "sha256": stats.sha_sigs_bin},
            "sigs_mrl.index.cbor": {"bytes": stats.sigs_index_bytes, "sha256": stats.sha_sigs_index},
            "graph.cbor.zst": {"bytes": stats.graph_compressed_bytes, "sha256": stats.sha_graph},
            "pagerank.f32": {"bytes": stats.pagerank_bytes, "sha256": stats.sha_pagerank},
        },
        "source": {
            "db_path": str(args.db),
            "sha256": stats.sha_legi_sqlite,
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))


def write_build_report(output_dir: Path, stats: BuildStats, args: argparse.Namespace) -> None:
    report = {
        "stats": asdict(stats),
        "args": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "compression_ratio_vs_legi_sqlite": (
            args.legi_size_bytes / max(1, stats.sigs_bin_bytes + stats.sigs_index_bytes
                                        + stats.graph_compressed_bytes + stats.pagerank_bytes)
            if getattr(args, "legi_size_bytes", 0) else None
        ),
    }
    (output_dir / "build_report.json").write_text(json.dumps(report, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sprint K-1 — build KB artifacts (sigs, graph, pagerank)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Path to legi.sqlite")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory")
    p.add_argument("--model", type=str, default=MODEL_NAME, help="sentence-transformers model")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Embedding batch size")
    p.add_argument("--limit", type=int, default=None, help="Cap articles processed (smoke tests)")
    p.add_argument("--auto-download", action="store_true",
                   help="Authorize model download (2,2 Go BGE-M3, ~80 Mo MiniLM)")
    p.add_argument("--device", type=str, default=None, help="torch device (mps/cpu/cuda)")
    p.add_argument("--short-bits", type=int, default=SHORT_BITS,
                   help=f"Short signature bits (default {SHORT_BITS})")
    p.add_argument("--long-bits", type=int, default=LONG_BITS,
                   help=f"Long signature bits (default {LONG_BITS})")
    p.add_argument("--log-level", type=str, default="INFO")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    check_python_version()

    db_path: Path = args.db
    if not db_path.exists():
        logger.error("DB not found: %s", db_path)
        return 2
    output_dir: Path = args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    args.legi_size_bytes = db_path.stat().st_size
    logger.info("legi.sqlite size: %.1f Go", args.legi_size_bytes / 1e9)

    t0 = time.monotonic()
    stats = BuildStats()
    logger.info("SHA-256 of legi.sqlite (may take 30-60s for 4,4 Go)...")
    stats.sha_legi_sqlite = sha256_file(db_path)
    corpus_sha = bytes.fromhex(stats.sha_legi_sqlite)
    logger.info("legi.sqlite SHA-256 = %s", stats.sha_legi_sqlite)

    expected_dim = expected_dim_for_model(args.model)
    if args.long_bits > expected_dim:
        logger.warning(
            "Requested long_bits=%d > model dim=%d. Auto-capping long_bits to %d.",
            args.long_bits, expected_dim, expected_dim,
        )
        args.long_bits = expected_dim
    if args.long_bits % 8 != 0:
        raise SystemExit(f"long_bits {args.long_bits} must be multiple of 8")
    if args.short_bits > args.long_bits:
        raise SystemExit(f"short_bits {args.short_bits} > long_bits {args.long_bits}")

    n_articles = count_articles_vigueur(db_path, limit=args.limit)
    logger.info("Articles VIGUEUR to process: %d", n_articles)

    embedder = Embedder(EmbedderConfig(
        model_name=args.model,
        seed=args.seed,
        batch_size=args.batch_size,
        device=args.device,
        auto_download=args.auto_download,
    ))

    article_to_row, row_to_meta = build_signatures(
        db_path=db_path,
        output_dir=output_dir,
        embedder=embedder,
        n_articles=n_articles,
        corpus_sha=corpus_sha,
        stats=stats,
        limit=args.limit,
        short_bits=args.short_bits,
        long_bits=args.long_bits,
    )

    edges = build_graph(  # type: ignore[assignment]
        db_path=db_path,
        output_dir=output_dir,
        article_to_row=article_to_row,
        row_to_meta=row_to_meta,
        corpus_sha=corpus_sha,
        stats=stats,
        limit=args.limit,
    )

    build_pagerank(
        output_dir=output_dir,
        n_vertices=len(article_to_row),
        edges=edges,
        corpus_sha=corpus_sha,
        stats=stats,
    )

    stats.sha_sigs_bin = sha256_file(output_dir / "sigs_mrl.bin")
    stats.sha_sigs_index = sha256_file(output_dir / "sigs_mrl.index.cbor")
    stats.sha_graph = sha256_file(output_dir / "graph.cbor.zst")
    stats.sha_pagerank = sha256_file(output_dir / "pagerank.f32")

    stats.total_seconds = time.monotonic() - t0

    write_manifest(output_dir, stats, args)
    write_build_report(output_dir, stats, args)

    total_artifacts = (
        stats.sigs_bin_bytes + stats.sigs_index_bytes
        + stats.graph_compressed_bytes + stats.pagerank_bytes
    )
    ratio = args.legi_size_bytes / max(1, total_artifacts)
    logger.info("===== BUILD COMPLETE =====")
    logger.info("Articles: %d | Edges: %d | Unresolved refs: %d",
                stats.n_articles, stats.n_edges, stats.n_refs_unresolved)
    logger.info("Total artifacts: %.1f Mo (compression vs legi.sqlite: %.1fx)",
                total_artifacts / 1e6, ratio)
    logger.info("Wall time: %.1fs", stats.total_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
