"""Test PageRank computation + sérialisation f32."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import networkx as nx
import numpy as np

from lucie_v1_standalone.knowledge_legifrance.kb_compact.pagerank import (
    compute_pagerank,
    read_pagerank_f32,
    write_pagerank_f32,
)


def _sha() -> bytes:
    return hashlib.sha256(b"pr-test").digest()


def test_pagerank_three_nodes() -> None:
    # Classic graph A -> B -> C, A -> C
    edges = [(0, 1), (1, 2), (0, 2)]
    result = compute_pagerank(n_vertices=3, edges=edges)
    assert result.scores.shape == (3,)
    assert result.scores.dtype == np.float32
    # Sum approx 1 (PageRank stochastic)
    assert abs(result.scores.sum() - 1.0) < 1e-3
    # Node 2 (sink) should have highest score
    assert result.scores[2] > result.scores[0]
    assert result.scores[2] > result.scores[1]


def test_pagerank_matches_networkx() -> None:
    edges = [(0, 1), (1, 2), (2, 0), (1, 3), (3, 1)]
    result = compute_pagerank(n_vertices=4, edges=edges)

    g = nx.DiGraph()
    g.add_nodes_from(range(4))
    g.add_edges_from(edges)
    ref = nx.pagerank(g, alpha=0.85, max_iter=50, tol=1e-6)
    for node in range(4):
        assert abs(float(result.scores[node]) - ref[node]) < 1e-4


def test_pagerank_empty_graph() -> None:
    """Pas d'arêtes : score uniforme 1/N."""
    result = compute_pagerank(n_vertices=5, edges=[])
    for s in result.scores:
        assert abs(float(s) - 0.2) < 1e-4


def test_pagerank_f32_round_trip(tmp_path: Path) -> None:
    scores = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    path = tmp_path / "pr.f32"
    written = write_pagerank_f32(
        path,
        scores=scores,
        damping=0.85,
        n_iter_used=50,
        corpus_sha=_sha(),
    )
    assert written > 0

    header, loaded = read_pagerank_f32(path)
    assert header.n_articles == 4
    assert math.isclose(header.damping, 0.85, abs_tol=1e-6)
    assert header.n_iter_used == 50
    assert header.corpus_sha == _sha()
    np.testing.assert_array_equal(loaded, scores)
