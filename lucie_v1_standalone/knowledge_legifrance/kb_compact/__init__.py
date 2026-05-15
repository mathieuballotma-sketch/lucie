"""kb_compact — Sprint K-1 — pipeline signatures binaires Matryoshka + graphe DAG renvois + PageRank.

Produit 3 artefacts compacts côté serveur Beaume Team à partir de legi.sqlite :
- sigs_mrl.bin + sigs_mrl.index.cbor : signatures Matryoshka 2 niveaux (64 + 1024 bits)
- graph.cbor[.zst] : DAG des renvois inter-articles
- pagerank.f32 : centralité juridique PageRank

Invariant : aucune écriture dans legi.sqlite ; aucune modif du retriever client.
"""

from lucie_v1_standalone.knowledge_legifrance.kb_compact.constants import (
    ARTIFACT_VERSION,
    DAMPING_PAGERANK,
    DEFAULT_BATCH_SIZE,
    DEFAULT_SEED,
    LONG_BITS,
    MAGIC_GRAPH,
    MAGIC_SIGS,
    MAX_ITER_PAGERANK,
    MODEL_NAME,
    SHORT_BITS,
)

__all__ = [
    "ARTIFACT_VERSION",
    "DAMPING_PAGERANK",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_SEED",
    "LONG_BITS",
    "MAGIC_GRAPH",
    "MAGIC_SIGS",
    "MAX_ITER_PAGERANK",
    "MODEL_NAME",
    "SHORT_BITS",
]
