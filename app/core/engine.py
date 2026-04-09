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
import datetime
import random
import time
from dataclasses import asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
from app.utils.error_humanizer import humanize_error
from app.utils.logger import logger
from app.utils.memory_monitor import monitor_memory
from app.services.energy_manager import EnergyOrchestrator, PowerMode
from app.services.file_watcher import FileWatcher
from app.services.proactive_engine import ProactiveEngine
from app.services.search_engine import LocalSearchEngine
from app.services.time_tracker import TimeTracker
from app.utils.metrics import start_metrics_server

from ..agents.cyber_agent import CyberAgent
from ..agents.healer_agent import HealerAgent
from ..agents.profile_agent import ProfileAgent
from ..agents.strategist_agent import StrategistAgent
from ..agents.planner_agent import PlannerAgent
from ..core.config import Config
from ..core.elasticity import ElasticityEngine
from ..memory import ConsolidationEngine, ContextualMemory, EpisodicMemory, MemoryService, WorkingMemory
from ..memory.memory_manager import MemoryManager
from ..providers.manager import ProviderManager


# ─────────────────────────────────────────────────────────────────────────────
# Cache instantané pour salutations — réponse < 1ms sans LLM
# Règle CLAUDE.md : NE JAMAIS toucher _GREETING_CACHE
# ─────────────────────────────────────────────────────────────────────────────
_GREETING_CACHE: Dict[str, List[str]] = {
    "bonjour": ["Bonjour ! Comment puis-je t'aider ?", "Bonjour ! Que puis-je faire pour toi ?", "Bonjour !"],
    "bonsoir": ["Bonsoir ! Comment puis-je t'aider ?", "Bonsoir !"],
    "salut": ["Salut ! Qu'est-ce que je peux faire ?", "Salut !", "Salut, dis-moi tout !"],
    "hello": ["Hello ! How can I help?", "Hello !", "Hello, que puis-je faire ?"],
    "coucou": ["Coucou ! Quoi de neuf ?", "Coucou !", "Coucou, dis-moi !"],
    "hey": ["Hey ! Comment ça va ?", "Hey !", "Hey, je t'écoute !"],
    "hi": ["Hi ! Que puis-je faire ?", "Hi !", "Hi, je suis là !"],
    "merci": ["Avec plaisir !", "De rien !", "Je t'en prie !"],
    "au revoir": ["Au revoir !", "À bientôt !", "Salut, à plus !"],
    "bye": ["Bye !", "À plus !", "Bye bye !"],
    "bonne nuit": ["Bonne nuit !", "Dors bien !", "Bonne nuit, à demain !"],
    "ça va": ["Ça va bien, merci ! Et toi ?", "Impeccable ! Et toi ?"],
    "ca va": ["Ça va bien ! Et toi ?", "Très bien, merci !"],
    "comment vas-tu": ["Je vais très bien, merci !", "Parfait, prêt à t'aider !"],
    "comment tu vas": ["Super bien ! Que puis-je faire ?", "Très bien !"],
    "ok": ["OK ! Autre chose ?", "Bien reçu !"],
    "oui": ["D'accord ! Que veux-tu faire ?", "OK !"],
    "non": ["Pas de souci !", "D'accord !"],
    "merci beaucoup": ["Avec grand plaisir !", "De rien, c'est normal !"],
    "bonne journée": ["Bonne journée à toi aussi !", "Merci, bonne journée !"],
    "quoi de neuf": ["Pas grand-chose, je t'attends ! Que puis-je faire ?"],
}

# Seuil de similarité pour le matching flou des salutations
_GREETING_SIMILARITY_THRESHOLD = 0.75


def _check_greeting(query: str) -> Optional[str]:
    """Détecte une salutation (exacte ou floue) et retourne une réponse instantanée.

    Matching flou pour attraper les typos : bonjourr, bonojur, slaut, etc.
    Retourne None si pas une salutation → le pipeline normal prend le relais.
    """
    q = query.lower().strip().rstrip("!?.…,;: ")

    # Match exact — 0ms
    if q in _GREETING_CACHE:
        return random.choice(_GREETING_CACHE[q])

    # Match flou — < 1ms (SequenceMatcher sur ~20 clés)
    best_match: Optional[str] = None
    best_score: float = 0.0
    for key in _GREETING_CACHE:
        score = SequenceMatcher(None, q, key).ratio()
        if score > best_score:
            best_score = score
            best_match = key

    if best_match and best_score >= _GREETING_SIMILARITY_THRESHOLD:
        return random.choice(_GREETING_CACHE[best_match])

    return None


_CAPABILITY_KEYWORDS: tuple[str, ...] = (
    "qu'est-ce que tu peux faire",
    "qu est ce que tu peux faire",
    "quesque tu peut faire",
    "que peux-tu faire",
    "que peux tu faire",
    "tu peux faire quoi",
    "tu fais quoi",
    "que sais-tu faire",
    "tes capacités",
    "tes fonctions",
    "tes fonctionnalités",
    "liste tes agents",
    "c'est quoi tes agents",
    "comment tu fonctionnes",
    "tu m'aides à faire quoi",
    "tu m aides a faire quoi",
    "aide moi à comprendre",
    "quelles sont tes capacités",
    "quelles sont tes fonctions",
    "what can you do",
)

_CAPABILITY_RESPONSE = """Je suis Lucie, ton IA locale macOS. Voici ce que je peux faire :

📁 **Fichiers** — lire, écrire, organiser des fichiers et dossiers
📄 **Documents** — créer des fichiers Word, PDF ou Excel
📅 **Agenda** — ajouter des événements dans Calendrier
⏰ **Rappels** — créer des rappels dans Reminders
✉️ **Mail** — lire, classer et rédiger des emails
💻 **Contrôle macOS** — ouvrir des apps, taper du texte, capturer l'écran
🔍 **Recherche** — chercher sur le web via Safari
🧠 **Mémoire** — me souvenir de tes préférences et conversations
📝 **Code** — expliquer, déboguer et refactoriser du code
🗂️ **Multi-actions** — enchaîner plusieurs tâches en une phrase

Dis-moi ce que tu veux faire !"""


def _check_capabilities(query: str) -> Optional[str]:
    """Détecte les questions sur les capacités et retourne la liste réelle des agents."""
    q = query.lower().strip().rstrip("!?.…,;: ")
    for kw in _CAPABILITY_KEYWORDS:
        if kw in q:
            return _CAPABILITY_RESPONSE
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Fast-path questions simples — bypass pipeline lourd, réponse < 1s via E4B
# ─────────────────────────────────────────────────────────────────────────────
_SIMPLE_QUERY_MAX_WORDS = 20

# Mots-clés qui forcent le pipeline normal même si la requête semble simple
_SIMPLE_QUERY_BLACKLIST: tuple[str, ...] = (
    "rendez-vous", "calendrier", "rappel", "fichier", "mail", "email",
    "pdf", "agenda", "document",
)

# Verbes d'action système → pipeline obligatoire
_ACTION_VERBS: tuple[str, ...] = (
    "crée", "ouvre", "ouvr", "envoie", "supprime", "recherche", "résume",
    "sauvegarde", "organise", "trie", "déplace", "copie", "renomme",
    "lis", "écris", "rédige", "génère",
    "lance", "démarre", "ferme", "quitte",
)

# Mots-clés agents → pipeline obligatoire
_AGENT_KEYWORDS: tuple[str, ...] = (
    "fichier", "dossier", "mail", "email", "pdf", "word", "agenda",
    "calendrier", "rappel", "safari", "rendez-vous", "document",
    "photo", "image", "écran",
)

# Patterns multi-étapes → pipeline obligatoire
_MULTI_STEP_PATTERNS: tuple[str, ...] = ("et puis", "ensuite", "après ça")


def _is_simple_query(query: str) -> bool:
    """Détecte les questions simples qui n'ont pas besoin du pipeline lourd.

    Critères : pas de verbe d'action système, pas de mot-clé agent,
    pas de pattern multi-étapes, moins de 20 mots, et aucun mot de la blacklist.
    """
    q = query.lower().strip()

    # Trop long → pipeline normal
    if len(q.split()) >= _SIMPLE_QUERY_MAX_WORDS:
        return False

    # Blacklist explicite
    if any(kw in q for kw in _SIMPLE_QUERY_BLACKLIST):
        return False

    # Verbes d'action système
    if any(verb in q for verb in _ACTION_VERBS):
        return False

    # Mots-clés agents
    if any(kw in q for kw in _AGENT_KEYWORDS):
        return False

    # Patterns multi-étapes
    if any(pat in q for pat in _MULTI_STEP_PATTERNS):
        return False

    return True


# Requêtes brèves qui ne nécessitent pas de RAG
_BRIEF_QUERY_MAX_WORDS = 4


def _is_brief_query(query: str) -> bool:
    """Détecte les requêtes trop courtes pour bénéficier du RAG."""
    return len(query.split()) <= _BRIEF_QUERY_MAX_WORDS


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

        self._init_energy()
        self.time_tracker = TimeTracker()
        self.contextual_memory = ContextualMemory()
        self.proactive_engine: Optional[ProactiveEngine] = None
        self._init_llm()
        self._init_executor()
        self._init_memory()
        self._init_services()
        self._init_agents()
        self._init_cortex()

        # FIX v2 : _register_event_handlers est désormais async,
        # elle sera appelée depuis set_loop() via create_task.
        logger.info("✅ Moteur Lucide initialisé (handlers en attente de set_loop)")

    # -----------------------------------------------------------------------
    # Initialisation
    # -----------------------------------------------------------------------
    def _init_energy(self) -> None:
        """Initialise le gestionnaire d'energie."""
        self.energy = EnergyOrchestrator(
            energy_mode=self.config.energy.energy_mode,
            low_battery_threshold=self.config.energy.low_battery_threshold,
            power_check_interval=self.config.energy.power_check_interval,
        )
        self.energy.on_mode_change(self._on_energy_mode_change)

    def _on_energy_mode_change(self, mode: PowerMode) -> None:
        """Reagit aux changements de mode energetique."""
        energy_config = self.energy.get_energy_config()
        self.manager.set_energy_config(energy_config)

        # Basculer FAISS si necessaire
        profile = self.energy.profile
        faiss_mode = profile.get("faiss_mode", "memory")
        if hasattr(self.rag, "switch_faiss_mode"):
            self.rag.switch_faiss_mode(faiss_mode)

        # En mode CRITICAL, decharger les modeles
        if mode == PowerMode.CRITICAL:
            self.manager.unload_all_models()

        logger.info(f"Engine adapte au mode energie: {mode.value}")

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

        # Warmup silencieux du modèle nano pour pré-charger en VRAM
        try:
            self.manager.generate(
                prompt="ping",
                system="Réponds 'pong'.",
                priority="speed",
                max_tokens=4,
                temperature=0.0,
                timeout=30.0,
            )
            logger.info("🔥 Warmup E4B terminé — modèle pré-chargé en VRAM")
        except Exception as e:
            logger.warning(f"Warmup E4B échoué (non-bloquant): {e}")

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

        # Moteur de recherche local
        self.search_engine: Optional[LocalSearchEngine] = None
        self.file_watcher: Optional[FileWatcher] = None
        if self.config.search.enabled:
            self.search_engine = LocalSearchEngine(
                index_dir=self.config.search.index_dir,
                embedder=self.embedder,
                provider_manager=self.manager,
                excluded_dirs=self.config.search.excluded_dirs,
                excluded_extensions=self.config.search.excluded_extensions,
                max_file_size=self.config.search.max_file_size,
                generate_keywords=self.config.search.generate_keywords,
            )
            self.file_watcher = FileWatcher(
                self.search_engine,
                check_interval=self.config.search.watch_interval,
            )

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
            event_bus=self.event_bus,
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
                "profile": {"active": self.config.profile.active},
                "profiles": self.config.profile.profiles,
            },
        )

        # Injecter le QuantumRouter pour l'apprentissage adaptatif du routage
        from app.brain.cortex.quantum_router import QuantumRouter
        self.cortex._quantum_router = QuantumRouter()  # type: ignore[assignment]

        # FIX v2 : utiliser agent_registry.agents (et non cortex.agents qui n'existe pas)
        self.planner_agent.set_agents(self.cortex.agent_registry.agents)

        for agent in self.cortex.agent_registry.agents.values():
            agent.event_bus = self.event_bus
            agent.time_tracker = self.time_tracker

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

        # ── StrategistAgent ──────────────────────────────────────────────
        strategist_token = await self.event_bus.register_source(
            source="StrategistAgent",
            publish_channels=["strategist.suggestion"],
            subscribe_channels=[],
        )
        self.strategist.set_token(strategist_token)

        logger.info("✅ Engine : handlers enregistrés (engine + cyber + healer + strategist)")

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
        async def _register_then_start() -> None:
            await self._register_event_handlers()
            self.cyber_agent.set_loop(loop)
            self.healer_agent.set_loop(loop)
            await self.energy.start()
            self.proactive_engine = ProactiveEngine(
                contextual_memory=self.contextual_memory,
                time_tracker=self.time_tracker,
            )
            await self.proactive_engine.start()
            # Demarrer le moteur de recherche et le file watcher
            if self.file_watcher and self.search_engine:
                for watched_dir in self.config.search.watched_dirs:
                    await self.file_watcher.watch(watched_dir)
                    await self.search_engine.add_directory(watched_dir)
                await self.file_watcher.start()
        loop.create_task(_register_then_start())

        logger.debug("Boucle asyncio définie")

    async def start_async(self) -> None:
        pass

    async def stop_async(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        logger.info("Arrêt du moteur en cours…")

        if self.file_watcher:
            await self.file_watcher.stop()
        if self.search_engine:
            self.search_engine.close()
        if self.proactive_engine:
            await self.proactive_engine.stop()
        await self.energy.stop()
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
        """Arrêt sûr — jamais de asyncio.run() si une boucle tourne déjà."""
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.create_task(self.stop_async())
        else:
            try:
                asyncio.run(self.stop_async())
            except RuntimeError:
                # Boucle déjà en cours dans un autre thread — fallback
                logger.warning("Arrêt impossible via asyncio.run(), boucle déjà active")

    # -----------------------------------------------------------------------
    # Traitement des requêtes
    # -----------------------------------------------------------------------
    async def _process_async_core(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        # Enrichir le system prompt avec le contexte utilisateur
        _DEFAULT_SYSTEM = (
            "Tu es Lucie, une assistante IA locale sur macOS. "
            "Tu DOIS toujours répondre en français. Ne réponds JAMAIS en chinois, anglais ou autre langue. "
            "Sois concise et utile."
        )
        enriched_system = system_prompt if system_prompt else _DEFAULT_SYSTEM
        try:
            user_ctx = await self.contextual_memory.get_context_for_query(query)
            if user_ctx:
                ctx_parts = []
                comm = user_ctx.get("communication")
                if comm:
                    ctx_parts.append(f"Preferences communication: {comm}")
                interests = user_ctx.get("content_interests")
                if interests:
                    ctx_parts.append(f"Sujets frequents: {interests}")
                if ctx_parts:
                    ctx_str = "\n".join(ctx_parts) + "\n\n"
                    enriched_system = (
                        f"{ctx_str}{enriched_system}" if enriched_system else ctx_str
                    )
        except Exception as e:
            logger.debug(f"Contexte utilisateur indisponible: {e}")
        if self.rag.active and not _is_brief_query(query):
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

        # Détecter les tâches multi-étapes → pipeline
        if self._is_multi_step(query):
            logger.info("🔗 Tâche multi-étapes détectée → pipeline")
            try:
                pipeline_result = await self._run_pipeline(query)
                if pipeline_result:
                    # Latence recalculée par process() — pas besoin ici
                    if self.rag.active and pipeline_result:
                        self.rag.index_conversation(query, pipeline_result, time.time())
                    return pipeline_result, 0.0  # latency recalculée par process()
            except Exception as e:
                logger.warning(f"Pipeline échoué, fallback sur think(): {e}")

        response, latency = await self.cortex.think(
            query, system_prompt=enriched_system, allow_web_search=allow_web_search
        )

        # Indexer la conversation dans le RAG pour les futures recherches
        if self.rag.active and response and not response.startswith("Erreur"):
            self.rag.index_conversation(query, response, time.time())

        return response, latency

    def _is_multi_step(self, query: str) -> bool:
        """Détecte si une requête nécessite un pipeline multi-agents."""
        q = query.lower()
        # Mots-clés de chaînage
        chaining = ["puis", "ensuite", "après", "et sauvegarde", "et enregistre",
                     "et écris", "et crée un fichier", "et mets"]
        # Combinaisons d'actions (création + sauvegarde, recherche + résumé, etc.)
        multi_action = [
            ("crée" in q or "écris" in q or "rédige" in q or "génère" in q)
            and ("sauvegarde" in q or "fichier" in q or "bureau" in q or "enregistre" in q),
            ("résume" in q or "analyse" in q or "résumé" in q) and ("envoie" in q or "sauvegarde" in q),
            ("cherche" in q or "trouve" in q) and ("crée" in q or "écris" in q),
            # Recherche + résumé/synthèse (ex: "recherche X et fais un résumé")
            ("recherche" in q or "cherche" in q)
            and ("résumé" in q or "résume" in q or "synthèse" in q),
        ]
        return any(kw in q for kw in chaining) or any(multi_action)

    async def _run_pipeline(self, query: str) -> Optional[str]:
        """Décompose et exécute un pipeline multi-agents."""
        planner = self.cortex.planner
        steps = await planner.decompose(query)
        if not steps or len(steps) < 2:
            return None  # pas assez d'étapes, fallback

        result = await self.cortex.execute_pipeline(steps, timeout=120.0)
        return result

    def process(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        use_rag: bool = True,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        start = time.time()
        logger.info(f"⚙️ Engine.process() — {query[:50]}…")

        # ── Fast path salutations — < 1ms, contourne TOUT ────────────
        greeting = _check_greeting(query)
        if greeting:
            latency = time.time() - start
            logger.info(f"⚡ Salutation détectée → {latency*1000:.0f}ms")
            return greeting, latency

        # ── Fast path capacités — liste réelle des agents ─────────────
        capability_resp = _check_capabilities(query)
        if capability_resp:
            latency = time.time() - start
            logger.info(f"⚡ Question capacités détectée → {latency*1000:.0f}ms")
            return capability_resp, latency

        # ── Fast path questions simples — E4B direct < 1s ────────────
        if _is_simple_query(query):
            q_lower = query.lower()
            if any(kw in q_lower for kw in ("quelle heure", "l'heure", "il est quelle heure", "heure actuelle")):
                now = datetime.datetime.now()
                return f"Il est {now.strftime('%H:%M')}.", time.time() - start
            if any(kw in q_lower for kw in ("quel jour", "quelle date", "on est quel jour", "date aujourd'hui")):
                now = datetime.datetime.now()
                jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
                mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
                return f"On est {jours[now.weekday()]} {now.day} {mois[now.month-1]} {now.year}.", time.time() - start
            response = self.manager.generate(
                prompt=query,
                system="Tu es Lucie, une IA locale macOS. Réponds de façon concise et utile en français. Si on te demande l'heure, utilise l'heure système.",
                priority="speed",
                max_tokens=256,
                temperature=0.3,
            )
            latency = time.time() - start
            logger.info(f"⚡ Question simple → E4B direct {latency:.1f}s")
            return response, latency

        if self._loop is None:
            raise RuntimeError("set_loop() doit être appelé avant process().")

        # Timeout adaptatif : 15s simple, 60s pipeline/recherche
        effective_timeout = 120 if self._is_multi_step(query) else 45

        future = asyncio.run_coroutine_threadsafe(
            self._process_async_core(query, system_prompt, allow_web_search),
            self._loop,
        )

        try:
            raw_response, _ = future.result(timeout=effective_timeout)
        except Exception as e:
            future.cancel()
            logger.error(f"Erreur process: {e}")
            return humanize_error(f"Erreur: {e}"), time.time() - start

        action_executed, final_response = self.action_router.parse_and_execute(raw_response)
        latency = time.time() - start
        logger.debug(f"engine.process_latency: {latency:.3f}")
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

        # ── Fast path salutations — < 1ms ────────────────────────────
        greeting = _check_greeting(query)
        if greeting:
            latency = time.time() - start
            logger.info(f"⚡ Salutation détectée → {latency*1000:.0f}ms")
            return greeting, latency

        # ── Fast path capacités — liste réelle des agents ─────────────
        capability_resp = _check_capabilities(query)
        if capability_resp:
            latency = time.time() - start
            logger.info(f"⚡ Question capacités détectée → {latency*1000:.0f}ms")
            return capability_resp, latency

        # ── Fast path questions simples — E4B direct < 1s ────────────
        if _is_simple_query(query):
            q_lower = query.lower()
            if any(kw in q_lower for kw in ("quelle heure", "l'heure", "il est quelle heure", "heure actuelle")):
                now = datetime.datetime.now()
                return f"Il est {now.strftime('%H:%M')}.", time.time() - start
            if any(kw in q_lower for kw in ("quel jour", "quelle date", "on est quel jour", "date aujourd'hui")):
                now = datetime.datetime.now()
                jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
                mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
                return f"On est {jours[now.weekday()]} {now.day} {mois[now.month-1]} {now.year}.", time.time() - start
            response = self.manager.generate(
                prompt=query,
                system="Tu es Lucie, une IA locale macOS. Réponds de façon concise et utile en français. Si on te demande l'heure, utilise l'heure système.",
                priority="speed",
                max_tokens=256,
                temperature=0.3,
            )
            latency = time.time() - start
            logger.info(f"⚡ Question simple → E4B direct {latency:.1f}s")
            return response, latency

        # Timeout adaptatif : 15s simple, 60s pipeline/recherche
        effective_timeout = 120.0 if self._is_multi_step(query) else 45.0

        try:
            raw_response, _ = await asyncio.wait_for(
                self._process_async_core(
                    query, system_prompt, allow_web_search
                ),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout process_async après {effective_timeout}s")
            return humanize_error("timeout"), time.time() - start
        except Exception as e:
            logger.error(f"Erreur process_async: {e}")
            return humanize_error(f"Erreur: {e}"), time.time() - start

        action_executed, final_response = self.action_router.parse_and_execute(raw_response)
        latency = time.time() - start
        logger.debug(f"engine.process_async_latency: {latency:.3f}")
        return final_response, latency

    # -----------------------------------------------------------------------
    # RAG
    # -----------------------------------------------------------------------
    def index_file(self, path: str) -> bool:
        return self.rag.index_file(path)

    def index_folder(self, path: str) -> int:
        return self.rag.index_folder(path)

    # -----------------------------------------------------------------------
    # Recherche locale
    # -----------------------------------------------------------------------
    async def search_files(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Recherche de fichiers via le moteur de recherche local."""
        engine = self.search_engine
        if engine is None:
            return []
        return await engine.search(query, top_k=top_k)

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
