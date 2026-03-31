"""
Tests unitaires pour le QuantumRouter DS-P1-01.

Couvre :
- QuantumModels (PathWeight, QuantumState, CollapseResult)
- SuperpositionGenerator (décision, génération, multi-task)
- ResultFusion (4 stratégies)
- QuantumRouter (intégration, timeout, early termination)
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.brain.cortex.quantum_models import (
    CollapseResult, FusionStrategy, PathState, PathWeight, QuantumState,
)
from app.brain.cortex.quantum_superposition import (
    SuperpositionGenerator, AMBIGUITY_THRESHOLD,
)
from app.brain.cortex.quantum_fusion import (
    ResultFusion, WINNER_CONFIDENCE_THRESHOLD,
)
from app.brain.cortex.router import RouteResult, RoutePath


# ═══════════════════════════════════════════════════════════════
# QuantumModels
# ═══════════════════════════════════════════════════════════════

class TestQuantumModels:

    def test_path_weight_effective_score(self):
        """Score effectif = weight × confidence."""
        pw = PathWeight(agent="A", weight=0.6, state=PathState.COMPLETED,
                       confidence=0.8)
        assert abs(pw.effective_score - 0.48) < 0.001

    def test_path_weight_score_when_failed(self):
        """Score = 0 si pas complété."""
        pw = PathWeight(agent="A", weight=0.6, state=PathState.FAILED,
                       confidence=0.8)
        assert pw.effective_score == 0.0

    def test_path_weight_is_terminal(self):
        """Terminal states are detected correctly."""
        for s in (PathState.COMPLETED, PathState.FAILED,
                  PathState.CANCELLED, PathState.DECOHERENT):
            pw = PathWeight(agent="A", weight=0.5, state=s)
            assert pw.is_terminal is True

        for s in (PathState.PENDING, PathState.RUNNING):
            pw = PathWeight(agent="A", weight=0.5, state=s)
            assert pw.is_terminal is False

    def test_quantum_state_normalization(self):
        """Normalisation des poids → sum = 1.0."""
        state = QuantumState(
            paths=[
                PathWeight(agent="A", weight=3.0),
                PathWeight(agent="B", weight=7.0),
            ]
        )
        state.normalize_weights()
        assert abs(state.paths[0].weight - 0.3) < 0.001
        assert abs(state.paths[1].weight - 0.7) < 0.001

    def test_quantum_state_is_collapsed(self):
        """is_collapsed quand tous les chemins sont terminaux."""
        state = QuantumState(
            paths=[
                PathWeight(agent="A", weight=0.5, state=PathState.COMPLETED),
                PathWeight(agent="B", weight=0.5, state=PathState.FAILED),
            ]
        )
        assert state.is_collapsed is True

    def test_quantum_state_not_collapsed(self):
        """Pas collapsed si un chemin est encore en cours."""
        state = QuantumState(
            paths=[
                PathWeight(agent="A", weight=0.5, state=PathState.COMPLETED),
                PathWeight(agent="B", weight=0.5, state=PathState.RUNNING),
            ]
        )
        assert state.is_collapsed is False

    def test_quantum_state_active_paths(self):
        """active_paths returns non-terminal paths."""
        state = QuantumState(
            paths=[
                PathWeight(agent="A", weight=0.5, state=PathState.COMPLETED),
                PathWeight(agent="B", weight=0.3, state=PathState.RUNNING),
                PathWeight(agent="C", weight=0.2, state=PathState.PENDING),
            ]
        )
        active = state.active_paths
        assert len(active) == 2
        assert all(not p.is_terminal for p in active)

    def test_quantum_state_completed_paths(self):
        """completed_paths returns only COMPLETED paths."""
        state = QuantumState(
            paths=[
                PathWeight(agent="A", weight=0.5, state=PathState.COMPLETED),
                PathWeight(agent="B", weight=0.3, state=PathState.FAILED),
                PathWeight(agent="C", weight=0.2, state=PathState.COMPLETED),
            ]
        )
        completed = state.completed_paths
        assert len(completed) == 2

    def test_collapse_result_audit_dict(self):
        """CollapseResult se sérialise correctement pour l'audit."""
        cr = CollapseResult(
            quantum_id="abc123",
            query="test",
            selected_agent="A",
            result="ok",
            confidence=0.9,
            strategy_used=FusionStrategy.WEIGHTED_SUM,
            total_latency_ms=150.0,
            paths_explored=3,
            paths_completed=2,
            paths_cancelled=1,
        )
        d = cr.to_audit_dict()
        assert d["quantum_id"] == "abc123"
        assert d["strategy"] == "weighted_sum"
        assert d["explored"] == 3
        assert d["completed"] == 2
        assert d["cancelled"] == 1


# ═══════════════════════════════════════════════════════════════
# SuperpositionGenerator
# ═══════════════════════════════════════════════════════════════

class TestSuperpositionGenerator:

    def _make_router(self):
        router = MagicMock()
        router.route.return_value = RouteResult(
            path=RoutePath.FAST_PATH,
            agent="file_agent",
            confidence=0.6,
            latency_ms=5.0,
            via_fast_path=True,
        )
        return router

    def test_should_superpose_low_confidence(self):
        """Confiance < seuil → superposition."""
        router = self._make_router()
        gen = SuperpositionGenerator(router)
        result = RouteResult(
            path=RoutePath.FAST_PATH,
            agent="file_agent",
            confidence=0.5,
            latency_ms=5.0,
        )
        assert gen.should_superpose(result, "cherche un fichier") is True

    def test_should_not_superpose_high_confidence(self):
        """Confiance >= seuil et pas multi-tâche → pas de superposition."""
        router = self._make_router()
        gen = SuperpositionGenerator(router)
        result = RouteResult(
            path=RoutePath.FAST_PATH,
            agent="file_agent",
            confidence=0.90,
            latency_ms=5.0,
        )
        assert gen.should_superpose(result, "ouvre le fichier") is False

    def test_should_superpose_multi_task(self):
        """Requête multi-tâche → superposition même avec haute confiance."""
        router = self._make_router()
        gen = SuperpositionGenerator(router)
        result = RouteResult(
            path=RoutePath.FAST_PATH,
            agent="file_agent",
            confidence=0.90,
            latency_ms=5.0,
        )
        assert gen.should_superpose(
            result, "cherche le fichier et cree un rappel"
        ) is True

    def test_generate_paths_count(self):
        """Génère les bons chemins avec affinités."""
        router = self._make_router()
        gen = SuperpositionGenerator(router)
        result = RouteResult(
            path=RoutePath.FAST_PATH,
            agent="file_agent",
            confidence=0.6,
            latency_ms=5.0,
        )
        state = gen.generate("cherche un fichier", result)

        assert len(state.paths) >= 1
        assert state.paths[0].agent == "FileAgent"
        total_weight = sum(p.weight for p in state.paths)
        assert abs(total_weight - 1.0) < 0.01

    def test_generate_multi_task_split(self):
        """Multi-tâche → sous-requêtes routées indépendamment."""
        router = self._make_router()
        router.route.side_effect = [
            RouteResult(path=RoutePath.FAST_PATH, agent="file_agent",
                       confidence=0.7, latency_ms=3.0),
            RouteResult(path=RoutePath.FAST_PATH, agent="reminder",
                       confidence=0.8, latency_ms=2.0),
        ]
        gen = SuperpositionGenerator(router)
        result = RouteResult(
            path=RoutePath.FAST_PATH, agent="file_agent",
            confidence=0.5, latency_ms=5.0,
        )
        state = gen.generate(
            "cherche le dossier Dupont et cree un rappel pour vendredi",
            result,
        )

        agents = {p.agent for p in state.paths}
        assert "FileAgent" in agents
        assert "AppleEcosystemAgent" in agents or len(agents) >= 2

    def test_max_paths_limit(self):
        """Jamais plus de MAX_PATHS chemins."""
        router = self._make_router()
        gen = SuperpositionGenerator(router)
        result = RouteResult(
            path=RoutePath.FAST_PATH, agent="file_agent",
            confidence=0.3, latency_ms=5.0,
        )
        state = gen.generate("tout faire en meme temps", result)
        assert len(state.paths) <= 4


# ═══════════════════════════════════════════════════════════════
# ResultFusion
# ═══════════════════════════════════════════════════════════════

class TestResultFusion:

    def _make_state(self, paths: list, strategy: FusionStrategy) -> QuantumState:
        return QuantumState(
            query="test query",
            paths=paths,
            strategy=strategy,
        )

    @pytest.mark.asyncio
    async def test_first_winner_above_threshold(self):
        """FIRST_WINNER : le premier résultat confiant gagne."""
        paths = [
            PathWeight(agent="A", weight=0.5, state=PathState.COMPLETED,
                      result="reponse A", confidence=0.8, latency_ms=100),
            PathWeight(agent="B", weight=0.5, state=PathState.COMPLETED,
                      result="reponse B", confidence=0.9, latency_ms=200),
        ]
        state = self._make_state(paths, FusionStrategy.FIRST_WINNER)
        fusion = ResultFusion()
        result = await fusion.fuse(state)

        assert result.selected_agent == "A"
        assert result.confidence == 0.8

    @pytest.mark.asyncio
    async def test_first_winner_fallback_best_score(self):
        """FIRST_WINNER : si aucun ne dépasse le seuil, meilleur score."""
        paths = [
            PathWeight(agent="A", weight=0.7, state=PathState.COMPLETED,
                      result="reponse A", confidence=0.5, latency_ms=100),
            PathWeight(agent="B", weight=0.3, state=PathState.COMPLETED,
                      result="reponse B", confidence=0.6, latency_ms=200),
        ]
        state = self._make_state(paths, FusionStrategy.FIRST_WINNER)
        fusion = ResultFusion()
        result = await fusion.fuse(state)

        # A: 0.7 × 0.5 = 0.35 > B: 0.3 × 0.6 = 0.18
        assert result.selected_agent == "A"

    @pytest.mark.asyncio
    async def test_weighted_sum(self):
        """WEIGHTED_SUM : score = weight × confidence."""
        paths = [
            PathWeight(agent="A", weight=0.3, state=PathState.COMPLETED,
                      result="low weight", confidence=0.9, latency_ms=100),
            PathWeight(agent="B", weight=0.7, state=PathState.COMPLETED,
                      result="high weight", confidence=0.8, latency_ms=200),
        ]
        state = self._make_state(paths, FusionStrategy.WEIGHTED_SUM)
        fusion = ResultFusion()
        result = await fusion.fuse(state)

        # B: 0.7 × 0.8 = 0.56 > A: 0.3 × 0.9 = 0.27
        assert result.selected_agent == "B"

    @pytest.mark.asyncio
    async def test_consensus_single_path(self):
        """CONSENSUS avec un seul chemin → retourne directement."""
        paths = [
            PathWeight(agent="A", weight=1.0, state=PathState.COMPLETED,
                      result="seul resultat", confidence=0.9, latency_ms=100),
        ]
        state = self._make_state(paths, FusionStrategy.CONSENSUS)
        fusion = ResultFusion()
        result = await fusion.fuse(state)

        assert result.selected_agent == "A"
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_no_completed_paths(self):
        """Aucun chemin complété → échec global."""
        paths = [
            PathWeight(agent="A", weight=0.5, state=PathState.FAILED,
                      error="timeout"),
            PathWeight(agent="B", weight=0.5, state=PathState.CANCELLED),
        ]
        state = self._make_state(paths, FusionStrategy.FIRST_WINNER)
        fusion = ResultFusion()
        result = await fusion.fuse(state)

        assert result.confidence == 0.0
        assert "failed" in result.result.lower() or "aucun" in result.result.lower()

    @pytest.mark.asyncio
    async def test_llm_arbiter_fallback_on_no_llm(self):
        """LLM_ARBITER sans LLM → fallback WEIGHTED_SUM."""
        paths = [
            PathWeight(agent="A", weight=0.4, state=PathState.COMPLETED,
                      result="A", confidence=0.8, latency_ms=100),
            PathWeight(agent="B", weight=0.6, state=PathState.COMPLETED,
                      result="B", confidence=0.7, latency_ms=200),
        ]
        state = self._make_state(paths, FusionStrategy.LLM_ARBITER)
        fusion = ResultFusion(llm_service=None)
        result = await fusion.fuse(state)

        # Fallback weighted_sum : B=0.6×0.7=0.42 > A=0.4×0.8=0.32
        assert result.selected_agent == "B"


# ═══════════════════════════════════════════════════════════════
# QuantumRouter (intégration)
# ═══════════════════════════════════════════════════════════════

class TestQuantumRouter:

    def _make_quantum_router(self):
        from app.brain.cortex.quantum_router import QuantumRouter

        router = MagicMock()
        router.route.return_value = RouteResult(
            path=RoutePath.FALLBACK, agent="planner",
            confidence=0.4, latency_ms=5.0,
        )

        registry = MagicMock()
        agent_mock = AsyncMock()
        agent_mock.execute = AsyncMock(return_value="test result from agent")
        agent_mock.name = "TestAgent"
        registry.get_agent.return_value = agent_mock

        qr = QuantumRouter(
            path_router=router,
            agent_registry=registry,
        )
        return qr

    @pytest.mark.asyncio
    async def test_classic_route_high_confidence(self):
        """Confiance élevée → routage classique."""
        qr = self._make_quantum_router()
        qr._router.route.return_value = RouteResult(
            path=RoutePath.FAST_PATH, agent="FileAgent",
            confidence=0.95, latency_ms=3.0, via_fast_path=True,
        )

        result = await qr.route_quantum("ouvre le fichier test.txt")
        assert result.paths_explored == 1
        assert qr._stats["classic_routes"] == 1

    @pytest.mark.asyncio
    async def test_quantum_route_low_confidence(self):
        """Confiance faible → mode quantique activé."""
        qr = self._make_quantum_router()
        result = await qr.route_quantum("prepare le dossier client Dupont")

        assert result.paths_explored >= 1
        assert qr._stats["quantum_routes"] == 1

    @pytest.mark.asyncio
    async def test_force_quantum(self):
        """force_quantum=True → toujours quantique."""
        qr = self._make_quantum_router()
        qr._router.route.return_value = RouteResult(
            path=RoutePath.FAST_PATH, agent="FileAgent",
            confidence=0.99, latency_ms=1.0,
        )

        result = await qr.route_quantum("simple query", force_quantum=True)
        assert qr._stats["quantum_routes"] == 1

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Timeout global → agents annulés, résultat partiel."""
        qr = self._make_quantum_router()

        async def slow_agent(query):
            await asyncio.sleep(10)
            return "too slow"

        qr._registry.get_agent.return_value.execute = slow_agent

        result = await qr.route_quantum(
            "requete lente",
            timeout_ms=500,
            force_quantum=True,
        )

        assert result.total_latency_ms < 2000

    @pytest.mark.asyncio
    async def test_early_termination(self):
        """Early termination quand un agent converge."""
        qr = self._make_quantum_router()
        qr.early_termination = True

        fast_agent = AsyncMock()
        fast_agent.execute = AsyncMock(
            return_value="reponse rapide et complete avec beaucoup de details pour passer le seuil"
        )
        fast_agent.name = "FastAgent"

        async def slow_execute(query):
            await asyncio.sleep(5)
            return "lent"

        slow_agent = AsyncMock()
        slow_agent.execute = slow_execute
        slow_agent.name = "SlowAgent"

        call_count = 0
        def get_agent(name):
            nonlocal call_count
            call_count += 1
            return fast_agent if call_count == 1 else slow_agent

        qr._registry.get_agent.side_effect = get_agent

        result = await qr.route_quantum(
            "test early termination",
            force_quantum=True,
            timeout_ms=10000,
        )

        assert result.total_latency_ms < 5000

    @pytest.mark.asyncio
    async def test_all_agents_fail(self):
        """Tous les agents échouent → échec global gracieux."""
        qr = self._make_quantum_router()

        failing_agent = AsyncMock()
        failing_agent.execute = AsyncMock(side_effect=RuntimeError("boom"))
        failing_agent.name = "FailAgent"
        qr._registry.get_agent.return_value = failing_agent

        result = await qr.route_quantum("doomed query", force_quantum=True)

        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """Les stats sont correctement mises à jour."""
        qr = self._make_quantum_router()

        await qr.route_quantum("query 1")
        await qr.route_quantum("query 2")

        stats = qr.stats
        assert stats["total_routes"] == 2
        assert isinstance(stats["quantum_ratio"], str)


# ═══════════════════════════════════════════════════════════════
# Legacy backward compat
# ═══════════════════════════════════════════════════════════════

class TestLegacyCompat:

    def test_legacy_quantum_state(self):
        """Legacy QuantumState still works for FrontalCortex."""
        from app.brain.cortex.quantum_router import QuantumState as LegacyState
        state = LegacyState()
        assert "direct" in state.agents
        assert "llm" in state.agents

        # reinforce / penalize
        state.reinforce("direct", 0.3)
        assert state.measure() in state.agents

        state.penalize("llm", 0.1)
        stats = state.get_stats()
        assert "dominant" in stats

    def test_quantum_router_has_state(self):
        """QuantumRouter.state is the legacy QuantumState."""
        from app.brain.cortex.quantum_router import QuantumRouter
        qr = QuantumRouter()
        assert hasattr(qr, 'state')
        assert hasattr(qr.state, 'reinforce')
        assert hasattr(qr.state, 'penalize')
        assert hasattr(qr.state, 'measure')
