"""
Plasticity — Protocol commun pour les mécanismes LTP/LTD de Lucie.

Deux implémentations prévues (post-beta, Bloc AW-2) :
  - ContextGraph (MemoryStore, SQLite) — déjà conforme rétroactivement
  - QuantumAmplitudes (RAM, numpy) — à extraire de QuantumState

Ce fichier ne contient que le Protocol. Aucune implémentation concrète.
"""

from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class Plasticity(Protocol):
    """
    Interface Hebbian pour tout composant qui apprend par renforcement.

    Grammaire partagée :
      strengthen / weaken  → modification de force d'un lien
      prune                → élagage sous seuil
      snapshot             → export déterministe de l'état courant
    """

    def strengthen(self, link_id: str, delta: float = 0.1) -> None:
        """Renforce un lien (LTP — Long-Term Potentiation)."""
        ...

    def weaken(self, link_id: str, delta: float = 0.1) -> None:
        """Affaiblit un lien (LTD — Long-Term Depression)."""
        ...

    def prune(self, threshold: float) -> int:
        """Élague les liens sous le seuil. Retourne le nombre élaguées."""
        ...

    def snapshot(self) -> Dict[str, Any]:
        """Export déterministe de l'état courant (pour audit et tests)."""
        ...
