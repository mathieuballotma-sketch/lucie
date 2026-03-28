"""
Cortex central — Orchestrateur des agents et de la planification.

Ce package expose exactement les mêmes noms que l'ancien cortex.py monolithique.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from pydantic.v1 import BaseModel, ValidationError

from app.agents.planner_agent import PlannerAgent
from app.memory.memory_manager import MemoryManager

from ..synapses.event_bus import EventBus
from ...core.elasticity import ElasticityEngine
from ...core.executor import TaskExecutor
from ...memory import MemoryService
from ...providers.manager import ProviderManager
from ...services.prompt_cache import PromptCache
from ...utils.circuit_breaker import CircuitBreaker
from ...utils.logger import logger

# Re-exports depuis les sous-modules
from .registry import AgentRegistry, AgentFileHandler as AgentFileHandler
from .classifier import EmbeddingClassifier
from .predictor import NanoPredictor
from .router import PathRouter as PathRouter, RoutePath as RoutePath, RouteResult as RouteResult
from .execution_engine import ExecutionEngine

# Alias pour compatibilite avec l'ancien cortex
class PathManager:
    """Gère le routage des requêtes vers les chemins d'exécution."""

    def __init__(self, classifier: Any = None) -> None:
        self._classifier = classifier
        self._router = PathRouter()
        self._router.initialize()
        self._exec_engine: Optional[Any] = None

    async def select_paths(self, query: str = "", *args: Any, **kwargs: Any) -> List[Tuple[str, Callable[..., Awaitable[str]]]]:
        engine: Optional[Any] = self._exec_engine

        async def direct_path(q: Optional[str] = None) -> str:
            result = await engine.execute_direct_action(q or query) if engine else None
            if not result:
                raise ValueError("Aucune action directe trouvee")
            return str(result)

        async def multi_path(q: Optional[str] = None) -> str:
            result = await engine.execute_multi_action(q or query) if engine else None
            if not result:
                raise ValueError("Aucune action multi trouvee")
            return str(result)

        async def creation_path(q: Optional[str] = None) -> str:
            result = await engine.execute_creation_agent(q or query) if engine else None
            if not result:
                raise ValueError("Aucune creation trouvee")
            return str(result)

        async def resonance_path(q: Optional[str] = None) -> str:
            """Chemin LLM par résonance — vibration progressive nano→speed→balanced."""
            if engine and engine._current_ctx is not None:
                return str(await engine.llm_resonance(engine._current_ctx, q or query))
            raise ValueError("Résonance non disponible")

        async def llm_path(q: Optional[str] = None) -> str:
            if engine:
                loop = asyncio.get_running_loop()
                return str(await loop.run_in_executor(
                    None, engine.call_llm, q or query, "balanced"
                ))
            raise ValueError("Pas d'engine disponible")

        async def visual_research_path(q: Optional[str] = None) -> str:
            if engine:
                result = await engine.execute_visual_research(q or query)
                if not result:
                    raise ValueError("Recherche visuelle échouée")
                return str(result)
            raise ValueError("Pas d'engine disponible")

        # Mapping Thalamus → agent pour le chemin agent_path
        _THALAMUS_TO_AGENT: Dict[str, str] = {
            "calendar_query": "CalendarAgent",
            "reminder_query": "AppleEcosystemAgent",
            "file_query": "FileAgent",
            "code_query": "CodeDebugAgent",
            "document_query": "DocumentAgent",
            "research_query": "KnowledgeAgent",
            "finance_query": "KnowledgeAgent",
            "watch_query": "WatchAgent",
            "mail_query": "SmartMailAgent",
        }

        async def agent_path(q: Optional[str] = None) -> str:
            """Chemin Thalamus → Agent direct. Le cerveau décide."""
            if not engine:
                raise ValueError("Pas d'engine")
            # Lire les signaux Thalamus depuis le ctx injecté dans l'engine
            ctx_signals = getattr(engine, "_current_ctx", None)
            if not ctx_signals or not ctx_signals.signals:
                raise ValueError("Pas de signal Thalamus")
            freqs = ctx_signals.signals.get("frequencies", [])
            for freq in freqs:
                agent_name = _THALAMUS_TO_AGENT.get(freq)
                if not agent_name:
                    continue
                agent = engine.registry.agents.get(agent_name)
                if agent and hasattr(agent, "handle"):
                    result = await agent.handle(q or query)
                    if result:
                        return str(result)
            raise ValueError("Aucun agent Thalamus disponible")

        # Routage intelligent : utiliser le router pour décider de l'ordre
        route_result = self._router.route(query) if self._router else None
        q_lower = query.lower().strip()

        # Requêtes de création d'agent → creation en premier
        _creation_kw = ["crée un agent", "créer un agent", "génère un agent", "fabrique un agent"]
        is_creation = any(kw in q_lower for kw in _creation_kw)
        if is_creation:
            return [("creation", creation_path), ("llm", llm_path)]

        # ── Recherche visuelle Safari → PRIORITAIRE sur multi-action ─────
        # Détection par co-occurrence : recherche + synthèse/résumé, ou safari + recherche
        _LLM_ONLY_PREFIXES = ("explique", "définis", "qu'est-ce", "c'est quoi",
                               "donne-moi", "résume en", "décris")
        if not any(q_lower.startswith(p) for p in _LLM_ONLY_PREFIXES):
            _has_search = any(w in q_lower for w in ("recherche", "cherche", "trouve"))
            _has_synth = any(w in q_lower for w in (
                "résumé", "résume", "synthèse", "synthese", "bilan", "rapport",
            ))
            _has_safari = "safari" in q_lower
            if (_has_search and _has_synth) or (_has_safari and _has_search):
                return [("visual_research", visual_research_path), ("llm", llm_path)]

        # Recherche visuelle détectée par le router (keywords/embedding/thalamus)
        if route_result and route_result.path.value == "visual_research":
            if not any(q_lower.startswith(p) for p in _LLM_ONLY_PREFIXES):
                return [("visual_research", visual_research_path), ("llm", llm_path)]

        # Multi-action détectée ("et" ou "puis" dans la requête) → multi en premier
        import re as _re
        if _re.search(r"\s+(et|puis)\s+", q_lower):
            return [("multi", multi_path), ("direct", direct_path), ("agent", agent_path), ("llm", llm_path)]

        # Fast path (keyword ou embedding match) → direct/agent/multi d'abord
        if route_result and route_result.path.value == "fast_path":
            return [("direct", direct_path), ("agent", agent_path), ("multi", multi_path), ("llm", llm_path)]

        # Fallback → agent Thalamus avant LLM
        return [("direct", direct_path), ("agent", agent_path), ("resonance", resonance_path), ("llm", llm_path)]


# ─────────────────────────────────────────────────────────────────────────────
# Modèles de validation
# ─────────────────────────────────────────────────────────────────────────────
class UserQuery(BaseModel):
    """Requête utilisateur validée."""
    text: str
    allow_web_search: bool = True
    system_prompt: Optional[str] = None

    @classmethod
    def from_raw(cls, query: str, **kwargs: Any) -> UserQuery:
        try:
            return cls(text=query, **kwargs)
        except ValidationError as e:
            raise ValueError(f"Requête invalide: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class CortexConfig:
    """Configuration du cortex."""
    plan_timeout: float = 30.0
    max_plan_retries: int = 1
    enable_memory: bool = True
    enable_elasticity: bool = True
    enable_circuit_breaker: bool = True
    cb_failure_threshold: int = 5
    cb_recovery_timeout: int = 60
    web_search: bool = True
    speed_model: str = "qwen2.5:3b"
    balanced_model: str = "qwen2.5:7b"
    quality_model: str = "qwen3:14b"
    nano_model: str = "qwen2.5:3b"
    deep_model: str = "deepseek-r1:14b"
    retrain_classifier: bool = False
    custom_agents_dir: str = "./data/custom_agents"
    api_keys: Dict[str, str] = field(default_factory=dict)
    vision: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CortexConfig:
        return cls(
            plan_timeout=data.get("plan_timeout", 30.0),
            max_plan_retries=data.get("max_plan_retries", 1),
            enable_memory=data.get("enable_memory", True),
            enable_elasticity=data.get("enable_elasticity", True),
            enable_circuit_breaker=data.get("enable_circuit_breaker", True),
            cb_failure_threshold=data.get("cb_failure_threshold", 5),
            cb_recovery_timeout=data.get("cb_recovery_timeout", 60),
            web_search=data.get("web_search", True),
            speed_model=data.get("speed_model", "qwen2.5:3b"),
            balanced_model=data.get("balanced_model", "qwen2.5:7b"),
            quality_model=data.get("quality_model", "qwen3:14b"),
            deep_model=data.get("deep_model", "deepseek-r1:14b"),
            nano_model=data.get("nano_model", "qwen2.5:0.5b"),
            retrain_classifier=data.get("retrain_classifier", False),
            custom_agents_dir=data.get("custom_agents_dir", "./data/custom_agents"),
            api_keys=data.get("api_keys", {}),
            vision=data.get("vision", {}),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Cortex frontal — Orchestrateur principal
# ─────────────────────────────────────────────────────────────────────────────
class FrontalCortex:
    """
    Cortex frontal — Orchestrateur principal.
    Délègue aux sous-composants pour l'exécution.
    """

    def __init__(
        self,
        manager: ProviderManager,
        bus: Any,
        event_bus: EventBus,
        prompt_cache: PromptCache,
        memory_service: MemoryService,
        elasticity_engine: ElasticityEngine,
        config: Dict[str, Any],
    ) -> None:
        self.manager = manager
        self.bus = bus
        self.event_bus = event_bus
        self.prompt_cache = prompt_cache
        self.memory = memory_service
        self.elasticity = elasticity_engine
        self.raw_config = config
        self.cortex_config = CortexConfig.from_dict(config)

        self.executor = TaskExecutor(max_workers=3, persist_path=None)

        self.custom_agents_dir = Path(self.cortex_config.custom_agents_dir)
        self.custom_agents_dir.mkdir(parents=True, exist_ok=True)

        self._cortex_token = str(_uuid.uuid4())
        self._cortex_registered = False
        self._quantum_router = None  # injecté par engine.py
        logger.debug(f"Cortex créé avec token provisoire {self._cortex_token[:8]}...")

        self.agent_registry = AgentRegistry(
            manager, bus, event_bus, config, self.custom_agents_dir, self._cortex_token
        )

        self.memory_manager = MemoryManager(memory_service, config)

        self.planner = PlannerAgent(manager, bus, event_bus, config)
        self.planner.set_agents(self.agent_registry.agents)

        self.model_mapping: Dict[str, str] = {
            "speed": self.cortex_config.speed_model,
            "balanced": self.cortex_config.balanced_model,
            "quality": self.cortex_config.quality_model,
            "nano": self.cortex_config.nano_model,
            "deep": self.cortex_config.deep_model,
        }

        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self.classifier = EmbeddingClassifier(retrain=self.cortex_config.retrain_classifier)
        if self.classifier.initialize():
            logger.info("✅ Classifier initialisé (all-MiniLM-L6-v2)")
        else:
            logger.warning("⚠️ Classifier indisponible — Fast Path par keywords uniquement")

        # NanoPredictor connecté au même classifier que le cortex
        self.predictor: Optional[NanoPredictor] = NanoPredictor()
        self._predictor_started = False

        self._llm_circuit_breaker: Optional[CircuitBreaker] = None
        if self.cortex_config.enable_circuit_breaker:
            self._llm_circuit_breaker = CircuitBreaker(
                name="llm",
                failure_threshold=self.cortex_config.cb_failure_threshold,
                recovery_timeout=self.cortex_config.cb_recovery_timeout,
            )

        self.execution_engine: Optional[ExecutionEngine] = None

        self.path_manager = PathManager(self.classifier)

        # Passer le classifier du cortex au PathRouter pour cohérence
        if self.classifier.is_ready:
            self.path_manager._router._classifier = self.classifier
            self.path_manager._router._trained = True
            self.path_manager._router._fast_path_enabled = True
            # Charger les exemples de training si pas déjà fait
            if self.classifier.example_count == 0:
                self.path_manager._router.initialize()
            logger.info(f"✅ Fast Path actif ({self.classifier.example_count} exemples)")
            # Connecter le predictor au router qui utilise le bon classifier
            if self.predictor:
                self.predictor.set_router(self.path_manager._router)

        self.agent_registry.start_watcher()

        logger.info(f"🧠 FrontalCortex initialisé avec {len(self.agent_registry.agents)} agents.")

    async def _ensure_cortex_registered(self) -> None:
        """Enregistre le cortex et les agents sur l'EventBus (une seule fois, lazy)."""
        if self._cortex_registered:
            return
        try:
            self._cortex_token = await self.event_bus.register_source(
                source="cortex",
                publish_channels=["tool.error", "agent.loaded", "system.anomaly"],
                subscribe_channels=[],
            )
            self._cortex_registered = True
            logger.debug(f"Cortex enregistré sur EventBus, token {self._cortex_token[:8]}...")
            # Enregistrer aussi tous les agents en attente
            await self.agent_registry.register_agents_on_bus()
        except Exception as e:
            logger.warning(f"Cortex: impossible de s'enregistrer sur EventBus: {e}")

    async def think(
        self,
        query_or_ctx: Any,
        system_prompt: Optional[str] = None,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        """Accepte une requête string ou un ContextWave (rétrocompatible)."""
        from .context_wave import ContextWave
        if isinstance(query_or_ctx, ContextWave):
            ctx = query_or_ctx
            query = ctx.query
        else:
            query = query_or_ctx
            ctx = ContextWave.create(query, budget=45.0)

        self._loop = asyncio.get_running_loop()
        self.agent_registry._loop = self._loop

        # Enregistrement lazy du cortex sur l'EventBus
        await self._ensure_cortex_registered()

        if self.execution_engine is None:
            self.execution_engine = ExecutionEngine(
                registry=self.agent_registry,
                planner=self.planner,
                manager=self.manager,
                prompt_cache=self.prompt_cache,
                memory=self.memory,
                event_bus=self.event_bus,
                config=self.raw_config,
                loop=self._loop,
                model_mapping=self.model_mapping,
                llm_circuit_breaker=self._llm_circuit_breaker,
                elasticity=self.elasticity,
            )
        self.path_manager._exec_engine = self.execution_engine

        if not self._predictor_started:
            self._predictor_started = True
            if self.predictor and self.path_manager._router:
                self.predictor.set_router(self.path_manager._router)

        # Injecter le ContextWave dans l'execution engine
        self.execution_engine._current_ctx = ctx

        start = time.time()
        logger.info(f"🧠 think() — Requête: {query[:60]}…")

        try:
            user_query = UserQuery.from_raw(query, allow_web_search=allow_web_search, system_prompt=system_prompt)
        except ValueError as e:
            logger.error(f"Requête invalide: {e}")
            return "Désolé, votre requête est invalide.", time.time() - start

        paths = await self.path_manager.select_paths(user_query.text)

        # Thalamus influence l'ordre — visual_research prioritaire si finance/recherche web
        if ctx.signals:
            freqs = ctx.signals.get("frequencies", [])
            if any(f in freqs for f in ("finance_query", "research_query")):
                # Ne remonter visual_research que pour les recherches web réelles
                # Pas pour les questions "explique X" qui sont des questions LLM
                q_low = user_query.text.lower()
                _LLM_ONLY_PREFIXES = ("explique", "définis", "qu'est-ce", "c'est quoi",
                                       "donne-moi", "résume en", "décris")
                is_llm_question = any(q_low.startswith(p) for p in _LLM_ONLY_PREFIXES)
                if not is_llm_question:
                    vr = [(pid, fn) for pid, fn in paths if pid == "visual_research"]
                    if vr:
                        paths = vr + [(pid, fn) for pid, fn in paths if pid != "visual_research"]
                        logger.debug("🔮 Thalamus réordonne → visual_research en tête")

        logger.info(f"⚡ Ordre des chemins: {[p[0] for p in paths]}")

        for path_id, path_func in paths:
            try:
                # Budget timeout via ContextWave — Loi de Moindre Action
                # Timeout adapté par chemin — les agents LLM ont besoin de plus
                _PATH_TIMEOUTS = {
                    "visual_research": 125.0,
                    "direct": 45.0,
                    "agent": 45.0,
                    "resonance": 45.0,
                    "llm": 45.0,
                    "multi": 45.0,
                    "creation": 45.0,
                }
                default_timeout = _PATH_TIMEOUTS.get(path_id, 15.0)
                path_timeout = ctx.get_effective_timeout(default_timeout)
                if asyncio.iscoroutinefunction(path_func):
                    response = await asyncio.wait_for(
                        path_func(user_query.text), timeout=path_timeout
                    )
                else:
                    response = str(path_func(user_query.text))
                duration = time.time() - start
                logger.info(f"✅ Chemin '{path_id}' réussi en {duration:.3f}s")

                # ── Fallback confiance LLM → Safari ──────────────────
                # Si le LLM a répondu mais avec faible confiance sur une
                # question factuelle → relancer via Safari
                if path_id in ("llm", "resonance") and response:
                    if self._is_low_confidence_factual(user_query.text, response):
                        remaining = ctx.remaining()
                        if remaining > 15.0:
                            logger.info("🔍 Confiance faible détectée → fallback Safari")
                            try:
                                safari_result = await asyncio.wait_for(
                                    self._execute_visual_research(user_query.text),
                                    timeout=min(remaining - 5.0, 60.0),
                                )
                                if safari_result and len(safari_result) > 20:
                                    duration = time.time() - start
                                    return safari_result, duration
                            except Exception as _sr_err:
                                logger.debug(f"Fallback Safari échoué : {_sr_err}")

                # QuantumRouter apprend du succès
                if self._quantum_router:
                    self._quantum_router.state.reinforce(path_id, 0.2)
                return response, duration
            except Exception as exc:
                logger.warning(f"⚠️  Chemin '{path_id}' échoué: {exc}")
                # QuantumRouter apprend de l'échec
                if self._quantum_router:
                    self._quantum_router.state.penalize(path_id, 0.15)
                if self._cortex_registered:
                    try:
                        await asyncio.wait_for(
                            self.event_bus.publish(
                                channel="tool.error",
                                data={"agent": "cortex", "path": path_id,
                                      "error": str(exc), "suggestion": "Un autre chemin va être essayé."},
                                source="cortex", token=self._cortex_token
                            ),
                            timeout=0.5
                        )
                    except Exception as _eb_err:
                        logger.debug(f"EventBus publish (path error) échoué : {_eb_err}")

        logger.error("Tous les chemins ont échoué.")
        response = self._safe_fallback(user_query.text)
        duration = time.time() - start
        return response, duration

    async def execute_pipeline(
        self,
        steps: List[Dict[str, str]],
        timeout: float = 120.0,
    ) -> str:
        pipeline_start = time.time()
        context = ""
        results: List[str] = []

        deduped: List[Dict[str, str]] = []
        for j, step in enumerate(steps):
            if (step["agent"] == "FileAgent" and j + 1 < len(steps)
                    and steps[j + 1]["agent"] == "FileAgent"):
                continue
            deduped.append(step)
        steps = deduped

        for i, step in enumerate(steps):
            elapsed = time.time() - pipeline_start
            if elapsed > timeout:
                logger.error(f"⏱️ Pipeline timeout après {elapsed:.1f}s (étape {i+1})")
                break

            agent_name = step["agent"]
            instruction = step["instruction"]

            agent = self.agent_registry.agents.get(agent_name)
            if agent is None:
                msg = f"❌ Étape {i+1}: Agent '{agent_name}' introuvable"
                logger.error(msg)
                results.append(msg)
                continue

            if context:
                enriched = f"{instruction}\n\nContexte de l'étape précédente :\n{context}"
            else:
                enriched = instruction

            step_start = time.time()
            try:
                remaining = timeout - (time.time() - pipeline_start)
                is_write = agent_name == "FileAgent" and bool(context) and self._is_file_write(instruction)
                if is_write:
                    filepath = self._extract_filepath(instruction)
                    logger.info(f"🔗 Shortcut FileAgent → write_file({filepath}, {len(context)} chars)")
                    result = agent.write_file(filepath, context)  # type: ignore[attr-defined]
                else:
                    result = await asyncio.wait_for(agent.handle(enriched), timeout=min(remaining, 60.0))
                step_duration = time.time() - step_start
                logger.info(f"🔗 Pipeline étape {i+1}/{len(steps)}: {agent_name} → {step_duration:.1f}s")
                context = result
                results.append(f"✅ {agent_name}: {result}")
            except asyncio.TimeoutError:
                results.append(f"⏱️ Étape {i+1} ({agent_name}) timeout")
                break
            except Exception as e:
                results.append(f"❌ Étape {i+1} ({agent_name}): {e}")
                break

        total = time.time() - pipeline_start
        logger.info(f"🔗 Pipeline terminé en {total:.1f}s ({len(results)}/{len(steps)} étapes)")
        return context if context else "\n".join(results)

    def _is_file_write(self, instruction: str) -> bool:
        keywords = ["sauvegarde", "écris", "crée un fichier", "enregistre",
                     "write", "save", "créer un fichier", "écrire",
                     "sauvegarder", "bureau", "desktop"]
        return any(kw in instruction.lower() for kw in keywords)

    def _extract_filepath(self, instruction: str) -> str:
        match = re.search(r"(~/[^\s\"',]+)", instruction)
        if match:
            return match.group(1)
        match = re.search(r"(/[^\s\"',]+\.\w+)", instruction)
        if match:
            return match.group(1)
        name_match = re.search(r"\b(\w[\w\-]*\.\w{1,5})\b", instruction)
        if name_match:
            return str(Path.home() / "Desktop" / name_match.group(1))
        return str(Path.home() / "Desktop" / "lucide_output.txt")

    # ── Détection de faible confiance LLM ──────────────────────────────

    # Marqueurs d'incertitude dans la réponse LLM
    _UNCERTAINTY_MARKERS = [
        "je ne sais pas", "je n'ai pas d'information", "je ne peux pas vérifier",
        "je n'ai pas accès", "données en temps réel", "pas de données récentes",
        "impossible de vérifier", "je ne dispose pas", "en tant qu'ia",
        "mes connaissances", "ma dernière mise à jour", "je recommande de vérifier",
        "information non disponible", "je ne suis pas en mesure",
    ]

    # Mots-clés indiquant une question factuelle/temps réel
    _FACTUAL_KEYWORDS = [
        "cours", "prix", "combien coûte", "valeur", "bitcoin", "btc", "eth",
        "bourse", "action", "cac", "nasdaq", "température", "météo",
        "score", "résultat", "match", "actualité", "news", "aujourd'hui",
        "en ce moment", "actuellement", "dernières nouvelles",
    ]

    def _is_low_confidence_factual(self, query: str, response: str) -> bool:
        """Détecte si le LLM a répondu avec faible confiance sur une question factuelle."""
        q_low = query.lower()
        r_low = response.lower()

        # La question doit être factuelle/temps réel
        is_factual = any(kw in q_low for kw in self._FACTUAL_KEYWORDS)
        if not is_factual:
            return False

        # La réponse doit montrer de l'incertitude
        has_uncertainty = any(marker in r_low for marker in self._UNCERTAINTY_MARKERS)
        return has_uncertainty

    async def _execute_visual_research(self, query: str) -> Optional[str]:
        """Lance une recherche Safari contextuelle."""
        engine = self.execution_engine
        if engine and hasattr(engine, "execute_visual_research"):
            return await engine.execute_visual_research(query)
        return None

    def _safe_fallback(self, _query: str) -> str:
        logger.warning("Utilisation du fallback sécurisé.")
        if self._cortex_registered:
            try:
                asyncio.create_task(
                    self.event_bus.publish(
                        channel="system.anomaly",
                        data={"query": _query, "reason": "all_paths_failed"},
                        source="cortex",
                        token=self._cortex_token,
                    )
                )
            except Exception as _eb_err:
                logger.debug(f"EventBus publish (anomaly) échoué : {_eb_err}")
        return "Désolé, je n'ai pas pu traiter votre demande."

    async def stop(self) -> None:
        if self.predictor and hasattr(self.predictor, 'stop'):
            await self.predictor.stop()
        self.agent_registry.stop_watcher()
        self.executor.shutdown()
        logger.info("🛑 Cortex arrêté.")
