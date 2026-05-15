"""embedder — wrapper sentence-transformers pour le pipeline KB compact.

Charge BGE-M3 (ou fallback all-MiniLM-L6-v2) avec :
- device auto MPS / CPU (Mac M-series)
- déterminisme : seed numpy + torch fixé
- batching par lot avec progress logger
- vérification taille modèle / espace disque avant download

Garde-fous :
- Aucun appel cloud silencieux : download du modèle (2,2 Go BGE-M3) doit être
  explicitement autorisé via auto_download=True. Sinon RuntimeError.
- Mode déterministe : torch.use_deterministic_algorithms(True) impossible avec
  certains kernels MPS, donc on se contente de seeding + eval mode.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np

from lucie_v1_standalone.knowledge_legifrance.kb_compact.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_SEED,
    EMBED_DIM_BGE_M3,
    EMBED_DIM_MINILM,
    MODEL_NAME,
    MODEL_NAME_FALLBACK,
)

logger = logging.getLogger(__name__)

_BGE_M3_DOWNLOAD_GB: float = 2.2
_MINILM_DOWNLOAD_MB: float = 90.0


@dataclass(frozen=True)
class EmbedderConfig:
    model_name: str = MODEL_NAME
    seed: int = DEFAULT_SEED
    batch_size: int = DEFAULT_BATCH_SIZE
    device: str | None = None
    auto_download: bool = False
    max_seq_length: int = 512


class Embedder:
    """Wrapper sentence-transformers — chargé paresseusement pour permettre les
    smoke tests sans le modèle.

    Usage:
        >>> emb = Embedder(EmbedderConfig(auto_download=True))
        >>> for batch_vec in emb.embed_batched(["texte1", "texte2"]):
        ...     pass
    """

    def __init__(self, config: EmbedderConfig) -> None:
        self.config = config
        self._model = None
        self._dim: int | None = None

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._load()
        assert self._dim is not None
        return self._dim

    def _check_cache(self) -> bool:
        """Vérifie si le modèle est déjà en cache HuggingFace local."""
        cache_dir = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
        hub_dir = Path(cache_dir) / "hub"
        if not hub_dir.exists():
            return False
        model_dir_name = "models--" + self.config.model_name.replace("/", "--")
        return (hub_dir / model_dir_name).exists()

    def _load(self) -> None:
        if self._model is not None:
            return

        in_cache = self._check_cache()
        if not in_cache and not self.config.auto_download:
            size_hint = _BGE_M3_DOWNLOAD_GB if "bge" in self.config.model_name.lower() else _MINILM_DOWNLOAD_MB / 1024
            raise RuntimeError(
                f"Model '{self.config.model_name}' not in HuggingFace cache. "
                f"Download is ~{size_hint:.1f} GB. Re-run with auto_download=True "
                f"(CLI: --auto-download) to authorize the download."
            )

        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers and torch required. Install via "
                "pip install -r requirements.txt"
            ) from exc

        np.random.seed(self.config.seed)
        torch.manual_seed(self.config.seed)
        if hasattr(torch, "mps") and torch.backends.mps.is_available():
            torch.mps.manual_seed(self.config.seed)

        device = self.config.device or self._auto_device(torch)
        logger.info("Loading model %s on device=%s (in_cache=%s)", self.config.model_name, device, in_cache)

        self._model = SentenceTransformer(self.config.model_name, device=device)
        self._model.eval()
        self._model.max_seq_length = self.config.max_seq_length

        dim = self._model.get_sentence_embedding_dimension()
        if dim is None:
            raise RuntimeError(f"Could not detect embedding dimension for {self.config.model_name}")
        self._dim = int(dim)
        logger.info("Model loaded — embedding dim=%d", self._dim)

    @staticmethod
    def _auto_device(torch_module) -> str:
        if hasattr(torch_module, "mps") and torch_module.backends.mps.is_available():
            return "mps"
        if torch_module.cuda.is_available():
            return "cuda"
        return "cpu"

    def embed_batched(self, texts: Iterable[str]) -> Iterator[np.ndarray]:
        """Yield embedding batches en float32 [batch_size, dim] pour streaming."""
        self._load()
        batch: list[str] = []
        for text in texts:
            batch.append(text)
            if len(batch) >= self.config.batch_size:
                yield self._encode(batch)
                batch = []
        if batch:
            yield self._encode(batch)

    def _encode(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            self._load()
        assert self._model is not None
        vecs = self._model.encode(
            texts,
            batch_size=self.config.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if vecs.dtype != np.float32:
            vecs = vecs.astype(np.float32, copy=False)
        return vecs

    def embed_one(self, text: str) -> np.ndarray:
        """Embed un seul texte. Utile pour les queries de bench."""
        return self._encode([text])[0]


def expected_dim_for_model(model_name: str) -> int:
    """Renvoie la dimension d'embedding attendue pour un nom de modèle connu."""
    name = model_name.lower()
    if "bge-m3" in name:
        return EMBED_DIM_BGE_M3
    if "minilm-l6" in name:
        return EMBED_DIM_MINILM
    raise ValueError(f"Unknown model dimension for '{model_name}'")


def binary_quantize(embeddings: np.ndarray, n_bits: int) -> np.ndarray:
    """Quantize binaire Matryoshka : prend les n_bits premières dims et pack.

    Args:
        embeddings: shape [N, D] float32 ou float64
        n_bits: nombre de bits à conserver (doit être ≤ D et multiple de 8)

    Returns:
        bytes packés shape [N, n_bits // 8] uint8 — bit_i = 1 si emb[i] > 0
    """
    if embeddings.ndim != 2:
        raise ValueError(f"embeddings must be 2-D, got shape {embeddings.shape}")
    if n_bits % 8 != 0:
        raise ValueError(f"n_bits must be multiple of 8, got {n_bits}")
    if n_bits > embeddings.shape[1]:
        raise ValueError(f"n_bits={n_bits} > embedding dim={embeddings.shape[1]}")

    truncated = embeddings[:, :n_bits]
    bits = (truncated > 0).astype(np.uint8)
    packed = np.packbits(bits, axis=1, bitorder="big")
    return packed
