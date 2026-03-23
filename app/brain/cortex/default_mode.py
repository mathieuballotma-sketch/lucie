"""
DefaultModeNetwork — Réseau en mode par défaut — cerveau actif.

Lucie pense même sans utilisateur.
Analyse les conversations récentes, renforce la mémoire, anticipe les besoins.
Trois boucles permanentes :
1. Perception : structure l'information
2. Modèle du monde : représentation interne
3. Apprentissage : corrige et renforce
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional

from ...utils.logger import logger


class DefaultModeNetwork:
    """
    Réseau en mode par défaut — cerveau actif.
    Lucie pense même sans utilisateur.
    Analyse les conversations récentes,
    renforce la mémoire, anticipe les besoins.
    """

    def __init__(self, interval: float = 300.0, memory_graph: Optional[Any] = None) -> None:
        # Intervalle en secondes (5 min en production)
        self.interval = interval
        self.active = False
        self.reflection_count = 0
        self.last_reflection: Optional[float] = None
        self.insights: List[Dict[str, Any]] = []
        self.memory_graph = memory_graph

    async def reflect(self, memory_sample: list[Any]) -> List[Dict[str, Any]]:
        """
        Cycle de réflexion autonome.
        Phase 1 — Perception : analyser les souvenirs
        Phase 2 — Modèle du monde : mettre à jour
        Phase 3 — Apprentissage : renforcer les liens
        """
        if not memory_sample:
            return []

        self.reflection_count += 1
        self.last_reflection = time.monotonic()

        logger.debug(
            f"🧠 Réflexion autonome #{self.reflection_count} "
            f"— {len(memory_sample)} souvenirs analysés"
        )

        # Phase 1 — Perception
        patterns = self._detect_patterns(memory_sample)

        # Phase 2 — Modèle du monde
        insights = self._build_insights(patterns)

        # Phase 3 — Apprentissage
        self._reinforce_memory(insights)

        # Persistance des liens renforcés (si MemoryGraph persistant)
        if self.memory_graph and hasattr(self.memory_graph, "save_pending"):
            asyncio.create_task(self.memory_graph.save_pending())

        self.insights = insights
        return insights

    def _detect_patterns(self, memories: list[Any]) -> Dict[str, int]:
        """Détecte les patterns récurrents dans les souvenirs récents."""
        patterns: Dict[str, int] = {}
        stop_words = {
            "avec", "dans", "pour", "cette", "celui", "celle",
            "sont", "mais", "donc", "aussi", "plus", "comme",
            "tout", "bien", "très", "avoir", "être", "faire",
            "aller", "venir", "quoi", "quel", "quelle", "comment",
        }
        for memory in memories:
            content = ""
            if isinstance(memory, dict):
                content = str(memory.get("content", memory.get("query", "")) or "")
            elif isinstance(memory, str):
                content = memory

            words = content.lower().split()
            for word in words:
                if len(word) > 4 and word not in stop_words and word.isalpha():
                    patterns[word] = patterns.get(word, 0) + 1

        return dict(sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:10])

    def _build_insights(self, patterns: Dict[str, int]) -> List[Dict[str, Any]]:
        """Construit des insights depuis les patterns. Un insight = concept fréquent."""
        return [
            {"concept": concept, "frequency": freq, "timestamp": time.time()}
            for concept, freq in patterns.items()
            if freq >= 2
        ]

    def _reinforce_memory(self, insights: List[Dict[str, Any]]) -> None:
        """Renforce les connexions mémoire via MemoryGraph."""
        if not insights:
            return
        concepts = [i["concept"] for i in insights]
        logger.debug(f"🧠 Concepts renforcés : {concepts[:5]}")
        # Renforcer les liens dans le MemoryGraph
        if self.memory_graph:
            for i, c1 in enumerate(concepts[:5]):
                for c2 in concepts[i + 1:6]:
                    self.memory_graph.strengthen(c1, c2)

    async def run(self, get_memory_fn: Callable[..., Any]) -> None:
        """
        Boucle autonome principale.
        Tourne en permanence en arrière-plan.
        Lucie pense même quand personne ne parle.
        """
        self.active = True
        logger.info(f"🧠 DefaultModeNetwork démarré (intervalle {self.interval}s)")

        while self.active:
            try:
                await asyncio.sleep(self.interval)
                if not self.active:
                    break
                memories = await get_memory_fn()
                await self.reflect(memories)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"🧠 Réflexion autonome erreur : {e}")

        logger.info("🧠 DefaultModeNetwork arrêté")

    def stop(self) -> None:
        """Arrêt propre de la boucle."""
        self.active = False

    def get_stats(self) -> dict[str, Any]:
        """Statistiques de réflexion."""
        return {
            "reflections": self.reflection_count,
            "last_reflection": self.last_reflection,
            "insights": len(self.insights),
            "active": self.active,
        }
