"""Test GraphBuilder + RefResolver + load/save."""

from __future__ import annotations

import hashlib
from pathlib import Path

from lucie_v1_standalone.knowledge_legifrance.kb_compact.graph_writer import (
    GraphBuilder,
    RefResolver,
    load_graph,
)


def _sha() -> bytes:
    return hashlib.sha256(b"corpus-test").digest()


def test_resolver_single_candidate() -> None:
    r = RefResolver()
    r.add_article(row=0, num="L1233-3", code_cid="LEGITEXT000006072050")
    r.add_article(row=1, num="L1234-5", code_cid="LEGITEXT000006072050")

    assert r.resolve("L", "1233-3") == 0
    assert r.resolve("L", "1234-5") == 1
    assert r.resolve("L", "9999-99") is None


def test_resolver_multiple_candidates_prefers_same_code() -> None:
    r = RefResolver()
    r.add_article(row=0, num="L121-1", code_cid="CODE_A")
    r.add_article(row=1, num="L121-1", code_cid="CODE_B")

    # Source from CODE_A should resolve to row 0
    assert r.resolve("L", "121-1", src_code_cid="CODE_A") == 0
    assert r.resolve("L", "121-1", src_code_cid="CODE_B") == 1
    # Without context: first candidate
    assert r.resolve("L", "121-1") == 0


def test_resolver_canonicalization() -> None:
    r = RefResolver()
    r.add_article(row=0, num="L1233-3", code_cid="X")
    # Vérifie qu'on accepte les variantes "L. 1233-3", "L1233-3", "l.1233-3"
    assert r.resolve("L", "1233-3") == 0


def test_graph_builder_simple() -> None:
    r = RefResolver()
    r.add_article(0, "L1-1", "X")
    r.add_article(1, "L2-2", "X")
    r.add_article(2, "L3-3", "X")

    b = GraphBuilder(n_vertices=3)
    b.add_article_edges(0, "Voir article L.2-2 et L.3-3", "X", r)
    b.add_article_edges(1, "selon l'article L.3-3", "X", r)
    b.add_article_edges(2, "fin de la chaîne", "X", r)

    assert b.n_edges == 3
    assert (0, 1) in list(b.iter_edges())
    assert (0, 2) in list(b.iter_edges())
    assert (1, 2) in list(b.iter_edges())
    assert b.unresolved_count == 0


def test_graph_builder_unresolved_counted() -> None:
    r = RefResolver()
    r.add_article(0, "L1-1", "X")

    b = GraphBuilder(n_vertices=1)
    n_added = b.add_article_edges(
        0, "voir L.9999-9 et selon l'article L.8-8", "X", r
    )
    assert n_added == 0
    assert b.unresolved_count == 2


def test_graph_builder_skips_self_loops() -> None:
    r = RefResolver()
    r.add_article(0, "L1-1", "X")
    b = GraphBuilder(n_vertices=1)
    b.add_article_edges(0, "Cf. l'article L.1-1 lui-même", "X", r)
    assert b.n_edges == 0


def test_graph_round_trip(tmp_path: Path) -> None:
    r = RefResolver()
    r.add_article(0, "L1-1", "X")
    r.add_article(1, "L2-2", "X")
    b = GraphBuilder(n_vertices=2)
    b.add_article_edges(0, "voir L.2-2", "X", r)

    out = tmp_path / "graph.cbor.zst"
    raw_size, comp_size = b.write_compressed(out, _sha())
    assert comp_size > 0
    assert raw_size > 0

    loaded = load_graph(out)
    assert loaded["n_vertices"] == 2
    assert loaded["n_edges"] == 1
    assert loaded["edges"] == [[0, 1]]
    assert loaded["magic"] == "BEAUMEK1G"
    assert loaded["corpus_sha"] == _sha().hex()
