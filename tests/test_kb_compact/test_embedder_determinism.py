"""Test déterminisme de l'embedder + quantization binaire.

Le test du modèle complet (BGE-M3 ou MiniLM) est skippé si le modèle n'est pas
en cache HuggingFace — éviter télécharger 2 Go en CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from lucie_v1_standalone.knowledge_legifrance.kb_compact.constants import (
    EMBED_DIM_BGE_M3,
    EMBED_DIM_MINILM,
    LONG_BITS,
    SHORT_BITS,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.embedder import (
    Embedder,
    EmbedderConfig,
    binary_quantize,
    expected_dim_for_model,
)


def test_expected_dim_known_models() -> None:
    assert expected_dim_for_model("BAAI/bge-m3") == EMBED_DIM_BGE_M3
    assert expected_dim_for_model("sentence-transformers/all-MiniLM-L6-v2") == EMBED_DIM_MINILM


def test_expected_dim_unknown_raises() -> None:
    with pytest.raises(ValueError):
        expected_dim_for_model("unknown/model")


def test_binary_quantize_shapes() -> None:
    embs = np.random.RandomState(0).randn(10, 1024).astype(np.float32)
    sig_short = binary_quantize(embs, n_bits=SHORT_BITS)
    sig_long = binary_quantize(embs, n_bits=LONG_BITS)
    assert sig_short.shape == (10, SHORT_BITS // 8)
    assert sig_long.shape == (10, LONG_BITS // 8)
    assert sig_short.dtype == np.uint8
    assert sig_long.dtype == np.uint8


def test_binary_quantize_deterministic() -> None:
    embs = np.random.RandomState(0).randn(5, 256).astype(np.float32)
    a = binary_quantize(embs, n_bits=64)
    b = binary_quantize(embs, n_bits=64)
    np.testing.assert_array_equal(a, b)


def test_binary_quantize_positive_threshold() -> None:
    # All positives → all 1s (0xFF per byte)
    embs = np.ones((3, 64), dtype=np.float32)
    packed = binary_quantize(embs, n_bits=64)
    assert np.all(packed == 0xFF)

    # All non-positives → all 0s
    embs2 = np.zeros((3, 64), dtype=np.float32) - 1.0
    packed2 = binary_quantize(embs2, n_bits=64)
    assert np.all(packed2 == 0x00)


def test_binary_quantize_rejects_non_multiple_8() -> None:
    embs = np.random.RandomState(0).randn(2, 64).astype(np.float32)
    with pytest.raises(ValueError, match="multiple of 8"):
        binary_quantize(embs, n_bits=63)


def test_binary_quantize_rejects_dim_overflow() -> None:
    embs = np.random.RandomState(0).randn(2, 64).astype(np.float32)
    with pytest.raises(ValueError, match=">"):
        binary_quantize(embs, n_bits=128)


def _model_in_cache(name: str) -> bool:
    cache = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"
    return (cache / ("models--" + name.replace("/", "--"))).exists()


@pytest.mark.skipif(
    not _model_in_cache("sentence-transformers/all-MiniLM-L6-v2"),
    reason="MiniLM not in HF cache; skipping live embedding test",
)
def test_embedder_seed_reproducibility() -> None:
    cfg = EmbedderConfig(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        seed=42,
        batch_size=4,
        auto_download=False,
    )
    emb1 = Embedder(cfg)
    emb2 = Embedder(cfg)
    texts = ["test article", "deuxième article", "troisième"]
    v1 = next(emb1.embed_batched(texts))
    v2 = next(emb2.embed_batched(texts))
    np.testing.assert_allclose(v1, v2, atol=1e-5)


def test_embedder_refuses_without_auto_download() -> None:
    """Si modèle absent du cache et auto_download=False, doit lever explicitement."""
    cfg = EmbedderConfig(
        model_name="non-existent/totally-not-real-model-xyz-99999",
        auto_download=False,
    )
    emb = Embedder(cfg)
    with pytest.raises(RuntimeError, match="auto_download"):
        emb._load()
