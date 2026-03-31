"""
QuantumRouter — DS-P1-01

Routage adaptatif par superposition et collapse quantique.
Orchestre l'exécution parallèle de plusieurs agents pour les requêtes
ambiguës ou multi-tâches, avec fusion intelligente des résultats.

Intégration :
- Utilise PathRouter pour le routage initial
- Utilise AgentRegistry pour résoudre les noms d'agents
- Publie sur EventBus (routing.quantum, agent.start, agent.done)
- Trace dans AuditTrail (hash chain)

Mode hybride :
- Si la requête est claire (confiance >= seuil) → routage classique
- Si ambiguë ou multi-tâche → superposition quantique

Contraintes M3 16GB :
- Max 4 agents parallèles (MAX_PATHS)
- Timeout global configurable (default 5s)
- Early termination si un agent converge
- Annulation des agents restants via asyncio.Task.cancel()

Backward compat :
- Exports QuantumState (legacy) pour FrontalCortex.think()
  reinforce/penalize still work via LegacyQuantumState wrapper
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import numpy as np

from .quantum_models import (
    CollapseResult, FusionStrategy, PathState, PathWeight,
    QuantumState as _QuantumState,
)
from .quantum_superposition import SuperpositionGenerator
from .quantum_fusion import ResultFusion, WINNER_CONFIDENCE_THRESHOLD
from .router import PathRouter, RouteResult, RoutePath
from ...utils.logger import logger

if TYPE_CHECKING:
    from .registry import AgentRegistry
    from ..synapses.event_bus import EventBus
    from ...services.audit_trail import AuditTrail


# ─────────────────────────────────────────────────────────────────────
# Legacy QuantumState — used by FrontalCortex.think() for
# reinforce/penalize on path_ids ("direct", "multi", "llm", etc.)
# ─────────────────────────────────────────────────────────────────────

class QuantumState:
    """
    État quantique simulé — backward-compatible wrapper.

    Supporte reinforce/penalize pour l'apprentissage continu
    dans FrontalCortex.think(), tout en coexistant avec le nouveau
    QuantumRouter DS-P1-01.
    """

    AGENT_PATHS: List[str] = [
        "direct", "multi", "visual_research", "resonance", "llm",
    ]

    def __init__(self, agents: Optional[List[str]] = None) -> None:
        self.agents = agents or self.AGENT_PATHS
        n = len(self.agents)
        self.amplitudes = np.ones(n, dtype=np.float64) / np.sqrt(n)
        self.history: List[Dict[str, Any]] = []
        self.total_measures: int = 0

    def probabilities(self) -> Any:
        """Collapse la superposition en probabilités (Born rule)."""
        p = self.amplitudes ** 2
        total = p.sum()
        if total == 0:
            return np.ones(len(self.agents)) / len(self.agents)
        return p / total

    def measure(self) -> str:
        """Mesure quantique — collapse vers l'agent le plus probable."""
        probs = self.probabilities()
        idx = int(np.argmax(probs))
        self.total_measures += 1
        return self.agents[idx]

    def reinforce(self, agent: str, reward: float = 0.2) -> None:
        """Interférence constructive — succès renforce le chemin."""
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
        """Interférence destructive — échec affaiblit le chemin."""
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
        """Intrication quantique simulée."""
        combined = (self.amplitudes + other.amplitudes) / 2
        self.amplitudes = combined.copy()
        other.amplitudes = combined.copy()

    def _normalize(self) -> None:
        """Normalisation — somme des probabilités reste 1."""
        norm = np.linalg.norm(self.amplitudes)
        if norm > 0:
            self.amplitudes /= norm

    def get_stats(self) -> Dict[str, Any]:
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


# ─────────────────────────────────────────────────────────────────────
# QuantumRouter — DS-P1-01 Advanced Orchestrator
# ─────────────────────────────────────────────────────────────────────

class QuantumRouter:
    """
    Router quantique — exécution parallèle avec collapse.

    Lifecycle :
    1. route() reçoit la requête
    2. PathRouter classifie → RouteResult
    3. Si superposition nécessaire → generate() → QuantumState
    4. execute_parallel() lance les agents
    5. ResultFusion fusionne → CollapseResult
    6. Publish sur EventBus + AuditTrail
    """

    # Legacy path names for backward compat
    AGENT_PATHS: List[str] = [
        "direct", "multi", "visual_research", "resonance", "llm",
    ]

    def __init__(
        self,
        path_router: Optional[PathRouter] = None,
        agent_registry: Optional[AgentRegistry] = None,
        event_bus: Optional[EventBus] = None,
        audit_trail: Optional[AuditTrail] = None,
        llm_service: Optional[Any] = None,
        predictor: Optional[Any] = None,
    ) -> None:
        self._router = path_router
        self._registry = agent_registry
        self._event_bus = event_bus
        self._audit = audit_trail

        # Legacy state for FrontalCortex compatibility
        self.state = QuantumState(self.AGENT_PATHS)

        # DS-P1-01 components
        if path_router:
            self._superposition = SuperpositionGenerator(path_router, predictor)
        else:
            self._superposition = None  # type: ignore[assignment]
        self._fusion = ResultFusion(llm_service)

        # Configuration
        self.enabled: bool = True
        self.default_strategy: FusionStrategy = FusionStrategy.FIRST_WINNER
        self.default_timeout_ms: float = 5000.0
        self.early_termination: bool = True

        # Stats
        self._stats: Dict[str, Any] = {
            "total_routes": 0,
            "quantum_routes": 0,
            "classic_routes": 0,
            "avg_paths_explored": 0.0,
            "avg_latency_ms": 0.0,
            "early_terminations": 0,
        }

        # Source token pour EventBus
        self._source_token: Optional[str] = None

        # Thalamus weights for legacy route()
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

    async def initialize(self, event_bus: Optional[EventBus] = None) -> None:
        """Initialise la connexion EventBus."""
        if event_bus:
            self._event_bus = event_bus
        if self._event_bus:
            self._source_token = self._event_bus.register_source("quantum_router")

    # ── Legacy route (Thalamus-based, used by FrontalCortex) ───

    def route(self, ctx: Any) -> str:
        """
        Routage quantique legacy (Thalamus → measure).
        Kept for FrontalCortex backward compatibility.
        """
        if ctx.signals:
            freqs = ctx.signals.get("frequencies", [])
            for freq in freqs:
                preferred = self.thalamus_weights.get(freq)
                if preferred:
                    self.state.reinforce(preferred, 0.1)
        return self.state.measure()

    async def execute_and_learn(
        self, ctx: Any, execute_fn: Any,
    ) -> Tuple[Any, str, bool]:
        """Legacy execute_and_learn for backward compat."""
        start = time.monotonic()
        path = self.route(ctx)
        try:
            result = await execute_fn(path, ctx)
            success = result is not None
            if success:
                self.state.reinforce(path, 0.2)
            else:
                self.state.penalize(path, 0.15)
            return result, path, success
        except Exception as e:
            self.state.penalize(path, 0.15)
            raise

    # ── DS-P1-01 Advanced route ────────────────────────────────

    async def route_quantum(
        self,
        query: str,
        strategy: Optional[FusionStrategy] = None,
        timeout_ms: Optional[float] = None,
        force_quantum: bool = False,
    ) -> CollapseResult:
        """
        Route une requête — classique ou quantique.

        Args:
            query: La requête utilisateur
            strategy: Stratégie de fusion (default: FIRST_WINNER)
            timeout_ms: Timeout global en ms (default: 5000)
            force_quantum: Force le mode quantique même si confiance élevée

        Returns:
            CollapseResult avec le résultat final
        """
        if not self._router or not self._superposition:
            raise RuntimeError("QuantumRouter not properly initialized (no PathRouter)")

        t0 = time.time()
        self._stats["total_routes"] += 1

        strategy = strategy or self.default_strategy
        timeout_ms = timeout_ms or self.default_timeout_ms

        # 1. Routage initial via PathRouter
        route_result = self._router.route(query)

        # 2. Décider : classique ou quantique ?
        if not self.enabled and not force_quantum:
            self._stats["classic_routes"] += 1
            return await self._classic_route(query, route_result, t0)

        if not force_quantum and not self._superposition.should_superpose(
            route_result, query
        ):
            self._stats["classic_routes"] += 1
            return await self._classic_route(query, route_result, t0)

        # 3. Mode quantique
        self._stats["quantum_routes"] += 1
        logger.info(
            f"QuantumRouter active pour: \"{query[:60]}...\" "
            f"(initial: {route_result.agent} @ {route_result.confidence:.2f})"
        )

        # Publier l'événement de début
        await self._publish_event("routing.quantum.start", {
            "query": query[:100],
            "initial_agent": route_result.agent,
            "initial_confidence": route_result.confidence,
            "strategy": strategy.value,
        })

        # 4. Générer la superposition
        state = self._superposition.generate(
            query, route_result, strategy, timeout_ms,
        )

        # 5. Exécuter en parallèle
        result = await self._execute_quantum(state)

        # 6. Mettre à jour les stats
        elapsed = (time.time() - t0) * 1000
        result = CollapseResult(
            quantum_id=result.quantum_id,
            query=result.query,
            selected_agent=result.selected_agent,
            result=result.result,
            confidence=result.confidence,
            strategy_used=result.strategy_used,
            total_latency_ms=elapsed,
            paths_explored=result.paths_explored,
            paths_completed=result.paths_completed,
            paths_cancelled=result.paths_cancelled,
            all_paths=result.all_paths,
            fusion_detail=result.fusion_detail,
        )
        self._update_stats(result)

        # 7. Publier le résultat et tracer
        await self._publish_event("routing.quantum.collapse", {
            "quantum_id": result.quantum_id,
            "selected_agent": result.selected_agent,
            "confidence": result.confidence,
            "paths_explored": result.paths_explored,
            "latency_ms": result.total_latency_ms,
            "fusion_detail": result.fusion_detail,
        })
        await self._audit_log(result)

        logger.info(
            f"Quantum collapse -> {result.selected_agent} "
            f"(conf={result.confidence:.2f}, "
            f"paths={result.paths_completed}/{result.paths_explored}, "
            f"{result.total_latency_ms:.0f}ms)"
        )

        return result

    # ── Exécution quantique ─────────────────────────────────────

    async def _execute_quantum(self, state: _QuantumState) -> CollapseResult:
        """
        Exécute les agents en parallèle avec timeout et early termination.
        """
        timeout_s = state.timeout_ms / 1000.0
        tasks: Dict[asyncio.Task[None], PathWeight] = {}

        # Créer les tasks
        for path in state.paths:
            task = asyncio.create_task(
                self._execute_single_agent(path, state.query),
                name=f"quantum-{path.agent}",
            )
            tasks[task] = path
            path.state = PathState.RUNNING

        try:
            if self.early_termination and state.strategy == FusionStrategy.FIRST_WINNER:
                result = await self._execute_with_early_term(
                    tasks, state, timeout_s
                )
            else:
                result = await self._execute_all(tasks, state, timeout_s)
            return result

        except Exception as e:
            logger.error(f"Quantum execution error: {e}")
            for task in tasks:
                if not task.done():
                    task.cancel()
            return self._fusion._make_failure(state, str(e))

    async def _execute_with_early_term(
        self,
        tasks: Dict[asyncio.Task[None], PathWeight],
        state: _QuantumState,
        timeout_s: float,
    ) -> CollapseResult:
        """Exécution avec early termination."""
        pending = set(tasks.keys())
        deadline = time.monotonic() + timeout_s

        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                for task in pending:
                    task.cancel()
                    path = tasks[task]
                    if not path.is_terminal:
                        path.state = PathState.DECOHERENT
                        path.error = "timeout"
                break

            done, pending = await asyncio.wait(
                pending,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in done:
                path = tasks[task]
                try:
                    task.result()
                except asyncio.CancelledError:
                    path.state = PathState.CANCELLED
                except Exception as e:
                    path.state = PathState.FAILED
                    path.error = str(e)

                # Vérifier si c'est un winner
                if (path.state == PathState.COMPLETED and
                        path.confidence >= WINNER_CONFIDENCE_THRESHOLD):
                    self._stats["early_terminations"] += 1
                    for other_task in pending:
                        other_task.cancel()
                        other_path = tasks[other_task]
                        other_path.state = PathState.CANCELLED
                    pending.clear()
                    break

        # Attendre la cancellation effective
        for task in tasks:
            if not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

        return await self._fusion.fuse(state)

    async def _execute_all(
        self,
        tasks: Dict[asyncio.Task[None], PathWeight],
        state: _QuantumState,
        timeout_s: float,
    ) -> CollapseResult:
        """Exécution complète — attend tous les résultats ou timeout."""
        try:
            done, pending = await asyncio.wait(
                tasks.keys(),
                timeout=timeout_s,
                return_when=asyncio.ALL_COMPLETED,
            )
        except Exception:
            done = set()
            pending = set(tasks.keys())

        for task in done:
            path = tasks[task]
            try:
                task.result()
            except asyncio.CancelledError:
                path.state = PathState.CANCELLED
            except Exception as e:
                if not path.is_terminal:
                    path.state = PathState.FAILED
                    path.error = str(e)

        for task in pending:
            task.cancel()
            path = tasks[task]
            path.state = PathState.DECOHERENT
            path.error = "timeout"

        return await self._fusion.fuse(state)

    async def _execute_single_agent(
        self, path: PathWeight, query: str
    ) -> None:
        """Exécute un seul agent et met à jour le PathWeight."""
        t0 = time.perf_counter()

        try:
            await self._publish_event("agent.start", {
                "agent": path.agent,
                "reason": "quantum_exploration",
            })

            agent = self._resolve_agent(path.agent)
            if agent is None:
                path.state = PathState.FAILED
                path.error = f"Agent '{path.agent}' not found in registry"
                return

            result = await self._call_agent(agent, query)

            path.state = PathState.COMPLETED
            path.result = str(result) if result else ""
            path.confidence = self._estimate_result_confidence(result)
            path.latency_ms = (time.perf_counter() - t0) * 1000

            await self._publish_event("agent.done", {
                "agent": path.agent,
                "latency_ms": path.latency_ms,
                "confidence": path.confidence,
            })

        except asyncio.CancelledError:
            path.state = PathState.CANCELLED
            path.latency_ms = (time.perf_counter() - t0) * 1000
            raise

        except Exception as e:
            path.state = PathState.FAILED
            path.error = str(e)[:200]
            path.latency_ms = (time.perf_counter() - t0) * 1000
            logger.warning(f"Quantum path {path.agent} failed: {e}")

    def _resolve_agent(self, agent_name: str) -> Optional[Any]:
        """Résout un nom d'agent via le registre."""
        if self._registry is None:
            return None
        try:
            return self._registry.get_agent(agent_name)
        except Exception:
            return None

    async def _call_agent(self, agent: Any, query: str) -> Any:
        """
        Appelle un agent de manière uniforme.

        Supporte :
        - agent.execute(query) → async
        - agent.process(query) → async
        - agent.handle(query) → async or sync
        """
        if hasattr(agent, 'execute'):
            return await agent.execute(query)
        elif hasattr(agent, 'process'):
            return await agent.process(query)
        elif hasattr(agent, 'handle'):
            result = agent.handle(query)
            if asyncio.iscoroutine(result):
                return await result
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, agent.handle, query)
        else:
            raise RuntimeError(
                f"Agent {getattr(agent, 'name', agent)} has no execute/process/handle method"
            )

    def _estimate_result_confidence(self, result: Any) -> float:
        """
        Estime la confiance d'un résultat d'agent.

        Heuristique :
        - None → 0.0
        - Chaîne vide → 0.1
        - Contient "erreur" ou "impossible" → 0.3
        - Longueur > 20 chars → 0.7
        - Longueur > 100 chars → 0.85
        - Résultat structuré (dict avec "result") → 0.9
        """
        if result is None:
            return 0.0
        if isinstance(result, dict):
            if "error" in result:
                return 0.2
            if "result" in result:
                return 0.9
            return 0.7
        s = str(result)
        if not s:
            return 0.1
        lower = s.lower()
        if "erreur" in lower or "impossible" in lower or "error" in lower:
            return 0.3
        if len(s) > 100:
            return 0.85
        if len(s) > 20:
            return 0.7
        return 0.5

    # ── Route classique (wrapper) ───────────────────────────────

    async def _classic_route(
        self, query: str, route_result: RouteResult, t0: float
    ) -> CollapseResult:
        """Route classique — un seul agent, wrappé en CollapseResult."""
        agent = self._resolve_agent(route_result.agent)

        result_text = ""
        confidence = route_result.confidence

        if agent:
            try:
                result_text = str(await self._call_agent(agent, query) or "")
                confidence = max(confidence, self._estimate_result_confidence(result_text))
            except Exception as e:
                result_text = f"Error: {e}"
                confidence = 0.1

        elapsed = (time.time() - t0) * 1000

        return CollapseResult(
            quantum_id="classic",
            query=query,
            selected_agent=route_result.agent,
            result=result_text,
            confidence=confidence,
            strategy_used=FusionStrategy.FIRST_WINNER,
            total_latency_ms=elapsed,
            paths_explored=1,
            paths_completed=1 if result_text else 0,
            paths_cancelled=0,
            all_paths=[{
                "agent": route_result.agent,
                "weight": 1.0,
                "state": "completed",
                "confidence": confidence,
                "latency_ms": elapsed,
                "has_result": bool(result_text),
            }],
            fusion_detail="classic_route",
        )

    # ── EventBus & AuditTrail ───────────────────────────────────

    async def _publish_event(self, channel: str, data: Dict[str, Any]) -> None:
        """Publie un événement sur l'EventBus si disponible."""
        if self._event_bus and self._source_token:
            try:
                await self._event_bus.publish(
                    channel=channel,
                    data=data,
                    source="quantum_router",
                    token=self._source_token,
                )
            except Exception as e:
                logger.debug(f"EventBus publish error: {e}")

    async def _audit_log(self, result: CollapseResult) -> None:
        """Trace le résultat dans l'AuditTrail si disponible."""
        if self._audit:
            try:
                await self._audit.log(
                    action="quantum_collapse",
                    data=result.to_audit_dict(),
                    source="quantum_router",
                )
            except Exception as e:
                logger.debug(f"AuditTrail log error: {e}")

    # ── Stats ───────────────────────────────────────────────────

    def _update_stats(self, result: CollapseResult) -> None:
        """Met à jour les statistiques globales."""
        n = self._stats["total_routes"]
        old_avg_paths = self._stats["avg_paths_explored"]
        old_avg_lat = self._stats["avg_latency_ms"]

        alpha = 1.0 / min(n, 100)
        self._stats["avg_paths_explored"] = (
            old_avg_paths * (1 - alpha) + result.paths_explored * alpha
        )
        self._stats["avg_latency_ms"] = (
            old_avg_lat * (1 - alpha) + result.total_latency_ms * alpha
        )

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "quantum_ratio": (
                f"{self._stats['quantum_routes'] / max(1, self._stats['total_routes']):.0%}"
            ),
            "early_term_ratio": (
                f"{self._stats['early_terminations'] / max(1, self._stats['quantum_routes']):.0%}"
            ),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Legacy get_stats() — returns both quantum and legacy stats."""
        legacy = self.state.get_stats()
        legacy["quantum_router"] = self.stats
        return legacy
