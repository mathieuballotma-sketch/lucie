"""
Moteur principal de l'application.
Coordonne le cortex, les services, la mémoire et les agents.
Version refactorisée avec séparation des responsabilités et cycle de vie asynchrone.
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
from app.brain.synapses.event_bus import EventBus
from app.core.executor import TaskExecutor
from app.services.prompt_cache import PromptCache
from app.services.rag import RAGService
from app.services.scheduler_service import SchedulerService
from app.utils.circuit_breaker import CircuitBreaker
from app.utils.crypto import CryptoManager
from app.utils.logger import logger
from app.utils.memory_monitor import monitor_memory
from app.utils.metrics import MetricsCollector, start_metrics_server

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
    Gère le cycle de vie (démarrage/arrêt) et les événements.
    """

    def __init__(self, config: Config):
        """
        Initialise le moteur avec la configuration donnée.
        La boucle asyncio doit être définie ultérieurement via set_loop().
        """
        self.config = config
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stopping = False

        # Bus de communication
        self.bus = SynapseBus()
        self.event_bus = EventBus()

        # Métriques
        self.metrics = MetricsCollector()
        if config.metrics.enabled:
            start_metrics_server(port=config.metrics.port)
            monitor_memory(interval=config.metrics.memory_interval)

        # Composants de base
        self._init_llm()
        self._init_executor()
        self._init_memory()
        self._init_services()
        self._init_agents()
        self._init_cortex()
        self._init_p2p()

        # Enregistrer les handlers d'événements
        self._register_event_handlers()

        logger.info("✅ Moteur Lucide initialisé")

    # -----------------------------------------------------------------------
    # Initialisation (découpage du constructeur)
    # -----------------------------------------------------------------------
    def _init_llm(self) -> None:
        """Initialise le gestionnaire de providers LLM."""
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
        logger.debug("ProviderManager initialisé")

    def _init_executor(self) -> None:
        """Initialise l'exécuteur de tâches."""
        data_dir = Path(self.config.app.data_dir)
        self.executor = TaskExecutor(
            max_workers=3,
            persist_path=data_dir / "tasks.pkl"
        )
        logger.debug("TaskExecutor initialisé")

    def _init_memory(self) -> None:
        """Initialise les composants mémoire."""
        data_dir = Path(self.config.app.data_dir)

        episodic = EpisodicMemory(
            persist_directory=str(data_dir / "episodic"),
            max_entries=self.config.memory.max_episodic,
            metrics_collector=self.metrics,
        )

        working = WorkingMemory(capacity=self.config.memory.working_capacity)

        self.memory = MemoryService(episodic, working)

        self.memory_manager = MemoryManager(self.memory, asdict(self.config))

        self.consolidation = ConsolidationEngine(
            episodic,
            interval=self.config.memory.consolidation_interval
        )
        if self.config.memory.auto_consolidate:
            self.consolidation.start()

        logger.debug("Mémoire initialisée")

    def _init_services(self) -> None:
        """Initialise les services (cache, RAG, élasticité, scheduler)."""
        data_dir = Path(self.config.app.data_dir)

        self.prompt_cache = PromptCache(
            cache_dir=data_dir / "cache",
            max_size=10000
        )

        self.rag = RAGService(self.config.rag)

        self.elasticity = ElasticityEngine(asdict(self.config.elasticity))
        self.elasticity.start()

        self.scheduler = SchedulerService()
        self.scheduler.start()

        self.ollama_circuit = CircuitBreaker(
            "ollama",
            failure_threshold=3,
            recovery_timeout=30
        )

        self.crypto = CryptoManager()

        logger.debug("Services initialisés")

    def _init_agents(self) -> None:
        """Initialise tous les agents internes."""
        self.system_actions = SystemActions()
        self.writer_agent = WriterAgent(
            str(self.config.actions.word_output_dir)
        )
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

        self.cyber_agent = CyberAgent(
            llm_service=self.manager,
            bus=self.bus,
            event_bus=self.event_bus,
            config=asdict(self.config),
            memory_service=self.memory,
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
        )

        self.planner_agent = PlannerAgent(
            self.manager,
            self.bus,
            self.event_bus,
            asdict(self.config)
        )

        logger.debug("Agents internes initialisés")

    def _init_cortex(self) -> None:
        """Initialise le cortex frontal avec tous les agents."""
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

        # Injecter les agents du cortex au planner
        self.planner_agent.set_agents(self.cortex.agents)

        # Connecter l'event_bus aux agents du cortex
        for agent in self.cortex.agents.values():
            agent.event_bus = self.event_bus

        logger.debug("Cortex initialisé")

    def _init_p2p(self) -> None:
        """Initialise le nœud P2P si activé."""
        if hasattr(self.config, "p2p") and self.config.p2p.enabled:
            data_dir = Path(self.config.app.data_dir) / "p2p"
            self.p2p_node = P2PNode(
                config=asdict(self.config.p2p),
                crypto=self.crypto,
                event_bus=self.event_bus,
                data_dir=data_dir
            )
        else:
            self.p2p_node = None

    def _register_event_handlers(self) -> None:
        """Enregistre tous les handlers d'événements."""
        self.event_bus.subscribe("strategist.suggestion", self._handle_suggestion)
        self.event_bus.subscribe("tool.error", self._handle_tool_error)
        self.event_bus.subscribe("cyber.threat", self._handle_cyber_threat)
        self.event_bus.subscribe("cyber.quarantine", self._handle_cyber_quarantine)
        self.event_bus.subscribe("healer.threat_detected", self._handle_healer_threat)
        self.event_bus.subscribe("healer.file_quarantined", self._handle_healer_quarantine)

    # -----------------------------------------------------------------------
    # Cycle de vie
    # -----------------------------------------------------------------------
    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Définit la boucle asyncio principale.
        À appeler après le démarrage de la boucle (par l'interface).
        """
        self._loop = loop
        self.cyber_agent.set_loop(loop)
        self.healer_agent.set_loop(loop)

        if self.p2p_node:
            self.p2p_node.run_in_thread()

        logger.debug("Boucle asyncio définie")

    async def start_async(self) -> None:
        """Démarre les composants asynchrones (si nécessaire)."""
        pass

    async def stop_async(self) -> None:
        """Arrête proprement tous les composants de manière asynchrone."""
        if self._stopping:
            return
        self._stopping = True
        logger.info("Arrêt du moteur en cours...")

        if self.p2p_node:
            await self.p2p_node.stop()
        await self.healer_agent.stop()
        self.cyber_agent.stop()
        self.strategist.stop()
        self.profile_agent.stop()
        self.scheduler.stop()
        self.elasticity.stop()
        self.consolidation.stop()
        await self.cortex.stop()
        self.executor.shutdown()

        await self.memory.close()

        logger.info("Moteur arrêté")

    def stop(self) -> None:
        """Version synchrone de stop."""
        if self._loop and self._loop.is_running():
            asyncio.create_task(self.stop_async())
        else:
            logger.warning("Aucune boucle asynchrone en cours, création d'une boucle temporaire")
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
        return await self.cortex.think(query, system_prompt=system_prompt, allow_web_search=allow_web_search)

    def process(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        use_rag: bool = True,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        start = time.time()
        logger.info(f"⚙️ Engine.process() - Requête: {query[:50]}...")

        if use_rag:
            self.rag.query(query)

        if self._loop is None:
            raise RuntimeError("La boucle asyncio n'a pas été définie. Appeler set_loop() d'abord.")

        future = asyncio.run_coroutine_threadsafe(
            self._process_async_core(query, system_prompt, allow_web_search),
            self._loop,
        )

        try:
            raw_response, _ = future.result(timeout=30)
        except Exception as e:
            future.cancel()
            logger.error(f"Erreur après circuit breaker: {e}")
            self.metrics.increment("engine.process_errors")
            return f"Erreur de communication avec le LLM: {e}", time.time() - start

        action_executed, final_response = self.action_router.parse_and_execute(raw_response)

        latency = time.time() - start
        if action_executed:
            logger.info(f"Action exécutée en {latency:.2f}s")
        else:
            logger.info(f"Réponse générée en {latency:.2f}s")

        self.metrics.record_timing("engine.process_latency", latency)
        return final_response, latency

    async def process_async(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        use_rag: bool = True,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        start = time.time()
        logger.info(f"⚙️ Engine.process_async() - Requête: {query[:50]}...")

        if use_rag:
            self.rag.query(query)

        try:
            raw_response, _ = await self._process_async_core(query, system_prompt, allow_web_search)
        except Exception as e:
            logger.error(f"Erreur: {e}")
            self.metrics.increment("engine.process_async_errors")
            return f"Erreur: {e}", time.time() - start

        action_executed, final_response = self.action_router.parse_and_execute(raw_response)

        latency = time.time() - start
        if action_executed:
            logger.info(f"Action exécutée en {latency:.2f}s")
        else:
            logger.info(f"Réponse générée en {latency:.2f}s")

        self.metrics.record_timing("engine.process_async_latency", latency)
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
    # -----------------------------------------------------------------------
    async def _handle_suggestion(self, data: Dict[str, Any], event_id: str, source: str) -> None:
        try:
            logger.info(f"💡 Réception suggestion: {data.get('title', 'sans titre')}")
            cron = data.get("cron_expression")
            query = data.get("query")
            if cron and query:
                self.scheduler.add_cron_job(
                    func=self._execute_scheduled_query,
                    cron_expr=cron,
                    job_id=f"auto_{data.get('title', 'task')[:20]}",
                    kwargs={"query": query},
                )
                logger.info(f"📅 Tâche automatique ajoutée: {data.get('title')}")
        except Exception as e:
            logger.error(f"Erreur dans _handle_suggestion: {e}")

    async def _handle_tool_error(self, data: Dict[str, Any], event_id: str, source: str) -> None:
        try:
            tool = data.get("tool")
            agent = data.get("agent")
            code = data.get("code", "UNKNOWN")
            message = data.get("message", "")
            suggestion = data.get("suggestion", "")

            logger.error(f"❌ Erreur outil [{code}] - Agent: {agent}, Outil: {tool} - {message}")
            if suggestion:
                logger.info(f"💡 Suggestion: {suggestion}")
            self.metrics.increment("engine.tool_errors", {"code": code})
        except Exception as e:
            logger.error(f"Erreur dans _handle_tool_error: {e}")

    async def _handle_cyber_threat(self, data: Dict[str, Any], event_id: str, source: str) -> None:
        try:
            pattern = data.get('pattern', 'inconnue')
            severity = data.get('severity', 0)
            count = data.get('count', 0)
            affected = data.get('affected_agents', [])
            solution = data.get('solution', 'Aucune solution connue')

            logger.warning(f"🔥 ALERTE CYBER - Menace détectée : {pattern}")
            logger.warning(f"   Sévérité : {severity:.2f}, Occurrences : {count}, Agents affectés : {affected}")
            if solution:
                logger.info(f"   Solution suggérée : {solution}")

            if self.p2p_node:
                await self.p2p_node.broadcast_threat(data)
        except Exception as e:
            logger.error(f"Erreur dans _handle_cyber_threat: {e}")

    async def _handle_cyber_quarantine(self, data: Dict[str, Any], event_id: str, source: str) -> None:
        try:
            agent = data.get('agent', '?')
            tool = data.get('tool', '?')
            until = data.get('until', 0)
            until_str = time.ctime(until) if until else 'indéfiniment'

            logger.error(f"⛔ QUARANTAINE - Outil {agent}:{tool} mis en quarantaine jusqu'à {until_str}")
        except Exception as e:
            logger.error(f"Erreur dans _handle_cyber_quarantine: {e}")

    async def _handle_healer_threat(self, data: Dict[str, Any], event_id: str, source: str) -> None:
        try:
            filepath = data.get('filepath', '?')
            threat_name = data.get('threat_name', 'inconnue')
            severity = data.get('severity', 0)

            logger.warning(f"🩺 HEALER - Menace détectée dans {filepath} : {threat_name} (sévérité {severity:.2f})")
        except Exception as e:
            logger.error(f"Erreur dans _handle_healer_threat: {e}")

    async def _handle_healer_quarantine(self, data: Dict[str, Any], event_id: str, source: str) -> None:
        try:
            original = data.get('original', '?')
            quarantine = data.get('quarantine_path', '?')
            threat = data.get('threat', 'inconnue')

            logger.info(f"📦 HEALER - Fichier mis en quarantaine : {original} -> {quarantine} (menace: {threat})")
        except Exception as e:
            logger.error(f"Erreur dans _handle_healer_quarantine: {e}")

    async def _execute_scheduled_query(self, query: str) -> None:
        logger.info(f"⏰ Exécution programmée: {query}")
        try:
            response, latency = await self.process_async(query, use_rag=False)
            logger.info(f"✅ Résultat: {response[:100]}... (latence {latency:.2f}s)")
        except Exception as e:
            logger.error(f"❌ Erreur exécution programmée: {e}")
            self.metrics.increment("engine.scheduled_errors")