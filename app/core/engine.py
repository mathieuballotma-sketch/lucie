"""
Moteur principal de l'application.
Coordonne le cortex, les services, la mémoire et les agents.
Intègre désormais l'agent Cyber, le réseau P2P simplifié, l'agent Healer,
le Memory Manager, le Planner Agent et le Scheduler.
Ajoute des souscripteurs pour les erreurs d'outils et les événements cyber.
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
from app.services.scheduler_service import SchedulerService  # Ajout
from app.utils.circuit_breaker import CircuitBreaker
from app.utils.crypto import CryptoManager

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

        # Scheduler (pour les tâches périodiques et l'autonomie)
        self.scheduler = SchedulerService()
        self.scheduler.start()

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
                "max_short_term": getattr(config.memory, "max_short_term", 5),
                "max_long_term": getattr(config.memory, "max_long_term", 3),
                "max_plan_steps": getattr(config.planner, "max_plan_steps", 5),
            },
        )

        # Memory Manager
        self.memory_manager = MemoryManager(self.memory, asdict(config))

        # ProfileAgent
        self.profile_agent = ProfileAgent(
            llm_service=self.manager,
            bus=self.bus,
            memory_service=self.memory,
            rag_service=self.rag,
            config=asdict(config),
        )
        self.profile_agent.start()

        # Strategist
        self.strategist = StrategistAgent(
            llm_service=self.manager,
            bus=self.bus,
            event_bus=self.event_bus,
            memory_service=self.memory,
            config=asdict(config),
        )
        # Planifier l'analyse stratégique toutes les heures
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

        # Agent Healer
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

        # Planner Agent
        self.planner_agent = PlannerAgent(self.manager, self.bus, asdict(config))
        # On lui donne accès à tous les agents
        self.planner_agent.set_agents(self.cortex.agents)

        # Connecter l'event_bus aux agents du cortex
        for agent in self.cortex.agents.values():
            agent.event_bus = self.event_bus

        # Souscrire aux suggestions
        self.event_bus.subscribe("strategist.suggestion", self._handle_suggestion)

        # Souscrire aux erreurs d'outils
        self.event_bus.subscribe("tool.error", self._handle_tool_error)

        # Souscrire aux événements cyber
        self.event_bus.subscribe("cyber.threat", self._handle_cyber_threat)
        self.event_bus.subscribe("cyber.quarantine", self._handle_cyber_quarantine)

        # Souscrire aux événements healer
        self.event_bus.subscribe("healer.threat_detected", self._handle_healer_threat)
        self.event_bus.subscribe("healer.file_quarantined", self._handle_healer_quarantine)

        # Réseau P2P
        if hasattr(config, "p2p") and config.p2p.enabled:
            data_dir_p2p = data_dir / "p2p"
            self.p2p_node = P2PNode(
                config=asdict(config.p2p),
                crypto=self.crypto,
                event_bus=self.event_bus,
                data_dir=data_dir_p2p
            )
            self.p2p_node.run_in_thread()
            self.event_bus.subscribe("cyber.threat", self._p2p_broadcast_threat)
        else:
            self.p2p_node = None

        # Boucle asyncio (sera définie plus tard par l'interface)
        self._loop = None

        logger.info(
            "✅ Moteur Lucide initialisé avec mémoire, élasticité, profil, scheduler, stratège, cyber, healer, planner et P2P"
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
        if hasattr(self, 'cyber_agent'):
            self.cyber_agent.set_loop(loop)
        if hasattr(self, 'healer_agent'):
            self.healer_agent.set_loop(loop)

    async def _process_async_core(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
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
        start = time.time()
        logger.info(f"⚙️ Engine.process_async() - Requête: {query[:50]}...")

        if use_rag:
            self.rag.query(query)

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
        agent = data.get('agent', '?')
        tool = data.get('tool', '?')
        until = data.get('until', 0)
        until_str = time.ctime(until) if until else 'indéfiniment'

        logger.error(f"⛔ QUARANTAINE - Outil {agent}:{tool} mis en quarantaine jusqu'à {until_str}")

    def _handle_healer_threat(self, data, event_id, source):
        filepath = data.get('filepath', '?')
        threat_name = data.get('threat_name', 'inconnue')
        severity = data.get('severity', 0)

        logger.warning(f"🩺 HEALER - Menace détectée dans {filepath} : {threat_name} (sévérité {severity:.2f})")

    def _handle_healer_quarantine(self, data, event_id, source):
        original = data.get('original', '?')
        quarantine = data.get('quarantine_path', '?')
        threat = data.get('threat', 'inconnue')

        logger.info(f"📦 HEALER - Fichier mis en quarantaine : {original} -> {quarantine} (menace: {threat})")

    async def _execute_scheduled_query(self, query: str):
        logger.info(f"⏰ Exécution programmée: {query}")
        try:
            response, latency = await self.process_async(query, use_rag=False)
            logger.info(f"✅ Résultat: {response[:100]}... (latence {latency:.2f}s)")
        except Exception as e:
            logger.error(f"❌ Erreur exécution programmée: {e}")

    async def _p2p_broadcast_threat(self, data, event_id, source):
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
        if hasattr(self, "healer_agent"):
            asyncio.create_task(self.healer_agent.stop())
        if hasattr(self, "p2p_node"):
            asyncio.run(self.p2p_node.stop())
        logger.info("Moteur arrêté.")