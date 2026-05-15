"""sig_reader — lecture du format binaire sigs_mrl.bin + index CBOR.

Utile pour :
- Le bench recall@10 (charge les signatures pour construire HNSW)
- Les tests unitaires (round-trip writer/reader)
- Le futur K-2 (consommation côté client)

API minimale et explicite : pas de cache, l'utilisateur gère la mémoire.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cbor2
import numpy as np

from lucie_v1_standalone.knowledge_legifrance.kb_compact.constants import (
    ARTIFACT_VERSION,
    MAGIC_SIGS,
    MODEL_NAME_HEADER_LEN,
    SHA256_LEN,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.sig_writer import HEADER_LEN


@dataclass(frozen=True)
class SigHeader:
    magic: bytes
    version: int
    short_bits: int
    long_bits: int
    n_articles: int
    model_name: str
    seed: int
    corpus_sha: bytes

    @property
    def short_bytes(self) -> int:
        return self.short_bits // 8

    @property
    def long_bytes(self) -> int:
        return self.long_bits // 8

    @property
    def row_bytes(self) -> int:
        return self.short_bytes + self.long_bytes


def read_header(path: Path) -> SigHeader:
    path = Path(path)
    with open(path, "rb") as fh:
        raw = fh.read(HEADER_LEN)
    if len(raw) < HEADER_LEN:
        raise ValueError(
            f"File {path} too short: {len(raw)} bytes, expected ≥ {HEADER_LEN}"
        )
    return _parse_header(raw)


def _parse_header(raw: bytes) -> SigHeader:
    magic = raw[:8]
    if magic != MAGIC_SIGS:
        raise ValueError(f"Bad magic: {magic!r} != {MAGIC_SIGS!r}")
    version = raw[8]
    if version != ARTIFACT_VERSION:
        raise ValueError(f"Unsupported version: {version} (expected {ARTIFACT_VERSION})")
    # raw[9:12] = reserved
    offset = 12
    (short_bits,) = struct.unpack_from("<H", raw, offset)
    offset += 2
    (long_bits,) = struct.unpack_from("<H", raw, offset)
    offset += 2
    (n_articles,) = struct.unpack_from("<I", raw, offset)
    offset += 4
    model_padded = raw[offset : offset + MODEL_NAME_HEADER_LEN]
    model_name = model_padded.rstrip(b"\x00").decode("utf-8")
    offset += MODEL_NAME_HEADER_LEN
    (seed,) = struct.unpack_from("<Q", raw, offset)
    offset += 8
    corpus_sha = bytes(raw[offset : offset + SHA256_LEN])
    return SigHeader(
        magic=bytes(magic),
        version=version,
        short_bits=short_bits,
        long_bits=long_bits,
        n_articles=n_articles,
        model_name=model_name,
        seed=seed,
        corpus_sha=corpus_sha,
    )


def load_sigs(path: Path) -> tuple[SigHeader, np.ndarray, np.ndarray]:
    """Charge les signatures court et long en RAM.

    Returns:
        (header, sigs_short [N, short_bytes] uint8, sigs_long [N, long_bytes] uint8)
    """
    path = Path(path)
    with open(path, "rb") as fh:
        header_bytes = fh.read(HEADER_LEN)
        header = _parse_header(header_bytes)
        body = np.frombuffer(fh.read(), dtype=np.uint8)

    expected_size = header.n_articles * header.row_bytes
    if body.size != expected_size:
        raise ValueError(
            f"Body size {body.size} != expected {expected_size} "
            f"(n_articles={header.n_articles}, row_bytes={header.row_bytes})"
        )
    body = body.reshape(header.n_articles, header.row_bytes)
    sigs_short = np.ascontiguousarray(body[:, : header.short_bytes])
    sigs_long = np.ascontiguousarray(body[:, header.short_bytes :])
    return header, sigs_short, sigs_long


def load_index(path: Path) -> dict[str, Any]:
    """Charge l'index CBOR (article_id ↔ row)."""
    path = Path(path)
    payload = path.read_bytes()
    index: dict[str, Any] = cbor2.loads(payload)
    if index.get("magic") != "BEAUMEK1":
        raise ValueError(f"Bad magic in index: {index.get('magic')!r}")
    if index.get("version") != ARTIFACT_VERSION:
        raise ValueError(f"Unsupported index version: {index.get('version')}")
    return index
