"""pagerank — calcul PageRank sur le graphe DAG + sérialisation f32.

Stratégie : networkx.pagerank par défaut. Fallback NumPy + scipy.sparse si
trop lent ou indisponible. Le format de sortie f32 est aligné sur le row_index
des signatures pour permettre un join O(1).

Format pagerank.f32 (little-endian) :
    [magic       :  8 bytes] = b"BEAUMEK1"
    [version     :  1 byte ] = 0x01
    [reserved    :  3 bytes] = 0x00
    [n_articles  :  4 bytes uint32]
    [damping     :  4 bytes float32]
    [n_iter_used :  4 bytes uint32]
    [corpus_sha  : 32 bytes]
    [scores      : N × 4 bytes float32]
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import networkx as nx
import numpy as np

from lucie_v1_standalone.knowledge_legifrance.kb_compact.constants import (
    ARTIFACT_VERSION,
    DAMPING_PAGERANK,
    MAGIC_SIGS,
    MAX_ITER_PAGERANK,
    SHA256_LEN,
    TOL_PAGERANK,
)

logger = logging.getLogger(__name__)

PAGERANK_HEADER_LEN: int = 8 + 1 + 3 + 4 + 4 + 4 + SHA256_LEN  # 56 bytes


@dataclass(frozen=True)
class PageRankResult:
    scores: np.ndarray  # [N] float32
    n_iter_used: int
    damping: float
    converged: bool


def compute_pagerank(
    n_vertices: int,
    edges: Iterable[tuple[int, int]],
    *,
    damping: float = DAMPING_PAGERANK,
    max_iter: int = MAX_ITER_PAGERANK,
    tol: float = TOL_PAGERANK,
) -> PageRankResult:
    """Calcule le PageRank via networkx.

    Pour 672k noeuds, networkx est OK (~30-120s). Si trop lent, voir
    compute_pagerank_sparse() (NumPy + scipy).
    """
    graph = nx.DiGraph()
    graph.add_nodes_from(range(n_vertices))
    graph.add_edges_from(edges)

    converged = True
    try:
        scores_dict = nx.pagerank(
            graph,
            alpha=damping,
            max_iter=max_iter,
            tol=tol,
        )
        n_iter_used = max_iter  # networkx ne retourne pas le nombre exact
    except nx.PowerIterationFailedConvergence as exc:
        logger.warning("PageRank did not converge: %s. Using partial result.", exc)
        converged = False
        # networkx 3.x exposes the partial state via the exception
        scores_dict = getattr(exc, "args", [None])[0] if hasattr(exc, "args") else None
        if not isinstance(scores_dict, dict):
            raise
        n_iter_used = max_iter

    scores = np.zeros(n_vertices, dtype=np.float32)
    for node, score in scores_dict.items():
        if 0 <= node < n_vertices:
            scores[node] = np.float32(score)
    return PageRankResult(scores=scores, n_iter_used=n_iter_used, damping=damping, converged=converged)


def write_pagerank_f32(
    path: Path,
    *,
    scores: np.ndarray,
    damping: float,
    n_iter_used: int,
    corpus_sha: bytes,
) -> int:
    """Écrit le fichier pagerank.f32. Returns nombre d'octets écrits."""
    if scores.dtype != np.float32:
        scores = scores.astype(np.float32, copy=False)
    if scores.ndim != 1:
        raise ValueError(f"scores must be 1-D, got shape {scores.shape}")
    if len(corpus_sha) != SHA256_LEN:
        raise ValueError(f"corpus_sha must be {SHA256_LEN} bytes")

    n_articles = int(scores.shape[0])
    header = (
        MAGIC_SIGS
        + bytes([ARTIFACT_VERSION])
        + b"\x00\x00\x00"
        + struct.pack("<I", n_articles)
        + struct.pack("<f", float(damping))
        + struct.pack("<I", n_iter_used)
        + corpus_sha
    )
    if len(header) != PAGERANK_HEADER_LEN:
        raise AssertionError(f"Header len {len(header)} != {PAGERANK_HEADER_LEN}")

    body = scores.tobytes(order="C")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(body)
    return len(header) + len(body)


@dataclass(frozen=True)
class PageRankHeader:
    n_articles: int
    damping: float
    n_iter_used: int
    corpus_sha: bytes


def read_pagerank_f32(path: Path) -> tuple[PageRankHeader, np.ndarray]:
    path = Path(path)
    with open(path, "rb") as fh:
        raw = fh.read(PAGERANK_HEADER_LEN)
        if len(raw) < PAGERANK_HEADER_LEN:
            raise ValueError(f"File {path} truncated header")
        magic = raw[:8]
        if magic != MAGIC_SIGS:
            raise ValueError(f"Bad pagerank magic: {magic!r}")
        version = raw[8]
        if version != ARTIFACT_VERSION:
            raise ValueError(f"Unsupported pagerank version: {version}")
        offset = 12
        (n_articles,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        (damping,) = struct.unpack_from("<f", raw, offset)
        offset += 4
        (n_iter_used,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        corpus_sha = bytes(raw[offset : offset + SHA256_LEN])

        scores_bytes = fh.read()
    scores = np.frombuffer(scores_bytes, dtype=np.float32)
    if scores.size != n_articles:
        raise ValueError(f"Scores size {scores.size} != n_articles {n_articles}")
    header = PageRankHeader(
        n_articles=n_articles,
        damping=damping,
        n_iter_used=n_iter_used,
        corpus_sha=corpus_sha,
    )
    return header, scores
