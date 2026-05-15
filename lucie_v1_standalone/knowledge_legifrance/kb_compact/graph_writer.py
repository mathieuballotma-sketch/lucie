"""graph_writer — construction du graphe DAG des renvois inter-articles.

Pour chaque article on extrait les références (prefix, num) via refs_extractor,
puis on résout chaque ref vers un article_id concret de la KB. Si plusieurs
candidats (le même num L.1234-1 existe dans plusieurs codes), on garde le
top-match par cohérence de code_cid avec l'article source ; sinon le premier.

Format CBOR de sortie :
    {
        "version": 1,
        "magic": "BEAUMEK1G",
        "corpus_sha": <hex>,
        "n_vertices": N,
        "n_edges": M,
        "edges": [[u32_src, u32_dst], ...],     # row indices
        "unresolved_count": int,
    }

Le fichier est ensuite compressé Zstd pour passer de ~30-80 Mo à ~10-25 Mo.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import cbor2
import zstandard as zstd

from lucie_v1_standalone.knowledge_legifrance.kb_compact.constants import (
    ARTIFACT_VERSION,
    MAGIC_GRAPH,
)
from lucie_v1_standalone.knowledge_legifrance.refs_extractor import extract_refs_extended

logger = logging.getLogger(__name__)


class RefResolver:
    """Résout (prefix, num) → row_index parmi les articles VIGUEUR.

    Construction du dict en mémoire : on indexe les articles par leur num
    canonique. Sur 672k articles VIGUEUR, le dict pèse ~30-50 Mo.
    """

    def __init__(self) -> None:
        self._by_num: dict[str, list[int]] = defaultdict(list)
        self._code_cid_by_row: dict[int, str] = {}
        self._size: int = 0

    def add_article(self, row: int, num: str, code_cid: str) -> None:
        """Ajoute un article au resolver.

        Args:
            row: row index dans sigs_mrl.bin
            num: numéro canonique stocké dans articles.num (ex "L1233-3" sans point)
            code_cid: code Légifrance auquel appartient l'article
        """
        if not num:
            return
        key = _canonicalize(num)
        self._by_num[key].append(row)
        self._code_cid_by_row[row] = code_cid
        self._size += 1

    @property
    def size(self) -> int:
        return self._size

    def resolve(self, prefix: str, num: str, src_code_cid: str | None = None) -> int | None:
        """Renvoie le row index cible, ou None si non résolu.

        Si plusieurs candidats, on préfère celui dont code_cid == src_code_cid.
        """
        key = _canonicalize(f"{prefix}{num}")
        candidates = self._by_num.get(key)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if src_code_cid is not None:
            for row in candidates:
                if self._code_cid_by_row.get(row) == src_code_cid:
                    return row
        return candidates[0]


def _canonicalize(raw: str) -> str:
    """Canonicalise un num d'article pour matching cross-format.

    "L. 1234-1", "l.1234-1", "L1234-1" → "L1234-1".
    """
    return "".join(c for c in raw.upper() if not c.isspace() and c != ".")


class GraphBuilder:
    """Construit le graphe DAG des renvois en streaming.

    Usage:
        resolver = RefResolver()
        for row, (aid, num, code, txt) in enumerate(articles):
            resolver.add_article(row, num, code)

        builder = GraphBuilder(n_vertices=N)
        for row, (aid, num, code, txt) in enumerate(articles):
            builder.add_article_edges(row, txt, code, resolver)
    """

    def __init__(self, n_vertices: int) -> None:
        self.n_vertices = n_vertices
        self._edges: list[tuple[int, int]] = []
        self.unresolved_count: int = 0
        self.resolved_count: int = 0

    def add_article_edges(
        self,
        src_row: int,
        text: str,
        src_code_cid: str | None,
        resolver: RefResolver,
    ) -> int:
        """Ajoute les arêtes sortantes du noeud src_row.

        Returns:
            Nombre d'arêtes ajoutées pour cet article.
        """
        if not text:
            return 0
        refs = extract_refs_extended(text)
        n_added = 0
        for prefix, num in refs:
            dst_row = resolver.resolve(prefix, num, src_code_cid)
            if dst_row is None:
                self.unresolved_count += 1
                continue
            if dst_row == src_row:
                continue
            self._edges.append((src_row, dst_row))
            self.resolved_count += 1
            n_added += 1
        return n_added

    @property
    def n_edges(self) -> int:
        return len(self._edges)

    def serialize_cbor(self, corpus_sha: bytes) -> bytes:
        payload = {
            "version": ARTIFACT_VERSION,
            "magic": MAGIC_GRAPH.decode("ascii"),
            "corpus_sha": corpus_sha.hex(),
            "n_vertices": self.n_vertices,
            "n_edges": self.n_edges,
            "edges": [[u, v] for u, v in self._edges],
            "unresolved_count": self.unresolved_count,
        }
        return cbor2.dumps(payload)

    def write_compressed(self, path: Path, corpus_sha: bytes, level: int = 9) -> tuple[int, int]:
        """Sérialise + compresse Zstd. Returns (raw_size, compressed_size)."""
        raw = self.serialize_cbor(corpus_sha)
        cctx = zstd.ZstdCompressor(level=level)
        compressed = cctx.compress(raw)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(compressed)
        return len(raw), len(compressed)

    def iter_edges(self) -> Iterable[tuple[int, int]]:
        return iter(self._edges)


def load_graph(path: Path) -> dict:
    """Charge un graph.cbor.zst (ou .cbor brut) et renvoie le dict décodé."""
    path = Path(path)
    data = path.read_bytes()
    if path.suffix == ".zst" or data[:4] == b"\x28\xb5\x2f\xfd":
        dctx = zstd.ZstdDecompressor()
        data = dctx.decompress(data)
    payload = cbor2.loads(data)
    expected_magic = MAGIC_GRAPH.decode("ascii")
    if payload.get("magic") != expected_magic:
        raise ValueError(f"Bad graph magic: {payload.get('magic')!r}")
    if payload.get("version") != ARTIFACT_VERSION:
        raise ValueError(f"Unsupported graph version: {payload.get('version')}")
    return payload
