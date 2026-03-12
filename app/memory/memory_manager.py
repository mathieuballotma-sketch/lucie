"""
Memory Manager - Gère le contexte utilisateur en combinant mémoire court terme et long terme.
Version avec persistance des routines et préférences.
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from app.memory import MemoryService
from app.utils.logger import logger


class MemoryManager:
    def __init__(self, memory_service: MemoryService, config: dict):
        self.memory = memory_service
        self.max_short_term = config.get("max_short_term", 5)
        self.max_long_term = config.get("max_long_term", 3)
        self.workspace_dir = Path(config.get("workspace_dir", "~/AgentLucide/workspace")).expanduser()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.routines_file = self.workspace_dir / "routines.json"
        self.preferences_file = self.workspace_dir / "preferences.json"
        self.routines = self._load_routines()
        self.preferences = self._load_preferences()

    def _load_routines(self) -> Dict[str, Any]:
        if self.routines_file.exists():
            try:
                return json.loads(self.routines_file.read_text())
            except Exception as e:
                logger.error(f"Erreur chargement routines: {e}")
        return {}

    def _save_routines(self):
        try:
            self.routines_file.write_text(json.dumps(self.routines, indent=2))
        except Exception as e:
            logger.error(f"Erreur sauvegarde routines: {e}")

    def _load_preferences(self) -> Dict[str, Any]:
        if self.preferences_file.exists():
            try:
                return json.loads(self.preferences_file.read_text())
            except Exception as e:
                logger.error(f"Erreur chargement préférences: {e}")
        return {}

    def _save_preferences(self):
        try:
            self.preferences_file.write_text(json.dumps(self.preferences, indent=2))
        except Exception as e:
            logger.error(f"Erreur sauvegarde préférences: {e}")

    async def get_context(self, user_id: str, query: str) -> str:
        """
        Récupère le contexte pertinent pour la requête.
        Inclut les routines actives et les préférences.
        """
        context_parts = []

        # Mémoire à court terme
        short_term = self.memory.get_working_context(n=self.max_short_term)
        if short_term:
            context_parts.append(f"Conversation récente:\n{short_term}")

        # Mémoire à long terme
        long_term_results = await self.memory.remember(query, n_results=self.max_long_term)
        if long_term_results:
            memories = []
            for res in long_term_results:
                response = res.get('response') or res.get('content') or str(res)
                memories.append(response)
            context_parts.append(f"Souvenirs pertinents:\n" + "\n".join(memories))

        # Routines (ex: "tous les matins, ouvre Notes")
        if self.routines:
            routines_text = "\n".join([f"- {k}: {v}" for k, v in self.routines.items()])
            context_parts.append(f"Routines actives:\n{routines_text}")

        # Préférences utilisateur
        if self.preferences:
            prefs_text = "\n".join([f"- {k}: {v}" for k, v in self.preferences.items()])
            context_parts.append(f"Préférences:\n{prefs_text}")

        return "\n\n".join(context_parts) if context_parts else ""

    def add_routine(self, name: str, cron_expr: str, action: str):
        """Ajoute une routine périodique."""
        self.routines[name] = {"cron": cron_expr, "action": action, "created": time.time()}
        self._save_routines()
        logger.info(f"Routine ajoutée: {name}")

    def remove_routine(self, name: str):
        if name in self.routines:
            del self.routines[name]
            self._save_routines()

    def set_preference(self, key: str, value: Any):
        self.preferences[key] = value
        self._save_preferences()