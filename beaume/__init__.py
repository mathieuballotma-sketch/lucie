"""Beaume — alias public Python du core legacy ``lucie_v1_standalone``.

Le code historique vit toujours dans ``lucie_v1_standalone`` (rebrand officiel
côté UI au 2026-05-02 ; le rename physique du package est volontairement
reporté post-prospection avocats pour éviter la régression d'imports massive
juste avant la fenêtre pilote).

Cet alias permet aux nouveaux call sites (tests, scripts internes, futures
intégrations) d'écrire ``from beaume import pipeline`` ou
``from beaume import verificateur`` plutôt que de référencer le legacy.

Politique de migration :
  - V1 (actuel) : alias seul, aucun changement d'import dans le code existant
  - V1.3+ (post-pilote) : `git mv lucie_v1_standalone beaume_core` + sed sur
    tous les sites d'import, suppression de cet alias

Ce module n'introduit aucun comportement — il ré-exporte tel-quel.
"""

from __future__ import annotations

# Ré-export des sous-modules les plus utilisés. ``from beaume import pipeline``
# et ``from beaume import verificateur`` doivent fonctionner sans import
# explicite du sous-module.
from lucie_v1_standalone import (  # noqa: F401
    cache,
    config,
    dialogue,
    document_writer,
    dossier_analyzer,
    lecteur,
    memory,
    ollama_client,
    perf,
    pipeline,
    redacteur,
    retriever,
    router,
    verificateur,
)
from lucie_v1_standalone.pipeline import (  # noqa: F401
    PipelineResponse,
    run,
    run_stream,
)

__all__ = [
    "cache",
    "config",
    "dialogue",
    "document_writer",
    "dossier_analyzer",
    "lecteur",
    "memory",
    "ollama_client",
    "perf",
    "pipeline",
    "redacteur",
    "retriever",
    "router",
    "verificateur",
    "PipelineResponse",
    "run",
    "run_stream",
]
