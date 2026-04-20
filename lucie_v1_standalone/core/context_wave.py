"""
ContextWave — Onde contextuelle immuable.

Voyage dans tout le pipeline sans reconstruction.
Chaque composant lit, jamais ne modifie.
Budget global partagé par tous les composants.

Principes :
- Moindre action : zéro reconstruction de contexte
- Résonance : budget temps partagé entre toutes les étapes
- Homéostasie : timeout adaptatif basé sur le budget restant
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass(slots=True, frozen=True)
class MemoryFragment:
    """Fragment de mémoire injecté en flux."""
    content: str
    score: float
    source: str


@dataclass(slots=True, frozen=True)
class ContextWave:
    """
    Onde contextuelle immuable — Loi de Résonance.
    Voyage dans tout le pipeline sans reconstruction.
    Chaque composant lit, jamais ne modifie.
    Budget global partagé par tous les composants.
    """
    query: str
    created: float
    budget: float = 15.0
    memory: Tuple[Any, ...] = ()
    signals: Optional[dict[str, Any]] = None
    chain_step: int = 0
    quantum_path: Optional[str] = None
    parent_wave: Optional[ContextWave] = None

    def remaining(self) -> float:
        """Temps restant dans le budget global."""
        elapsed = time.monotonic() - self.created
        return max(0.0, self.budget - elapsed)

    def is_expired(self) -> bool:
        """L'onde a-t-elle épuisé son budget ?"""
        return self.remaining() <= 0.0

    def get_effective_timeout(self, default: float = 30.0) -> float:
        """
        Timeout effectif basé sur budget restant.
        Jamais plus que ce qui reste.
        """
        return min(default, self.remaining())

    def get_enriched_system(self) -> str:
        """
        Contexte enrichi construit une seule fois.
        Zéro reconstruction.
        """
        if not self.memory:
            return self.query
        memory_str = "\n".join(f"- {m}" for m in self.memory)
        return f"{self.query}\n\nContexte mémorisé :\n{memory_str}"

    def next_wave(self, memory: tuple[Any, ...] = ()) -> ContextWave:
        """
        Crée une onde enfant pour étape suivante.
        Transmet le budget restant automatiquement.
        """
        return ContextWave(
            query=self.query,
            created=self.created,
            budget=self.budget,
            memory=memory or self.memory,
            signals=self.signals,
            chain_step=self.chain_step + 1,
            parent_wave=self,
        )

    @staticmethod
    def create(query: str, budget: float = 15.0) -> ContextWave:
        """Point d'entrée unique — première onde."""
        return ContextWave(
            query=query,
            created=time.monotonic(),
            budget=budget,
            signals={"frequencies": ["general_query"]},
        )
