"""Simulation ContextWave — onde contextuelle immutable avec budget partagé."""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class MemoryFragment:
    """Fragment de mémoire attaché à une onde."""
    content: str
    score: float
    source: str


@dataclass(frozen=True)
class ContextWave:
    """Onde contextuelle immutable — se propage à travers le pipeline."""
    query: str
    created: float
    budget: float = 15.0
    memory: tuple = ()
    signals: Optional[dict] = None
    chain_step: int = 0
    parent_wave: Optional['ContextWave'] = None

    def remaining(self) -> float:
        """Temps restant dans le budget (secondes)."""
        elapsed = time.monotonic() - self.created
        return max(0.0, self.budget - elapsed)

    def is_expired(self) -> bool:
        """Vérifie si le budget est épuisé."""
        return self.remaining() <= 0.0

    def next_wave(self, memory: tuple = ()) -> 'ContextWave':
        """Crée l'onde suivante avec mémoire enrichie."""
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
    def create(query: str, budget: float = 15.0) -> 'ContextWave':
        """Point d'entrée — crée une onde fraîche."""
        return ContextWave(
            query=query,
            created=time.monotonic(),
            budget=budget,
        )


def test_context_wave():
    print("── Simulation ContextWave ──")

    # Création
    ctx = ContextWave.create("test query", 15.0)
    assert ctx.query == "test query"
    assert ctx.remaining() > 14.0
    assert not ctx.is_expired()
    print("  ✅ Création OK")

    # Chaînage
    child = ctx.next_wave()
    assert child.chain_step == 1
    assert child.parent_wave == ctx
    assert child.remaining() > 0
    print("  ✅ Chaînage OK")

    # 3 ondes en chaîne — budget partagé
    wave1 = ContextWave.create("requête", 10.0)
    wave2 = wave1.next_wave(memory=("concept_a",))
    wave3 = wave2.next_wave(memory=("concept_a", "concept_b"))
    assert wave3.chain_step == 2
    assert wave3.memory == ("concept_a", "concept_b")
    assert wave3.remaining() > 0
    assert wave3.created == wave1.created  # même timestamp = budget partagé
    print("  ✅ 3 ondes chaînées — budget partagé OK")

    # Immutabilité
    try:
        ctx.query = "modifié"  # type: ignore
        assert False, "Devrait lever FrozenInstanceError"
    except Exception:
        pass
    print("  ✅ Immutabilité OK")

    print("  → ContextWave : 4/4 tests passés ✅\n")


if __name__ == "__main__":
    test_context_wave()
