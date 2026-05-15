"""sig_writer — sérialisation du format binaire sigs_mrl.bin + index CBOR.

Format binaire little-endian :
    [magic       :  8 bytes] = b"BEAUMEK1"
    [version     :  1 byte ] = 0x01
    [reserved    :  3 bytes] = 0x00
    [short_bits  :  2 bytes uint16]
    [long_bits   :  2 bytes uint16]
    [n_articles  :  4 bytes uint32]
    [model_name  : 64 bytes utf-8 NUL-padded]
    [seed        :  8 bytes uint64]
    [corpus_sha  : 32 bytes]
    [body        : N × (short_bytes + long_bytes)]

Total header : 124 bytes. Body : N × 136 bytes (pour 64+1024 bits).

L'écriture est streaming : on ouvre le fichier, on écrit le header, puis on
append les signatures au fur et à mesure que les embeddings sont calculés.
Permet de checkpoint et de rester en RAM bornée même sur 672k articles.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO

import cbor2
import numpy as np

from lucie_v1_standalone.knowledge_legifrance.kb_compact.constants import (
    ARTIFACT_VERSION,
    LONG_BITS,
    LONG_BYTES,
    MAGIC_SIGS,
    MODEL_NAME_HEADER_LEN,
    SHA256_LEN,
    SHORT_BITS,
    SHORT_BYTES,
    SIG_BYTES_PER_ARTICLE,
)

HEADER_LEN: int = 8 + 1 + 3 + 2 + 2 + 4 + MODEL_NAME_HEADER_LEN + 8 + SHA256_LEN


def _pack_header(
    *,
    short_bits: int,
    long_bits: int,
    n_articles: int,
    model_name: str,
    seed: int,
    corpus_sha: bytes,
) -> bytes:
    if len(corpus_sha) != SHA256_LEN:
        raise ValueError(f"corpus_sha must be {SHA256_LEN} bytes, got {len(corpus_sha)}")
    model_bytes = model_name.encode("utf-8")
    if len(model_bytes) > MODEL_NAME_HEADER_LEN:
        raise ValueError(
            f"model_name too long: {len(model_bytes)} bytes > {MODEL_NAME_HEADER_LEN}"
        )
    model_padded = model_bytes.ljust(MODEL_NAME_HEADER_LEN, b"\x00")
    return (
        MAGIC_SIGS
        + bytes([ARTIFACT_VERSION])
        + b"\x00\x00\x00"
        + struct.pack("<H", short_bits)
        + struct.pack("<H", long_bits)
        + struct.pack("<I", n_articles)
        + model_padded
        + struct.pack("<Q", seed)
        + corpus_sha
    )


class SigBinaryWriter:
    """Writer streaming pour sigs_mrl.bin.

    Usage:
        with SigBinaryWriter(path, n_articles=672352, model_name="BAAI/bge-m3",
                             seed=42, corpus_sha=sha) as w:
            for batch_short, batch_long in pairs:
                w.append_batch(batch_short, batch_long)
    """

    def __init__(
        self,
        path: Path,
        *,
        n_articles: int,
        model_name: str,
        seed: int,
        corpus_sha: bytes,
        short_bits: int = SHORT_BITS,
        long_bits: int = LONG_BITS,
    ) -> None:
        self.path = Path(path)
        self.n_articles = n_articles
        self.model_name = model_name
        self.seed = seed
        self.corpus_sha = corpus_sha
        self.short_bits = short_bits
        self.long_bits = long_bits
        self._fh: BinaryIO | None = None
        self._n_written = 0

    def __enter__(self) -> "SigBinaryWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "wb")
        header = _pack_header(
            short_bits=self.short_bits,
            long_bits=self.long_bits,
            n_articles=self.n_articles,
            model_name=self.model_name,
            seed=self.seed,
            corpus_sha=self.corpus_sha,
        )
        self._fh.write(header)
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def append_batch(self, sigs_short: np.ndarray, sigs_long: np.ndarray) -> None:
        if self._fh is None:
            raise RuntimeError("Writer not opened (use 'with' statement)")
        expected_short_bytes = self.short_bits // 8
        expected_long_bytes = self.long_bits // 8
        if sigs_short.shape[1] != expected_short_bytes:
            raise ValueError(
                f"sigs_short width {sigs_short.shape[1]} != {expected_short_bytes}"
            )
        if sigs_long.shape[1] != expected_long_bytes:
            raise ValueError(
                f"sigs_long width {sigs_long.shape[1]} != {expected_long_bytes}"
            )
        if sigs_short.shape[0] != sigs_long.shape[0]:
            raise ValueError("sigs_short and sigs_long row count mismatch")

        n = sigs_short.shape[0]
        interleaved = np.empty((n, expected_short_bytes + expected_long_bytes), dtype=np.uint8)
        interleaved[:, :expected_short_bytes] = sigs_short
        interleaved[:, expected_short_bytes:] = sigs_long
        self._fh.write(interleaved.tobytes(order="C"))
        self._n_written += n

    @property
    def n_written(self) -> int:
        return self._n_written


def write_index_cbor(
    path: Path,
    *,
    article_to_row: dict[str, int],
    corpus_sha: bytes,
) -> int:
    """Écrit le fichier sigs_mrl.index.cbor mappant article_id ↔ row index.

    Returns:
        Taille du fichier en octets.
    """
    if len(corpus_sha) != SHA256_LEN:
        raise ValueError(f"corpus_sha must be {SHA256_LEN} bytes")

    row_to_article = [""] * len(article_to_row)
    for article_id, row in article_to_row.items():
        if not 0 <= row < len(row_to_article):
            raise ValueError(f"row index {row} out of bounds for {article_id}")
        row_to_article[row] = article_id

    if any(not aid for aid in row_to_article):
        raise ValueError("article_to_row has gaps (missing row indices)")

    index = {
        "version": ARTIFACT_VERSION,
        "magic": "BEAUMEK1",
        "corpus_sha": corpus_sha.hex(),
        "article_to_row": article_to_row,
        "row_to_article": row_to_article,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = cbor2.dumps(index)
    path.write_bytes(payload)
    return len(payload)
