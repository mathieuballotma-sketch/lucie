"""
Moteur principal de l'application.
Coordonne le cortex, les services, la mémoire et les agents.
Intègre désormais l'agent Cyber et le réseau P2P simplifié.
Ajoute un souscripteur aux erreurs d'outils pour les logger.
Ajoute des écouteurs pour les événements cyber.
"""

import asyncio
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional, Tuple

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

from ..agents.cyber_agent import CyberAgent
from ..agents.profile_agent import ProfileAgent
from ..agents.strategist_agent import StrategistAgent
from ..core.config import Config
from ..core.elasticity import ElasticityEngine
from ..memory import ConsolidationEngine, EpisodicMemory, MemoryService, WorkingMemory
from ..p2p.node import P2PNode
from ..providers.manager import ProviderManager
from ..utils.logger import logger
from ..utils.memory_monitor import monitor_memory
from ..utils.metrics import start_metrics_server


class LucidEngine:
    def __init__(self, config: Config):
        self.config = config
        self.bus = SynapseBus()
        self.event_bus = EventBus()

        if config.metrics.enabled:
            start_metrics_server(port=config.metrics.port)
            monitor_memory(interval=config.metrics.memory_interval)

        self._init_llm()

        data_dir = Path(config.app.data_dir)
        self.executor = TaskExecutor(max_workers=3, persist_path=data_dir / "tasks.pkl")
        self.prompt_cache = PromptCache(cache_dir=data_dir / "cache", max_size=10000)
        self.ollama_circuit = CircuitBreaker(
            "ollama", failure_threshold=3, recovery_timeout=30
        )

        # Chiffrement
        self.crypto = CryptoManager()

        # Mémoire
        episodic = EpisodicMemory(
            persist_directory=str(data_dir / "episodic"),
            max_entries=config.memory.max_episodic,
        )
        working = WorkingMemory(capacity=config.memory.working_capacity)
        self.memory = MemoryService(episodic, working)

        # Consolidation
        self.consolidation = ConsolidationEngine(
            episodic, interval=config.memory.consolidation_interval
        )
        if config.memory.auto_consolidate:
            self.consolidation.start()

        # Élasticité
        self.elasticity = ElasticityEngine(asdict(config.elasticity))
        self.elasticity.start()

        # RAG
        self.rag = RAGService(config.rag)

        # Actions système
        self.system_actions = SystemActions()
        self.writer_agent = WriterAgent(str(config.actions.word_output_dir))
        self.action_router = ActionRouter(self.system_actions, self.writer_agent)

        # Cortex
        self.cortex = FrontalCortex(
            manager=self.manager,
            bus=self.bus,
            event_bus=self.event_bus,
            prompt_cache=self.prompt_cache,
            memory_service=self.memory,
            elasticity_engine=self.elasticity,
            config={
                "web_search": True,
                "api_keys": asdict(config.api_keys),
                "vision": asdict(config.vision),
                "enable_memory": True,
                "enable_elasticity": True,
                "plan_timeout": 30.0,
                "max_plan_retries": 1,
                "retrain_classifier": False,
                "enable_circuit_breaker": True,
            },
        )

        # ProfileAgent
        self.profile_agent = ProfileAgent(
            llm_service=self.manager,
            bus=self.bus,
            memory_service=self.memory,
            rag_service=self.rag,
            config=asdict(config),
        )
        self.profile_agent.start()

        # Scheduler et Strategist
        self.scheduler = SchedulerService()
        self.strategist = StrategistAgent(
            llm_service=self.manager,
            bus=self.bus,
            event_bus=self.event_bus,
            memory_service=self.memory,
            config=asdict(config),
        )
        self.scheduler.start()
        self.scheduler.add_cron_job(
            func=self.strategist.run_periodic_review,
            cron_expr="0 * * * *",
            job_id="strategist_review",
        )

        # Agent Cyber
        self.cyber_agent = CyberAgent(
            llm_service=self.manager,
            bus=self.bus,
            event_bus=self.event_bus,
            config=asdict(config),
            memory_service=self.memory,
        )
        # Connecter l'event_bus aux agents
        for agent in self.cortex.agents.values():
            agent.event_bus = self.event_bus

        # Souscrire aux suggestions
        self.event_bus.subscribe("strategist.suggestion", self._handle_suggestion)

        # Souscrire aux erreurs d'outils
        self.event_bus.subscribe("tool.error", self._handle_tool_error)

        # Souscrire aux événements cyber
        self.event_bus.subscribe("cyber.threat", self._handle_cyber_threat)
        self.event_bus.subscribe("cyber.quarantine", self._handle_cyber_quarantine)

        # Réseau P2P
        if hasattr(config, "p2p") and config.p2p.enabled:
            self.p2p_node = P2PNode(
                config=asdict(config.p2p), crypto=self.crypto, event_bus=self.event_bus
            )
            self.p2p_node.run_in_thread()
            # Connecter l'agent cyber au P2P pour diffuser les menaces
            self.event_bus.subscribe("cyber.threat", self._p2p_broadcast_threat)
        else:
            self.p2p_node = None

        # Boucle asyncio (sera définie plus tard par l'interface)
        self._loop = None

        logger.info(
            "✅ Moteur Lucide initialisé avec mémoire, élasticité, profil, scheduler, stratège, cyber et P2P"
        )

    def _init_llm(self):
        models_config = {}
        for key, m in self.config.llm.models.items():
            models_config[key] = asdict(m)
        self.manager = ProviderManager(
            {
                "host": self.config.llm.host,
                "models": models_config,
                "timeout": self.config.llm.timeout,
                "retry_attempts": self.config.llm.retry_attempts,
                "retry_delay": self.config.llm.retry_delay,
                "keep_alive": self.config.llm.keep_alive,
            }
        )

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Définit la boucle asyncio principale (à appeler après le démarrage de la boucle)."""
        self._loop = loop
        # Propager à l'agent cyber
        if hasattr(self, 'cyber_agent'):
            self.cyber_agent.set_loop(loop)

    async def _process_async_core(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        """Cœur asynchrone de process, appelé depuis le thread via run_coroutine_threadsafe."""
        return await self.cortex.think(
            query,
            system_prompt=system_prompt,
            allow_web_search=allow_web_search,
        )

    def process(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        use_rag: bool = True,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        """
        Version synchrone destinée à être appelée depuis un thread.
        Utilise run_coroutine_threadsafe avec la boucle stockée.
        """
        start = time.time()
        logger.info(f"⚙️ Engine.process() - Requête: {query[:50]}...")

        if use_rag:
            self.rag.query(query)  # synchrone

        if self._loop is None:
            raise RuntimeError("La boucle asyncio n'a pas été définie. Appeler set_loop() d'abord.")

        future = asyncio.run_coroutine_threadsafe(
            self._process_async_core(query, system_prompt, allow_web_search),
            self._loop,
        )

        try:
            # Timeout réduit à 30s (au lieu de 60)
            raw_response, _ = future.result(timeout=30)
        except Exception as e:
            # Annuler la future pour éviter qu'elle continue en arrière-plan
            future.cancel()
            logger.error(f"Erreur après circuit breaker: {e}")
            return f"Erreur de communication avec le LLM: {e}", time.time() - start

        action_executed, final_response = self.action_router.parse_and_execute(
            raw_response
        )

        latency = time.time() - start
        if action_executed:
            logger.info(f"Action exécutée en {latency:.2f}s")
        else:
            logger.info(f"Réponse générée en {latency:.2f}s")

        return final_response, latency

    async def process_async(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        use_rag: bool = True,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        """
        Version asynchrone pour être appelée directement depuis une coroutine.
        """
        start = time.time()
        logger.info(f"⚙️ Engine.process_async() - Requête: {query[:50]}...")

        if use_rag:
            self.rag.query(query)  # synchrone, à améliorer éventuellement

        try:
            raw_response, _ = await self._process_async_core(query, system_prompt, allow_web_search)
        except Exception as e:
            logger.error(f"Erreur: {e}")
            return f"Erreur: {e}", time.time() - start

        action_executed, final_response = self.action_router.parse_and_execute(
            raw_response
        )

        latency = time.time() - start
        if action_executed:
            logger.info(f"Action exécutée en {latency:.2f}s")
        else:
            logger.info(f"Réponse générée en {latency:.2f}s")

        return final_response, latency

    def index_file(self, path: str) -> bool:
        return self.rag.index_file(path)

    def index_folder(self, path: str) -> int:
        return self.rag.index_folder(path)

    def _handle_suggestion(self, data, event_id, source):
        logger.info(f"💡 Réception suggestion: {data.get('title', 'sans titre')}")
        cron = data.get("cron_expression")
        query = data.get("query")
        if cron and query:
            try:
                from croniter import croniter

                if not croniter.is_valid(cron):
                    logger.warning(f"Expression cron invalide: {cron}")
                    return
            except ImportError:
                pass
            self.scheduler.add_cron_job(
                func=self._execute_scheduled_query,
                cron_expr=cron,
                job_id=f"auto_{data.get('title', 'task')[:20]}",
                kwargs={"query": query},
            )
            logger.info(f"📅 Tâche automatique ajoutée: {data.get('title')}")
        else:
            logger.debug("Suggestion sans cron/query, ignorée")

    def _handle_tool_error(self, data, event_id, source):
        """
        Callback pour les événements tool.error.
        Logge l'erreur de manière structurée.
        """
        tool = data.get("tool")
        agent = data.get("agent")
        code = data.get("code", "UNKNOWN")
        message = data.get("message", "")
        suggestion = data.get("suggestion", "")

        logger.error(
            f"❌ Erreur outil [{code}] - Agent: {agent}, Outil: {tool} - {message}"
        )
        if suggestion:
            logger.info(f"💡 Suggestion: {suggestion}")

    def _handle_cyber_threat(self, data, event_id, source):
        """Callback pour les alertes de menace cyber."""
        pattern = data.get('pattern', 'inconnue')
        severity = data.get('severity', 0)
        count = data.get('count', 0)
        affected = data.get('affected_agents', [])
        solution = data.get('solution', 'Aucune solution connue')

        logger.warning(f"🔥 ALERTE CYBER - Menace détectée : {pattern}")
        logger.warning(f"   Sévérité : {severity:.2f}, Occurrences : {count}, Agents affectés : {affected}")
        if solution:
            logger.info(f"   Solution suggérée : {solution}")

    def _handle_cyber_quarantine(self, data, event_id, source):
        """Callback pour les mises en quarantaine."""
        agent = data.get('agent', '?')
        tool = data.get('tool', '?')
        until = data.get('until', 0)
        until_str = time.ctime(until) if until else 'indéfiniment'

        logger.error(f"⛔ QUARANTAINE - Outil {agent}:{tool} mis en quarantaine jusqu'à {until_str}")

    async def _execute_scheduled_query(self, query: str):
        logger.info(f"⏰ Exécution programmée: {query}")
        try:
            response, latency = await self.process_async(query, use_rag=False)
            logger.info(f"✅ Résultat: {response[:100]}... (latence {latency:.2f}s)")
        except Exception as e:
            logger.error(f"❌ Erreur exécution programmée: {e}")

    async def _p2p_broadcast_threat(self, data, event_id, source):
        """Relaye une menace de l'agent cyber vers le réseau P2P."""
        if self.p2p_node:
            await self.p2p_node.broadcast_threat(data)

    def stop(self):
        self.executor.shutdown()
        self.cortex.stop()
        self.consolidation.stop()
        self.elasticity.stop()
        self.profile_agent.stop()
        if hasattr(self, "scheduler"):
            self.scheduler.stop()
        if hasattr(self, "cyber_agent"):
            self.cyber_agent.stop()
        if hasattr(self, "p2p_node"):
            asyncio.run(self.p2p_node.stop())
        logger.info("Moteur arrêté.")