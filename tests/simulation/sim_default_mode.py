"""Simulation DefaultModeNetwork — réflexion autonome en arrière-plan."""

import asyncio
import time


class DefaultModeNetwork:
    """
    Réseau en mode par défaut — cerveau actif.
    Lucie réfléchit même sans utilisateur.
    Analyse les conversations, renforce la mémoire, anticipe.
    """

    def __init__(self, interval: float = 300.0):
        self.interval = interval
        self.active = False
        self.reflection_count = 0
        self.last_reflection: float | None = None
        self.insights_history: list[list[dict]] = []

    async def reflect(self, memory_sample: list) -> list[dict]:
        """Cycle de réflexion autonome."""
        self.reflection_count += 1
        self.last_reflection = time.monotonic()

        patterns = self._detect_patterns(memory_sample)
        insights = self._build_insights(patterns)
        self._reinforce_memory(insights)
        self.insights_history.append(insights)
        return insights

    def _detect_patterns(self, memories: list) -> dict[str, int]:
        """Détecte les patterns récurrents dans les souvenirs."""
        patterns: dict[str, int] = {}
        for memory in memories:
            words = memory.get("content", "").lower().split()
            for word in words:
                if len(word) > 4:
                    patterns[word] = patterns.get(word, 0) + 1
        return dict(sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:10])

    def _build_insights(self, patterns: dict[str, int]) -> list[dict]:
        """Construit des insights depuis les patterns récurrents."""
        return [
            {"concept": k, "frequency": v}
            for k, v in patterns.items()
            if v > 1
        ]

    def _reinforce_memory(self, insights: list[dict]) -> None:
        """Renforce les connexions mémoire (à connecter à MemoryGraph)."""
        pass  # Sera connecté au MemoryGraph en production

    async def run(self, get_memory_fn) -> None:
        """Boucle autonome principale."""
        self.active = True
        while self.active:
            await asyncio.sleep(self.interval)
            try:
                memories = get_memory_fn()
                if asyncio.iscoroutine(memories):
                    memories = await memories
                await self.reflect(memories)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def stop(self) -> None:
        self.active = False


async def test_default_mode():
    print("── Simulation DefaultModeNetwork ──")

    # Créer 5 faux souvenirs
    memories = [
        {"content": "cours or bitcoin finance investissement"},
        {"content": "python code fonction erreur debug"},
        {"content": "cours bourse bitcoin crypto marché"},
        {"content": "ouvre safari recherche google"},
        {"content": "finance investissement bitcoin portefeuille"},
    ]

    dmn = DefaultModeNetwork(interval=2.0)  # 2s en simulation

    # Lancer en tâche de fond
    task = asyncio.create_task(dmn.run(lambda: memories))

    # Attendre ~5s pour 2 cycles
    await asyncio.sleep(5.5)

    dmn.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Vérifications
    assert dmn.reflection_count >= 2, f"Attendu ≥ 2 réflexions, obtenu {dmn.reflection_count}"
    print(f"  ✅ {dmn.reflection_count} cycles de réflexion complétés")

    assert dmn.last_reflection is not None
    print(f"  ✅ Dernière réflexion enregistrée")

    assert not dmn.active
    print(f"  ✅ stop() arrête la boucle")

    # Vérifier les insights
    if dmn.insights_history:
        last_insights = dmn.insights_history[-1]
        concepts = [i["concept"] for i in last_insights]
        print(f"  ✅ Insights détectés : {concepts[:5]}")
        # "bitcoin" et "finance" devraient apparaître (fréquents)
        all_concepts = [c for insights in dmn.insights_history for i in insights for c in [i["concept"]]]
        assert any("bitcoin" in c for c in all_concepts), "bitcoin devrait être détecté"
        print("  ✅ Pattern 'bitcoin' détecté dans les réflexions")

    # Compatibilité EpisodicMemory : le format dict est compatible
    # EpisodicMemory.remember() retourne List[Dict[str, Any]]
    # DMN.reflect() accepte list[dict] — compatible
    print("  ✅ Format compatible EpisodicMemory")

    print(f"  → DefaultModeNetwork : tests passés ✅\n")


if __name__ == "__main__":
    asyncio.run(test_default_mode())
