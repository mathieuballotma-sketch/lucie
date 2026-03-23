"""
Soul Agent - Gère la persistance de l'état et des objectifs à long terme de l'agent.
Inspiré de SOUL.md et MEMORY.md d'OpenClaw.
"""

from pathlib import Path
from typing import Any, Optional, List

from app.agents.base_agent import BaseAgent
from app.utils.logger import logger


class SoulAgent(BaseAgent):
    """
    Agent responsable de la persistance des objectifs, routines et de l'identité.
    """

    def __init__(self, llm_service: Any, bus: Any, event_bus: Any, config: dict[str, Any], memory_service: Any = None) -> None:
        super().__init__("SoulAgent", llm_service, bus)
        self.event_bus = event_bus
        self.memory = memory_service
        self.soul_dir = Path(config.get("soul_dir", "~/.agent_lucie/soul")).expanduser()
        self.soul_dir.mkdir(parents=True, exist_ok=True)

        # Fichiers de persistance
        self.soul_file = self.soul_dir / "SOUL.md"
        self.memory_file = self.soul_dir / "MEMORY.md"
        self.heartbeat_file = self.soul_dir / "HEARTBEAT.md"

        self._load_soul()

    def _load_soul(self) -> None:
        """Charge l'identité et les objectifs depuis SOUL.md."""
        if self.soul_file.exists():
            with open(self.soul_file, "r") as f:
                self.soul = f.read()
            logger.info("🧠 Âme chargée depuis SOUL.md")
        else:
            self.soul = "Je suis Agent Lucie, un assistant personnel local, souverain et bienveillant."
            self._save_soul()
            logger.info("🧠 Âme initialisée")

    def _save_soul(self) -> None:
        """Sauvegarde l'identité."""
        with open(self.soul_file, "w") as f:
            f.write(self.soul)

    def get_soul(self) -> str:
        """Retourne l'identité de l'agent."""
        return self.soul

    def set_soul(self, text: str) -> None:
        """Modifie l'identité."""
        self.soul = text
        self._save_soul()
        logger.info("🧠 Âme mise à jour")

    def log_memory(self, entry: str) -> None:
        """Ajoute une entrée dans MEMORY.md."""
        with open(self.memory_file, "a") as f:
            f.write(f"- {entry}\n")
        logger.debug("📝 Entrée mémoire ajoutée")

    def get_memories(self) -> List[str]:
        """Récupère toutes les entrées mémoire."""
        if not self.memory_file.exists():
            return []
        with open(self.memory_file, "r") as f:
            lines = f.readlines()
        return [line.strip("- ").strip() for line in lines if line.startswith("- ")]

    def get_heartbeat(self) -> Optional[str]:
        """Récupère la routine heartbeat si définie."""
        if self.heartbeat_file.exists():
            with open(self.heartbeat_file, "r") as f:
                return f.read()
        return None

    def set_heartbeat(self, routine: str) -> None:
        """Définit la routine heartbeat."""
        with open(self.heartbeat_file, "w") as f:
            f.write(routine)
        logger.info("❤️ Heartbeat mis à jour")

    def can_handle(self, query: str) -> bool:
        return False  # Ne gère pas directement les requêtes

    async def handle(self, query: str) -> str:
        return "Agent d'âme non destiné à un usage direct."
