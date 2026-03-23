"""Registre des agents — gère l'enregistrement et le chargement dynamique."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import uuid as _uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from app.agents.base_agent import BaseAgent
from app.agents.code_debug_agent import CodeDebugAgent
from app.agents.computer_control_agent import ComputerControlAgent
from app.agents.workspace_agent import WorkspaceAgent
from app.agents.creator_agent import CreatorAgent
from app.agents.document_agent import DocumentAgent
from app.agents.feedback_agent import FeedbackAgent
from app.agents.file_agent import FileAgent
from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.smart_mail_agent import SmartMailAgent
from app.agents.calendar_agent import CalendarAgent
from app.agents.reminder_agent import ReminderAgent
from app.agents.watch_agent import WatchAgent
from app.agents.vision.text_extractor import TextExtractorAgent
from app.agents.apple_ecosystem_agent import AppleEcosystemAgent
from app.agents.deception_agent import DeceptionAgent
from app.brain.synapses.event_bus import EventBus
from ...services.web_search import WebSearch
from ...utils.logger import logger


class AgentFileHandler(FileSystemEventHandler):
    """Handler pour les événements de création/modification de fichiers dans le dossier des agents."""
    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def on_created(self, event: Any) -> None:
        if event.is_directory:
            return
        if str(event.src_path).endswith('.py'):
            self.registry.load_agent_from_file(Path(str(event.src_path)))

    def on_modified(self, event: Any) -> None:
        if event.is_directory:
            return
        if str(event.src_path).endswith('.py'):
            self.registry.load_agent_from_file(Path(str(event.src_path)))


# ── Loi d'Amdahl : identification des agents critiques ──────────────
# S = fraction séquentielle = len(CRITICAL_AGENTS) / total_agents
# Speedup_max = 1 / S
# Avec 5 critiques / 25 agents : S = 0.2 → Speedup RAM max = 5×
# Ces agents ne doivent JAMAIS être déchargés (lazy loading futur)
CRITICAL_AGENTS = frozenset({
    "ComputerControlAgent",  # Contrôle macOS — toujours prêt
    "SmartMailAgent",        # Pipeline brief du matin
    "CalendarAgent",         # Pipeline brief du matin
    "FileAgent",             # Accès fichiers — toujours prêt
    "AppleEcosystemAgent",   # Rappels, notes, actions macOS
})


class AgentRegistry:
    """Gère l'enregistrement et le chargement des agents standards et personnalisés."""

    def __init__(
        self,
        manager: Any,
        bus: Any,
        event_bus: EventBus,
        config: Dict[str, Any],
        custom_agents_dir: Path,
        cortex_token: str,
    ):
        self.manager = manager
        self.bus = bus
        self.event_bus = event_bus
        self.config = config
        self.custom_agents_dir = custom_agents_dir
        self.cortex_token = cortex_token
        self.agents: Dict[str, BaseAgent] = {}
        self.observer: Optional[Any] = None  # watchdog.observers.Observer
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._pending_registrations: List[tuple[str, str]] = []
        self._register_standard_agents()

    def _register_standard_agents(self) -> None:
        web_search = WebSearch() if self.config.get("web_search", True) else None
        agents_list: List[BaseAgent] = [
            ReminderAgent(self.manager, self.bus, {}),
            KnowledgeAgent(

                self.manager, self.bus,
                {
                    "max_results": 3,
                    "web_search": web_search,
                    "news_api_key": self.config.get("api_keys", {}).get("news_api_key"),
                },
            ),
            DocumentAgent(self.manager, self.bus, {"web_search": web_search}),
            TextExtractorAgent(self.manager, self.bus, self.config.get("vision", {})),
            ComputerControlAgent(self.manager, self.bus, {}),
            FileAgent(self.manager, self.bus, {"working_directory": str(Path.home())}),
            WorkspaceAgent(self.manager, self.bus, {}),
            AppleEcosystemAgent(self.manager, self.bus, self.config),
            CalendarAgent(self.manager, self.bus, {}),
            WatchAgent(self.manager, self.bus, {}),
            SmartMailAgent(self.manager, self.bus, {}),
            CodeDebugAgent(self.manager, self.bus, {}),
            # FeedbackAgent — boucle de rétroaction, token injecté par la boucle après
            FeedbackAgent(
                llm_service=self.manager,
                bus=self.bus,
                event_bus=self.event_bus,
                token=None,
            ),
            # DeceptionAgent — agent de leurre, NE PAS modifier deception_agent.py
            DeceptionAgent(
                llm_service=self.manager,
                bus=self.bus,
                event_bus=self.event_bus,
                config=self.config,
            ),
        ]
        available_tools = self._get_all_tool_names()
        creator = CreatorAgent(
            self.manager, self.bus, self.event_bus, self.config,
            agents_dir=self.custom_agents_dir,
            available_tools=available_tools
        )
        agents_list.append(creator)

        for agent in agents_list:
            token = str(_uuid.uuid4())
            agent.set_token(token)
            agent.event_bus = self.event_bus
            self.agents[agent.name] = agent
            self._pending_registrations.append((agent.name, token))
            logger.debug(f"Agent {agent.name} enregistré avec token {token[:8]}...")

    async def register_agents_on_bus(self) -> None:
        """Enregistre tous les agents en attente comme sources sur l'EventBus.

        Doit être appelé depuis une boucle asyncio (ex: dans set_loop ou think).
        """
        pending = getattr(self, "_pending_registrations", [])
        if not pending:
            return
        for agent_name, token in pending:
            try:
                await self.event_bus.register_source(
                    source=agent_name,
                    token=token,
                    publish_channels=["tool.error", "task.completed"],
                    subscribe_channels=[],
                )
                logger.debug(f"Agent {agent_name} enregistré sur EventBus")
            except Exception as e:
                logger.warning(f"Impossible d'enregistrer {agent_name} sur EventBus: {e}")
        self._pending_registrations = []

    def _get_all_tool_names(self) -> List[str]:
        tool_names = set()
        for agent in self.agents.values():
            for tool in agent.get_tools():
                tool_names.add(tool.name)
        return list(tool_names)

    def start_watcher(self) -> None:
        self.observer = Observer()
        handler = AgentFileHandler(self)
        observer = self.observer
        if observer is not None:
            observer.schedule(handler, str(self.custom_agents_dir), recursive=False)
            observer.start()
        logger.info(f"👀 Surveillance du dossier {self.custom_agents_dir} activée")

    def stop_watcher(self) -> None:
        if self.observer is not None:
            self.observer.stop()
            self.observer.join()

    def _publish_from_thread(self, channel: str, data: Dict[str, Any]) -> None:
        """Publie un événement depuis un thread sync (watchdog) de manière safe."""
        loop = self._loop
        if loop is None or loop.is_closed():
            logger.debug(f"Pas de boucle asyncio pour publier sur {channel}")
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.event_bus.publish(
                    channel=channel, data=data,
                    source="AgentRegistry", token=self.cortex_token,
                ),
                loop,
            )
        except Exception as e:
            logger.debug(f"Publication async échouée: {e}")

    def load_agent_from_file(self, filepath: Path) -> None:
        try:
            module_name = filepath.stem
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                logger.error(f"Impossible de charger le module {filepath}")
                return
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseAgent) and attr != BaseAgent:
                    agent_instance: BaseAgent = attr(self.manager, self.bus, self.config)
                    token = str(_uuid.uuid4())
                    agent_instance.set_token(token)
                    agent_instance.event_bus = self.event_bus
                    self.agents[agent_instance.name] = agent_instance
                    logger.info(f"✅ Agent {agent_instance.name} chargé dynamiquement depuis {filepath}")
                    self._publish_from_thread(
                        "agent.loaded", {"name": agent_instance.name}
                    )
                    return
            logger.warning(f"Aucune classe d'agent trouvée dans {filepath}")
        except Exception as e:
            logger.error(f"Erreur lors du chargement de {filepath}: {e}")
            self._publish_from_thread(
                "tool.error",
                {"agent": "AgentRegistry", "error": str(e),
                 "suggestion": "Vérifiez la syntaxe du fichier agent."},
            )

    def get_agent(self, name: str) -> BaseAgent:
        from ...utils.errors import AgentNotFoundError
        agent = self.agents.get(name)
        if not agent:
            raise AgentNotFoundError(f"Agent '{name}' introuvable")
        return agent

    def is_critical(self, agent_name: str) -> bool:
        """Retourne True si l'agent est critique (ne doit jamais être déchargé)."""
        return agent_name in CRITICAL_AGENTS

    def list_agents(self) -> List[str]:
        return list(self.agents.keys())

    def get_all_tool_names(self) -> List[str]:
        tool_names = set()
        for agent in self.agents.values():
            for tool in agent.get_tools():
                tool_names.add(tool.name)
        return list(tool_names)
