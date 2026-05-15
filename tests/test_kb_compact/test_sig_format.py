"""Test round-trip écriture/lecture du format binaire sigs_mrl.bin + index."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from lucie_v1_standalone.knowledge_legifrance.kb_compact.constants import (
    LONG_BITS,
    LONG_BYTES,
    MAGIC_SIGS,
    SHORT_BITS,
    SHORT_BYTES,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.sig_reader import (
    load_index,
    load_sigs,
    read_header,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.sig_writer import (
    SigBinaryWriter,
    write_index_cbor,
)


def _make_corpus_sha() -> bytes:
    return hashlib.sha256(b"test-corpus").digest()


def _rand_sigs(n: int, byte_width: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(n, byte_width), dtype=np.uint8)


def test_header_round_trip(tmp_path: Path) -> None:
    sigs_path = tmp_path / "sigs.bin"
    corpus_sha = _make_corpus_sha()
    n = 100
    short = _rand_sigs(n, SHORT_BYTES, seed=1)
    long_ = _rand_sigs(n, LONG_BYTES, seed=2)

    with SigBinaryWriter(
        sigs_path,
        n_articles=n,
        model_name="BAAI/bge-m3",
        seed=42,
        corpus_sha=corpus_sha,
    ) as w:
        w.append_batch(short, long_)

    header = read_header(sigs_path)
    assert header.magic == MAGIC_SIGS
    assert header.version == 1
    assert header.short_bits == SHORT_BITS
    assert header.long_bits == LONG_BITS
    assert header.n_articles == n
    assert header.model_name == "BAAI/bge-m3"
    assert header.seed == 42
    assert header.corpus_sha == corpus_sha


def test_body_round_trip(tmp_path: Path) -> None:
    sigs_path = tmp_path / "sigs.bin"
    corpus_sha = _make_corpus_sha()
    n = 250
    short = _rand_sigs(n, SHORT_BYTES, seed=3)
    long_ = _rand_sigs(n, LONG_BYTES, seed=4)

    with SigBinaryWriter(
        sigs_path,
        n_articles=n,
        model_name="test-model",
        seed=7,
        corpus_sha=corpus_sha,
    ) as w:
        w.append_batch(short[: n // 2], long_[: n // 2])
        w.append_batch(short[n // 2 :], long_[n // 2 :])

    _hdr, loaded_short, loaded_long = load_sigs(sigs_path)
    np.testing.assert_array_equal(loaded_short, short)
    np.testing.assert_array_equal(loaded_long, long_)


def test_index_round_trip(tmp_path: Path) -> None:
    index_path = tmp_path / "index.cbor"
    corpus_sha = _make_corpus_sha()
    article_to_row = {f"LEGIARTI{i:012d}": i for i in range(50)}
    written = write_index_cbor(index_path, article_to_row=article_to_row, corpus_sha=corpus_sha)
    assert written > 0

    loaded = load_index(index_path)
    assert loaded["version"] == 1
    assert loaded["magic"] == "BEAUMEK1"
    assert loaded["corpus_sha"] == corpus_sha.hex()
    assert loaded["article_to_row"] == article_to_row
    assert loaded["row_to_article"][0] == "LEGIARTI000000000000"
    assert loaded["row_to_article"][49] == "LEGIARTI000000000049"


def test_bad_magic_rejected(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.bin"
    bad_path.write_bytes(b"NOTGOOD\x00" + b"\x00" * 200)
    with pytest.raises(ValueError, match="magic"):
        read_header(bad_path)


def test_index_with_gap_rejected(tmp_path: Path) -> None:
    """Si article_to_row a un row index manquant, doit lever.

    Le code détecte d'abord les indices hors bornes (out of bounds) avant
    de chercher les trous (gaps). Les deux sont des cas d'erreur valides.
    """
    with pytest.raises(ValueError, match="(gap|out of bounds)"):
        write_index_cbor(
            tmp_path / "bad_index.cbor",
            article_to_row={"A": 0, "C": 2},  # B missing
            corpus_sha=_make_corpus_sha(),
        )


def test_model_name_too_long_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="too long"):
        with SigBinaryWriter(
            tmp_path / "x.bin",
            n_articles=1,
            model_name="x" * 200,
            seed=0,
            corpus_sha=_make_corpus_sha(),
        ):
            pass
