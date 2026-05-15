"""Constantes du pipeline KB compact — règle qualité #4 : pas de magic numbers."""

from __future__ import annotations

from typing import Final

ARTIFACT_VERSION: Final[int] = 1
MAGIC_SIGS: Final[bytes] = b"BEAUMEK1"
MAGIC_GRAPH: Final[bytes] = b"BEAUMEK1G"

MODEL_NAME: Final[str] = "BAAI/bge-m3"
MODEL_NAME_FALLBACK: Final[str] = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM_BGE_M3: Final[int] = 1024
EMBED_DIM_MINILM: Final[int] = 384

SHORT_BITS: Final[int] = 64
LONG_BITS: Final[int] = 1024
SHORT_BYTES: Final[int] = SHORT_BITS // 8
LONG_BYTES: Final[int] = LONG_BITS // 8
SIG_BYTES_PER_ARTICLE: Final[int] = SHORT_BYTES + LONG_BYTES

DEFAULT_SEED: Final[int] = 42
DEFAULT_BATCH_SIZE: Final[int] = 32

DAMPING_PAGERANK: Final[float] = 0.85
MAX_ITER_PAGERANK: Final[int] = 50
TOL_PAGERANK: Final[float] = 1e-6

HNSW_M: Final[int] = 16
HNSW_EF_CONSTRUCTION: Final[int] = 200
HNSW_EF_QUERY: Final[int] = 64

DEFAULT_TOP_K: Final[int] = 10
RECALL_THRESHOLD: Final[float] = 0.90

CHECKPOINT_INTERVAL: Final[int] = 10_000

MODEL_NAME_HEADER_LEN: Final[int] = 64
SHA256_LEN: Final[int] = 32

PYTHON_MIN_MAJOR: Final[int] = 3
PYTHON_MIN_MINOR: Final[int] = 11
