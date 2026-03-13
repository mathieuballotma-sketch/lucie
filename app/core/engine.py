"""
Moteur principal de l'application.
Coordonne le cortex, les services, la mémoire et les agents.

Corrections v2 :
  - Tous les handlers : signature corrigée (event: Event) → event.data, event.source
  - _register_event_handlers : devient async, enregistre le moteur comme source
  - set_loop() : déclenche l'enregistrement des handlers via create_task
  - CyberAgent : token enregistré et injecté au moment de l'init des agents

Incarne les lois universelles :
- Homéostasie : gestion d'erreurs robuste, arrêt propre.
- Entropie : code modulaire, documentation.
- Symbiose : communication via event_bus.
- Évolution : métriques intégrées.
"""

import asyncio
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from app.actions.router import ActionRouter
from app.actions.system import SystemActions
from app.actions.writer import WriterAgent
from app.brain.cortex import FrontalCortex
from app.brain.synapses.bus import SynapseBus
from app.brain.synapses.event_bus import EventBus, Event
from app.core.executor import TaskExecutor
from app.services.prompt_cache import PromptCache
from app.services.ollama_embedder import OllamaEmbedder
from app.services.rag import RAGService
from app.services.scheduler_service import SchedulerService
from app.utils.circuit_breaker import CircuitBreaker
from app.utils.crypto import CryptoManager
from app.utils.logger import logger
from app.utils.memory_monitor import monitor_memory

from ..agents.cyber_agent import CyberAgent
from ..agents.healer_agent import HealerAgent
from ..agents.profile_agent import ProfileAgent
from ..agents.strategist_agent import StrategistAgent
from ..agents.planner_agent import PlannerAgent
from ..core.config import Config
from ..core.elasticity import ElasticityEngine
from ..memory import ConsolidationEngine, EpisodicMemory, MemoryService, WorkingMemory
from ..memory.memory_manager import MemoryManager
from ..p2p.node import P2PNode
from ..providers.manager import ProviderManager


class LucidEngine:
    """
    Moteur principal de l'application Lucide.
    Initialise et orchestre tous les composants (cortex, mémoire, agents, services).
    """

    def __init__(self, config: Config):
        self.config = config
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stopping = False

        # Token de l'engine sur l'EventBus (injecté dans set_loop)
        self._engine_token: Optional[str] = None

        self.bus = SynapseBus()
        self.event_bus = EventBus()
        if config.metrics.enabled:
            start_metrics_server(port=config.metrics.port)
            monitor_memory(interval=config.metrics.memory_interval)

        self._init_llm()
        self._init_executor()
        self._init_memory()
        self._init_services()
        self._init_agents()
        self._init_cortex()
        self._init_p2p()

        # FIX v2 : _register_event_handlers est désormais async,
        # elle sera appelée depuis set_loop() via create_task.
        logger.info("✅ Moteur Lucide initialisé (handlers en attente de set_loop)")

    # -----------------------------------------------------------------------
    # Initialisation
    # -----------------------------------------------------------------------
    def _init_llm(self) -> None:
        models_config = {}
        for key, m in self.config.llm.models.items():
            models_config[key] = asdict(m)
        self.manager = ProviderManager({
            "host": self.config.llm.host,
            "models": models_config,
            "timeout": self.config.llm.timeout,
            "retry_attempts": self.config.llm.retry_attempts,
            "retry_delay": self.config.llm.retry_delay,
            "keep_alive": self.config.llm.keep_alive,
        })

    def _init_executor(self) -> None:
        data_dir = Path(self.config.app.data_dir)
        self.executor = TaskExecutor(
            max_workers=3,
            persist_path=data_dir / "tasks.pkl"
        )

    def _init_memory(self) -> None:
        data_dir = Path(self.config.app.data_dir)
        episodic = EpisodicMemory(
            persist_directory=str(data_dir / "episodic"),
            max_entries=self.config.memory.max_episodic,
            metrics_collector=None,
            embedding_fn=None,  # embedder injecté après _init_services
        )
        working = WorkingMemory(capacity=self.config.memory.working_capacity)
        self.memory = MemoryService(episodic, working)
        self.memory_manager = MemoryManager(self.memory, asdict(self.config))
        self.consolidation = ConsolidationEngine(
            episodic, interval=self.config.memory.consolidation_interval
        )
        if self.config.memory.auto_consolidate:
            self.consolidation.start()

    def _init_services(self) -> None:
        data_dir = Path(self.config.app.data_dir)
        self.prompt_cache = PromptCache(cache_dir=data_dir / "cache", max_size=10000)

        # Embedder Ollama pour le RAG vectoriel
        try:
            self.embedder: Optional[OllamaEmbedder] = OllamaEmbedder(
                model="mxbai-embed-large",
                host=self.config.llm.host,
            )
        except Exception as e:
            logger.warning(f"OllamaEmbedder indisponible: {e}")
            self.embedder = None

        self.rag = RAGService(self.config.rag, embedder=self.embedder)
        self.elasticity = ElasticityEngine(asdict(self.config.elasticity))
        self.elasticity.start()
        self.scheduler = SchedulerService()
        self.scheduler.start()
        self.ollama_circuit = CircuitBreaker("ollama", failure_threshold=3, recovery_timeout=30)
        self.crypto = CryptoManager()

    def _init_agents(self) -> None:
        """
        Initialise tous les agents internes.

        FIX v2 : CyberAgent et HealerAgent reçoivent event_bus mais PAS encore
        de token — celui-ci sera injecté dans set_loop() via set_token(),
        une fois la boucle asyncio disponible pour register_source().
        """
        self.system_actions = SystemActions()
        self.writer_agent = WriterAgent(str(self.config.actions.word_output_dir))
        self.action_router = ActionRouter(self.system_actions, self.writer_agent)

        self.profile_agent = ProfileAgent(
            llm_service=self.manager,
            bus=self.bus,
            memory_service=self.memory,
            rag_service=self.rag,
            config=asdict(self.config),
        )
        self.profile_agent.start()

        self.strategist = StrategistAgent(
            llm_service=self.manager,
            bus=self.bus,
            event_bus=self.event_bus,
            memory_service=self.memory,
            config=asdict(self.config),
        )
        self.scheduler.add_cron_job(
            func=self.strategist.run_periodic_review,
            cron_expr="0 * * * *",
            job_id="strategist_review",
        )

        # FIX v2 : token=None pour l'instant, injecté dans _register_event_handlers
        self.cyber_agent = CyberAgent(
            llm_service=self.manager,
            bus=self.bus,
            event_bus=self.event_bus,
            config=asdict(self.config),
            memory_service=self.memory,
            token=None,
        )

        self.healer_agent = HealerAgent(
            llm_service=self.manager,
            bus=self.bus,
            event_bus=self.event_bus,
            config={
                "quarantine_dir": "~/AgentLucide/quarantine",
                "lures_dir": "~/AgentLucide/lures",
                "auto_quarantine": True,
                "stealth_mode": False,
                "yara_rules_path": "~/.agent_lucide/yara_rules.yar",
                "malicious_hashes_path": "~/.agent_lucide/malicious_hashes.txt",
                "scan_threshold": 0.5,
                "lure_ttl": 86400,
            },
            memory_service=self.memory,
            token=None,
        )

        self.planner_agent = PlannerAgent(
            self.manager, self.bus, self.event_bus, asdict(self.config)
        )

    def _init_cortex(self) -> None:
        self.cortex = FrontalCortex(
            manager=self.manager,
            bus=self.bus,
            event_bus=self.event_bus,
            prompt_cache=self.prompt_cache,
            memory_service=self.memory,
            elasticity_engine=self.elasticity,
            config={
                "web_search": True,
                "api_keys": asdict(self.config.api_keys),
                "vision": asdict(self.config.vision),
                "enable_memory": True,
                "enable_elasticity": True,
                "plan_timeout": 30.0,
                "max_plan_retries": 1,
                "retrain_classifier": False,
                "enable_circuit_breaker": True,
                "max_short_term": getattr(self.config.memory, "max_short_term", 5),
                "max_long_term": getattr(self.config.memory, "max_long_term", 3),
                "max_plan_steps": getattr(self.config.planner, "max_plan_steps", 5),
            },
        )

        # FIX v2 : utiliser agent_registry.agents (et non cortex.agents qui n'existe pas)
        self.planner_agent.set_agents(self.cortex.agent_registry.agents)

        for agent in self.cortex.agent_registry.agents.values():
            agent.event_bus = self.event_bus

    def _init_p2p(self) -> None:
        if hasattr(self.config, "p2p") and self.config.p2p.enabled:
            data_dir = Path(self.config.app.data_dir) / "p2p"
            self.p2p_node = P2PNode(
                config=asdict(self.config.p2p),
                crypto=self.crypto,
                event_bus=self.event_bus,
                data_dir=data_dir,
            )
        else:
            self.p2p_node = None

    # -----------------------------------------------------------------------
    # Enregistrement des handlers
    # FIX v2 : async, enregistre l'engine + CyberAgent + HealerAgent comme sources
    # -----------------------------------------------------------------------
    async def _register_event_handlers(self) -> None:
        """
        Enregistre l'engine et les agents spéciaux comme sources sur l'EventBus,
        puis souscrit aux canaux pertinents.

        FIX v2 :
          - Méthode async (register_source et subscribe sont des coroutines)
          - L'engine reçoit son propre token
          - CyberAgent et HealerAgent reçoivent leur token via set_token()
        """
        # ── Engine ────────────────────────────────────────────────────────
        self._engine_token = await self.event_bus.register_source(
            source="engine",
            publish_channels=[],
            subscribe_channels=[
                "strategist.suggestion",
                "tool.error",
                "cyber.threat",
                "cyber.quarantine",
                "healer.threat_detected",
                "healer.file_quarantined",
            ],
        )

        await self.event_bus.subscribe(
            "strategist.suggestion", self._handle_suggestion,
            source="engine", token=self._engine_token
        )
        await self.event_bus.subscribe(
            "tool.error", self._handle_tool_error,
            source="engine", token=self._engine_token
        )
        await self.event_bus.subscribe(
            "cyber.threat", self._handle_cyber_threat,
            source="engine", token=self._engine_token
        )
        await self.event_bus.subscribe(
            "cyber.quarantine", self._handle_cyber_quarantine,
            source="engine", token=self._engine_token
        )
        await self.event_bus.subscribe(
            "healer.threat_detected", self._handle_healer_threat,
            source="engine", token=self._engine_token
        )
        await self.event_bus.subscribe(
            "healer.file_quarantined", self._handle_healer_quarantine,
            source="engine", token=self._engine_token
        )

        # ── CyberAgent ────────────────────────────────────────────────────
        cyber_token = await self.event_bus.register_source(
            source="cyber_agent",
            publish_channels=["cyber.threat", "cyber.quarantine", "cyber.emerging_pattern"],
            subscribe_channels=["tool.error", "agent.error", "system.anomaly"],
        )
        self.cyber_agent.set_token(cyber_token)

        # ── HealerAgent ───────────────────────────────────────────────────
        healer_token = await self.event_bus.register_source(
            source="HealerAgent",
            publish_channels=["healer.threat_detected", "healer.file_quarantined", "tool.error"],
            subscribe_channels=["file.created", "file.modified", "cyber.threat"],
        )
        self.healer_agent.set_token(healer_token)

        logger.info("✅ Engine : handlers enregistrés (engine + cyber + healer)")

    # -----------------------------------------------------------------------
    # Cycle de vie
    # -----------------------------------------------------------------------
    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Définit la boucle asyncio principale et démarre les composants async.

        FIX v2 : _register_event_handlers et les agents sont démarrés ici,
        une fois la boucle disponible.
        """
        self._loop = loop
        async def _register_then_start():
            await self._register_event_handlers()
            self.cyber_agent.set_loop(loop)
            self.healer_agent.set_loop(loop)
        loop.create_task(_register_then_start())

        if self.p2p_node:
            self.p2p_node.run_in_thread()

        logger.debug("Boucle asyncio définie")

    async def start_async(self) -> None:
        pass

    async def stop_async(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        logger.info("Arrêt du moteur en cours…")

        if self.p2p_node:
            await self.p2p_node.stop()
        await self.healer_agent.stop()
        await self.cyber_agent.stop()
        if hasattr(self.strategist, 'stop'):
            self.strategist.stop()
        if hasattr(self.profile_agent, 'stop'):
            self.profile_agent.stop()
        self.scheduler.stop()
        self.elasticity.stop()
        self.consolidation.stop()
        await self.cortex.stop()
        self.executor.shutdown()
        if hasattr(self.memory, 'close'):
            await self.memory.close()

        logger.info("Moteur arrêté")

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            asyncio.create_task(self.stop_async())
        else:
            asyncio.run(self.stop_async())

    # -----------------------------------------------------------------------
    # Traitement des requêtes
    # -----------------------------------------------------------------------
    async def _process_async_core(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        # Enrichir le system prompt avec les souvenirs RAG pertinents
        enriched_system = system_prompt
        if self.rag.active:
            memories = self.rag.search_memories(query, n_results=3)
            if memories:
                memory_ctx = "\n".join(
                    f"- Souvenir: Q: {m['query']} → R: {m['response'][:150]}"
                    for m in memories
                    if m.get("query")
                )
                if memory_ctx:
                    prefix = (
                        "Voici des souvenirs pertinents de conversations passées :\n"
                        f"{memory_ctx}\n\n"
                        "Utilise ces souvenirs pour contextualiser ta réponse.\n"
                    )
                    enriched_system = (
                        f"{prefix}{system_prompt}" if system_prompt else prefix
                    )
                    logger.info(f"🧠 {len(memories)} souvenirs RAG injectés")

        response, latency = await self.cortex.think(
            query, system_prompt=enriched_system, allow_web_search=allow_web_search
        )

        # Indexer la conversation dans le RAG pour les futures recherches
        if self.rag.active and response and not response.startswith("Erreur"):
            self.rag.index_conversation(query, response, time.time())

        return response, latency

    def process(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        use_rag: bool = True,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        start = time.time()
        logger.info(f"⚙️ Engine.process() — {query[:50]}…")

        if use_rag:
            self.rag.query(query)

        if self._loop is None:
            raise RuntimeError("set_loop() doit être appelé avant process().")

        future = asyncio.run_coroutine_threadsafe(
            self._process_async_core(query, system_prompt, allow_web_search),
            self._loop,
        )

        try:
            raw_response, _ = future.result(timeout=120)
        except Exception as e:
            future.cancel()
            logger.error(f"Erreur process: {e}")
            return f"Erreur: {e}", time.time() - start

        action_executed, final_response = self.action_router.parse_and_execute(raw_response)
        latency = time.time() - start
        logger.debug("engine.process_latency", latency)
        return final_response, latency

    async def process_async(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        use_rag: bool = True,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        start = time.time()
        logger.info(f"⚙️ Engine.process_async() — {query[:50]}…")

        if use_rag:
            self.rag.query(query)

        try:
            raw_response, _ = await self._process_async_core(
                query, system_prompt, allow_web_search
            )
        except Exception as e:
            logger.error(f"Erreur process_async: {e}")
            return f"Erreur: {e}", time.time() - start

        action_executed, final_response = self.action_router.parse_and_execute(raw_response)
        latency = time.time() - start
        logger.debug("engine.process_async_latency", latency)
        return final_response, latency

    # -----------------------------------------------------------------------
    # RAG
    # -----------------------------------------------------------------------
    def index_file(self, path: str) -> bool:
        return self.rag.index_file(path)

    def index_folder(self, path: str) -> int:
        return self.rag.index_folder(path)

    # -----------------------------------------------------------------------
    # Handlers d'événements
    # FIX v2 : tous reçoivent un objet Event — on extrait .data et .source
    # -----------------------------------------------------------------------
    async def _handle_suggestion(self, event: Event) -> None:
        """Réagit aux suggestions du StrategistAgent."""
        try:
            data = event.data if isinstance(event.data, dict) else {}
            logger.info(f"💡 Suggestion : {data.get('title', 'sans titre')}")
            cron = data.get("cron_expression")
            query = data.get("query")
            if cron and query:
                self.scheduler.add_cron_job(
                    func=self._execute_scheduled_query,
                    cron_expr=cron,
                    job_id=f"auto_{data.get('title', 'task')[:20]}",
                    kwargs={"query": query},
                )
                logger.info(f"📅 Tâche auto ajoutée : {data.get('title')}")
        except Exception as e:
            logger.error(f"_handle_suggestion: {e}")

    async def _handle_tool_error(self, event: Event) -> None:
        """Log les erreurs d'outils et met à jour les métriques."""
        try:
            data = event.data if isinstance(event.data, dict) else {}
            tool = data.get("tool")
            agent = data.get("agent")
            code = data.get("code", "UNKNOWN")
            message = data.get("message", "")
            suggestion = data.get("suggestion", "")

            logger.error(f"❌ [{code}] Agent: {agent}, Outil: {tool} — {message}")
            if suggestion:
                logger.info(f"💡 {suggestion}")
        except Exception as e:
            logger.error(f"_handle_tool_error: {e}")

    async def _handle_cyber_threat(self, event: Event) -> None:
        """Propage les alertes cyber (log + P2P si actif)."""
        try:
            data = event.data if isinstance(event.data, dict) else {}
            pattern = data.get('pattern', 'inconnue')
            severity = data.get('severity', 0)
            count = data.get('count', 0)
            affected = data.get('affected_agents', [])
            solution = data.get('solution', 'Aucune solution connue')

            logger.warning(
                f"🔥 CYBER — {pattern} | "
                f"sévérité {severity:.2f}, {count} occ., agents: {affected}"
            )
            if solution:
                logger.info(f"   Solution : {solution}")

            if self.p2p_node:
                await self.p2p_node.broadcast_threat(data)
        except Exception as e:
            logger.error(f"_handle_cyber_threat: {e}")

    async def _handle_cyber_quarantine(self, event: Event) -> None:
        """Log les mises en quarantaine cyber."""
        try:
            data = event.data if isinstance(event.data, dict) else {}
            agent = data.get('agent', '?')
            tool = data.get('tool', '?')
            until = data.get('until', 0)
            until_str = time.ctime(until) if until else 'indéfiniment'
            logger.error(f"⛔ QUARANTAINE — {agent}:{tool} jusqu'à {until_str}")
        except Exception as e:
            logger.error(f"_handle_cyber_quarantine: {e}")

    async def _handle_healer_threat(self, event: Event) -> None:
        """Log les menaces détectées par HealerAgent."""
        try:
            data = event.data if isinstance(event.data, dict) else {}
            filepath = data.get('filepath', '?')
            threat_name = data.get('threat_name', 'inconnue')
            severity = data.get('severity', 0)
            logger.warning(f"🩺 HEALER — {filepath} : {threat_name} (sév. {severity:.2f})")
        except Exception as e:
            logger.error(f"_handle_healer_threat: {e}")

    async def _handle_healer_quarantine(self, event: Event) -> None:
        """Log les quarantaines de fichiers par HealerAgent."""
        try:
            data = event.data if isinstance(event.data, dict) else {}
            original = data.get('original', '?')
            quarantine = data.get('quarantine_path', '?')
            threat = data.get('threat', 'inconnue')
            logger.info(f"📦 HEALER — {original} → {quarantine} (menace: {threat})")
        except Exception as e:
            logger.error(f"_handle_healer_quarantine: {e}")

    async def _execute_scheduled_query(self, query: str) -> None:
        logger.info(f"⏰ Exécution programmée : {query}")
        try:
            response, latency = await self.process_async(query, use_rag=False)
            logger.info(f"✅ {response[:100]}… ({latency:.2f}s)")
        except Exception as e:
            logger.error(f"❌ Programmée échouée : {e}")
from app.utils.metrics import start_metrics_server
