"""
ResultFusion — DS-P1-01

Stratégies de fusion des résultats multi-agents.

4 stratégies disponibles :

1. FIRST_WINNER : Le premier agent qui termine avec confiance > seuil gagne.
   → Le plus rapide. Idéal pour les requêtes simples ambiguës.

2. WEIGHTED_SUM : Score = weight × confidence. Le meilleur score gagne.
   → Le plus équilibré. Attend tous les résultats.

3. LLM_ARBITER : Un LLM léger (nano) choisit le meilleur parmi les résultats.
   → Le plus intelligent mais le plus lent (~500ms supplémentaires).

4. CONSENSUS : Vote pondéré par confiance. Si plusieurs agents convergent
   vers la même catégorie de réponse, le consensus gagne.
   → Le plus robuste pour les décisions critiques.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, List, Optional

from .quantum_models import (
    CollapseResult, FusionStrategy, PathWeight, PathState, QuantumState,
)
from ...utils.logger import logger


# Seuil de confiance pour FIRST_WINNER
WINNER_CONFIDENCE_THRESHOLD = 0.70


class ResultFusion:
    """
    Fusionne les résultats de plusieurs agents selon la stratégie choisie.

    Chaque stratégie est une méthode statique pure (pas d'état).
    L'orchestration (timeout, annulation) est gérée par le QuantumRouter.
    """

    def __init__(self, llm_service: Optional[Any] = None) -> None:
        """
        llm_service est optionnel — nécessaire uniquement pour LLM_ARBITER.
        """
        self._llm = llm_service

    async def fuse(self, state: QuantumState) -> CollapseResult:
        """
        Point d'entrée principal — dispatch vers la bonne stratégie.
        """
        strategy = state.strategy
        completed = state.completed_paths

        if not completed:
            # Aucun chemin complété → échec global
            return self._make_failure(state, "Aucun agent n'a produit de resultat")

        if strategy == FusionStrategy.FIRST_WINNER:
            return self._fuse_first_winner(state)
        elif strategy == FusionStrategy.WEIGHTED_SUM:
            return self._fuse_weighted_sum(state)
        elif strategy == FusionStrategy.LLM_ARBITER:
            return await self._fuse_llm_arbiter(state)
        elif strategy == FusionStrategy.CONSENSUS:
            return self._fuse_consensus(state)
        else:
            return self._fuse_weighted_sum(state)  # Fallback safe

    # ── FIRST_WINNER ────────────────────────────────────────────

    def _fuse_first_winner(self, state: QuantumState) -> CollapseResult:
        """
        Premier résultat avec confiance > seuil.
        Si aucun ne dépasse le seuil, prend le meilleur score.
        """
        completed = state.completed_paths

        # Chercher un winner au-dessus du seuil
        for path in sorted(completed, key=lambda p: p.latency_ms):
            if path.confidence >= WINNER_CONFIDENCE_THRESHOLD:
                return self._make_result(state, path, "first_winner above threshold")

        # Fallback : meilleur effective_score
        best = max(completed, key=lambda p: p.effective_score)
        return self._make_result(state, best, "first_winner best_score fallback")

    # ── WEIGHTED_SUM ────────────────────────────────────────────

    def _fuse_weighted_sum(self, state: QuantumState) -> CollapseResult:
        """
        Score = poids_initial × confiance_résultat.
        Le chemin avec le meilleur score effectif gagne.
        """
        completed = state.completed_paths
        best = max(completed, key=lambda p: p.effective_score)

        detail = " | ".join(
            f"{p.agent}={p.effective_score:.3f}" for p in completed
        )
        return self._make_result(state, best, f"weighted_sum: {detail}")

    # ── LLM_ARBITER ─────────────────────────────────────────────

    async def _fuse_llm_arbiter(self, state: QuantumState) -> CollapseResult:
        """
        Un LLM nano (<500ms) choisit le meilleur résultat.
        """
        if not self._llm:
            logger.warning("LLM_ARBITER sans LLM — fallback WEIGHTED_SUM")
            return self._fuse_weighted_sum(state)

        completed = state.completed_paths

        # Construire le prompt
        options = "\n".join(
            f"[{i+1}] Agent: {p.agent} (confiance: {p.confidence:.2f})\n"
            f"Reponse: {(p.result or '')[:200]}"
            for i, p in enumerate(completed)
        )

        prompt = (
            f"Question originale : \"{state.query}\"\n\n"
            f"Voici {len(completed)} reponses :\n{options}\n\n"
            f"Quel numero est la meilleure reponse ? "
            f"Reponds uniquement par le numero (1-{len(completed)})."
        )

        try:
            # Appel LLM nano avec timeout court
            response = await asyncio.wait_for(
                self._call_llm(prompt),
                timeout=2.0,  # 2s max pour l'arbitrage
            )

            # Parser le numéro
            choice = self._parse_choice(response, len(completed))
            if choice is not None:
                selected = completed[choice]
                return self._make_result(
                    state, selected,
                    f"llm_arbiter chose #{choice+1}: {response[:50]}"
                )
        except asyncio.TimeoutError:
            logger.warning("LLM_ARBITER timeout — fallback WEIGHTED_SUM")
        except Exception as e:
            logger.warning(f"LLM_ARBITER error: {e} — fallback WEIGHTED_SUM")

        return self._fuse_weighted_sum(state)

    async def _call_llm(self, prompt: str) -> str:
        """Appelle le LLM nano pour l'arbitrage."""
        if hasattr(self._llm, 'generate_async'):
            return await self._llm.generate_async(prompt, model="nano")
        elif hasattr(self._llm, 'generate'):
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, self._llm.generate, prompt, "nano"
            )
        raise RuntimeError("LLM service incompatible")

    def _parse_choice(self, response: str, max_n: int) -> Optional[int]:
        """Extrait le numéro choisi par le LLM (0-indexed)."""
        match = re.search(r'\b(\d+)\b', response)
        if match:
            num = int(match.group(1))
            if 1 <= num <= max_n:
                return num - 1
        return None

    # ── CONSENSUS ───────────────────────────────────────────────

    def _fuse_consensus(self, state: QuantumState) -> CollapseResult:
        """
        Vote pondéré. Si plusieurs agents donnent des résultats
        similaires, le consensus renforce la confiance.
        """
        completed = state.completed_paths

        if len(completed) == 1:
            return self._make_result(
                state, completed[0], "consensus: single path"
            )

        # Score par agent
        scores: Dict[str, float] = {}
        agents_map: Dict[str, PathWeight] = {}
        for p in completed:
            key = p.agent
            scores[key] = scores.get(key, 0) + p.effective_score
            if key not in agents_map or p.effective_score > agents_map[key].effective_score:
                agents_map[key] = p

        # Meilleure catégorie
        best_key = max(scores, key=lambda k: scores[k])
        best_path = agents_map[best_key]

        detail = " | ".join(f"{k}={v:.3f}" for k, v in scores.items())
        return self._make_result(state, best_path, f"consensus: {detail}")

    # ── Helpers ─────────────────────────────────────────────────

    def _make_result(self, state: QuantumState, winner: PathWeight,
                     fusion_detail: str) -> CollapseResult:
        """Construit le CollapseResult final."""
        total_latency = (time.time() - state.created_at) * 1000

        return CollapseResult(
            quantum_id=state.id,
            query=state.query,
            selected_agent=winner.agent,
            result=winner.result or "",
            confidence=winner.confidence,
            strategy_used=state.strategy,
            total_latency_ms=total_latency,
            paths_explored=len(state.paths),
            paths_completed=len(state.completed_paths),
            paths_cancelled=len([
                p for p in state.paths
                if p.state in (PathState.CANCELLED, PathState.DECOHERENT)
            ]),
            all_paths=[
                {
                    "agent": p.agent,
                    "weight": p.weight,
                    "state": p.state.value,
                    "confidence": p.confidence,
                    "latency_ms": p.latency_ms,
                    "has_result": p.result is not None,
                }
                for p in state.paths
            ],
            fusion_detail=fusion_detail,
        )

    def _make_failure(self, state: QuantumState, reason: str) -> CollapseResult:
        """Construit un CollapseResult d'échec."""
        return CollapseResult(
            quantum_id=state.id,
            query=state.query,
            selected_agent="none",
            result=f"Quantum collapse failed: {reason}",
            confidence=0.0,
            strategy_used=state.strategy,
            total_latency_ms=(time.time() - state.created_at) * 1000,
            paths_explored=len(state.paths),
            paths_completed=0,
            paths_cancelled=len(state.paths),
            all_paths=[],
            fusion_detail=reason,
        )
