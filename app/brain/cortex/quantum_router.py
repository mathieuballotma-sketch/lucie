"""
QuantumRouter — Routeur quantique inspiré pour Lucie.

Superposition de chemins, interférence constructive/destructive,
intrication entre états. Simulé en Python pur via numpy.
Latence cible : 1-3ms au lieu de 5-20ms (cascade séquentielle).

Principes :
- Résonance : les bons chemins s'amplifient par interférence
- Moindre action : mesure directe, pas de cascade séquentielle
- Évolution : apprentissage continu par renforcement/pénalisation
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Tuple

import numpy as np

from ...utils.logger import logger


class QuantumState:
    """
    État quantique simulé — Loi de Résonance.
    Chaque agent possède une amplitude.
    La superposition existe jusqu'à la mesure.
    Les bons chemins s'amplifient par interférence.
    Les mauvais s'annulent automatiquement.
    """

    def __init__(self, agents: List[str]) -> None:
        self.agents = agents
        n = len(agents)
        # Amplitudes égales au départ — superposition uniforme
        self.amplitudes = np.ones(n, dtype=np.float64) / np.sqrt(n)
        self.history: List[Dict[str, Any]] = []
        self.total_measures: int = 0

    def probabilities(self) -> np.ndarray:
        """
        Collapse la superposition en probabilités.
        P = amplitude² (règle de Born simulée).
        """
        p = self.amplitudes ** 2
        total = p.sum()
        if total == 0:
            return np.ones(len(self.agents)) / len(self.agents)
        return p / total

    def measure(self) -> str:
        """
        Mesure quantique — collapse vers l'agent le plus probable.
        Déterministe en production (pas d'exploration).
        """
        probs = self.probabilities()
        idx = int(np.argmax(probs))
        self.total_measures += 1
        agent = self.agents[idx]
        logger.debug(f"⚛️ Mesure quantique → {agent} ({probs[idx]:.2%})")
        return agent

    def measure_weighted(self) -> str:
        """Mesure pondérée — exploration probabiliste (apprentissage)."""
        probs = self.probabilities()
        idx = int(np.random.choice(len(self.agents), p=probs))
        self.total_measures += 1
        return self.agents[idx]

    def reinforce(self, agent: str, reward: float = 0.2) -> None:
        """
        Interférence constructive.
        Succès → amplitude augmente. Le bon chemin se renforce.
        """
        if agent not in self.agents:
            return
        idx = self.agents.index(agent)
        self.amplitudes[idx] += reward
        self._normalize()
        self.history.append({
            "agent": agent, "action": "reinforce",
            "reward": reward, "timestamp": time.time(),
        })

    def penalize(self, agent: str, penalty: float = 0.15) -> None:
        """
        Interférence destructive.
        Échec → amplitude diminue. Le mauvais chemin s'annule.
        """
        if agent not in self.agents:
            return
        idx = self.agents.index(agent)
        self.amplitudes[idx] = max(0.01, self.amplitudes[idx] - penalty)
        self._normalize()
        self.history.append({
            "agent": agent, "action": "penalize",
            "penalty": penalty, "timestamp": time.time(),
        })

    def entangle(self, other: QuantumState) -> None:
        """
        Intrication quantique simulée.
        Deux états partagent leurs amplitudes.
        Quand l'un apprend, l'autre sait.
        """
        combined = (self.amplitudes + other.amplitudes) / 2
        self.amplitudes = combined.copy()
        other.amplitudes = combined.copy()
        logger.debug("⚛️ États intriqués")

    def _normalize(self) -> None:
        """Normalisation — cohérence quantique. Somme des probabilités reste 1."""
        norm = np.linalg.norm(self.amplitudes)
        if norm > 0:
            self.amplitudes /= norm

    def get_stats(self) -> dict:
        """Statistiques de l'état quantique."""
        probs = self.probabilities()
        return {
            "agents": self.agents,
            "probabilities": {
                a: float(f"{p:.3f}")
                for a, p in zip(self.agents, probs)
            },
            "dominant": self.agents[int(np.argmax(probs))],
            "total_measures": self.total_measures,
            "history_size": len(self.history),
        }


class QuantumRouter:
    """
    Routeur quantique inspiré — Lucie.
    Remplace la cascade if/elif séquentielle par une superposition de chemins.
    Apprend de chaque requête via renforcement/pénalisation des amplitudes.
    Latence : 1-3ms (vs 5-20ms cascade).
    """

    # Noms harmonisés avec PathManager.select_paths()
    AGENT_PATHS: List[str] = [
        "direct",
        "multi",
        "visual_research",
        "resonance",
        "llm",
    ]

    def __init__(self) -> None:
        self.state = QuantumState(self.AGENT_PATHS)
        # Mapping Thalamus → vrais noms de paths
        self.thalamus_weights: Dict[str, str] = {
            "finance_query": "visual_research",
            "code_query": "llm",
            "file_query": "direct",
            "memory_query": "resonance",
            "research_query": "visual_research",
            "mac_query": "direct",
            "document_query": "direct",
            "calendar_query": "direct",
            "general_query": "llm",
        }

    def route(self, ctx: Any) -> str:
        """
        Routage quantique principal.
        1. Thalamus influence les amplitudes
        2. Mesure collapse vers le meilleur chemin
        3. Résultat en 1-3ms
        """
        # Influence Thalamus sur la superposition
        if ctx.signals:
            freqs = ctx.signals.get("frequencies", [])
            for freq in freqs:
                preferred = self.thalamus_weights.get(freq)
                if preferred:
                    self.state.reinforce(preferred, 0.1)

        # Mesure quantique — collapse
        return self.state.measure()

    async def execute_and_learn(
        self, ctx: Any, execute_fn: Callable,
    ) -> Tuple[Any, str, bool]:
        """
        Exécute une tâche et apprend du résultat.
        Renforce si succès, pénalise si échec.
        """
        start = time.monotonic()
        path = self.route(ctx)

        try:
            result = await execute_fn(path, ctx)
            success = result is not None

            if success:
                self.state.reinforce(path, 0.2)
            else:
                self.state.penalize(path, 0.15)

            duration = (time.monotonic() - start) * 1000
            logger.debug(f"⚛️ QuantumRouter {duration:.1f}ms → {path} (succès={success})")
            return result, path, success

        except Exception as e:
            self.state.penalize(path, 0.15)
            logger.warning(f"⚛️ Erreur {path} : {e}")
            raise

    def get_stats(self) -> dict:
        """État actuel du routeur quantique."""
        return self.state.get_stats()
