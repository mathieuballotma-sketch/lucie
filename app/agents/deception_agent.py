"""
Deception Agent - Agent de leurre et de déception.
Crée des leurres pour piéger les attaquants et collecter des informations.
"""

import asyncio
import os
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List
import json

from app.agents.base_agent import BaseAgent, Tool
from app.deception.lures import LureGenerator
from app.deception.tracker import LureTracker
from app.deception.database import AttackerDatabase
from app.utils.logger import logger
from app.utils.errors import ToolExecutionError


class DeceptionAgent(BaseAgent):
    """
    Agent capable de créer des leurres et de surveiller les interactions.
    """

    def __init__(self, llm_service, bus, event_bus, config: dict, memory_service=None):
        super().__init__("DeceptionAgent", llm_service, bus)
        self.event_bus = event_bus
        self.memory = memory_service

        # Configuration
        self.lures_dir = Path(config.get("lures_dir", "~/AgentLucide/lures")).expanduser()
        self.tracker_db = Path(config.get("tracker_db", "~/.agent_lucide/lure_tracker.db")).expanduser()
        self.auto_deploy = config.get("auto_deploy", True)

        # Créer les répertoires
        self.lures_dir.mkdir(parents=True, exist_ok=True)

        # Initialiser les sous-modules
        self.lure_gen = LureGenerator(config, self.lures_dir)
        self.tracker = LureTracker(config, self.tracker_db)
        self.db = AttackerDatabase(config)

        # S'abonner aux événements
        self.event_bus.subscribe("cyber.threat", self._on_cyber_threat)
        self.event_bus.subscribe("healer.threat_detected", self._on_healer_threat)
        self.event_bus.subscribe("lure.triggered", self._on_lure_triggered)

        logger.info("🎭 DeceptionAgent initialisé")

    def get_tools(self) -> list:
        return [
            Tool(
                name="deploy_lure",
                description="Déploie un leurre (fichier) dans un répertoire spécifié.",
                contract=DeployLureContract,
            ),
            Tool(
                name="list_lures",
                description="Liste les leurres actifs.",
                contract=ListLuresContract,
            ),
            Tool(
                name="get_attackers",
                description="Affiche les informations sur les attaquants détectés.",
                contract=GetAttackersContract,
            ),
        ]

    async def _on_cyber_threat(self, data: dict, event_id: str, source: str):
        """Callback quand une menace cyber est détectée."""
        if not self.auto_deploy:
            return

        # Analyser la menace pour déterminer quel type de leurre déployer
        pattern = data.get("pattern", "")
        severity = data.get("severity", 0)

        # Si la menace est assez grave, déployer un leurre
        if severity > 0.6:
            lure_type = self._choose_lure_type(pattern)
            await self._deploy_lure(lure_type, threat_data=data)

    async def _on_healer_threat(self, data: dict, event_id: str, source: str):
        """Callback quand Healer détecte une menace."""
        if not self.auto_deploy:
            return

        filepath = data.get("filepath")
        if filepath and os.path.exists(filepath):
            # Déployer un leurre à côté du fichier menaçant
            await self._deploy_lure("adjacent", target_path=filepath, threat_data=data)

    async def _on_lure_triggered(self, data: dict, event_id: str, source: str):
        """Callback quand un leurre est déclenché."""
        lure_id = data.get("lure_id")
        attacker_info = data.get("attacker", {})

        logger.warning(f"🎯 Leurre {lure_id} déclenché par {attacker_info}")

        # Enregistrer dans la base des attaquants
        self.db.add_attacker(attacker_info)

        # Publier un événement pour informer les autres agents
        self.event_bus.publish(
            "deception.attacker_identified",
            {
                "attacker": attacker_info,
                "lure_id": lure_id,
                "timestamp": time.time(),
            },
            self.name,
        )

    def _choose_lure_type(self, pattern: str) -> str:
        """Choisit le type de leurre le plus approprié."""
        if "fichier" in pattern.lower() or "file" in pattern.lower():
            return "file"
        elif "réseau" in pattern.lower() or "network" in pattern.lower():
            return "network_port"
        else:
            return "generic"

    async def _deploy_lure(self, lure_type: str, target_path: Optional[str] = None, threat_data: dict = None):
        """Déploie un leurre en fonction du type."""
        try:
            if lure_type == "file" or lure_type == "adjacent":
                # Déployer un fichier leurre
                if target_path and os.path.isdir(target_path):
                    directory = target_path
                elif target_path and os.path.isfile(target_path):
                    directory = os.path.dirname(target_path)
                else:
                    directory = str(Path.home())

                lure_path = await self.lure_gen.create_file_lure(
                    directory=directory,
                    name_hint=threat_data.get("pattern", "sensitive_data") if threat_data else None
                )
                logger.info(f"🎭 Leurre déployé: {lure_path}")

                # Enregistrer le leurre dans le tracker
                self.tracker.register_lure(lure_path, lure_type, threat_data)

            elif lure_type == "network_port":
                # Pour l'instant, on ne fait rien (implémentation future)
                logger.info("🌐 Déploiement de port réseau non implémenté")
            else:
                # Leurre générique (fichier texte)
                lure_path = await self.lure_gen.create_generic_lure(
                    directory=str(Path.home() / "Desktop")
                )
                logger.info(f"🎭 Leurre générique déployé: {lure_path}")
                self.tracker.register_lure(lure_path, "generic", threat_data)

        except Exception as e:
            logger.error(f"Erreur déploiement leurre: {e}")

    # -----------------------------------------------------------------------
    # Implémentations des outils
    # -----------------------------------------------------------------------

    async def _tool_deploy_lure(self, directory: str = None, lure_type: str = "file") -> str:
        """Outil pour déployer un leurre manuellement."""
        if directory is None:
            directory = str(Path.home())
        if not os.path.isdir(directory):
            return f"❌ Répertoire invalide: {directory}"

        if lure_type == "file":
            path = await self.lure_gen.create_file_lure(directory)
        else:
            path = await self.lure_gen.create_generic_lure(directory)

        self.tracker.register_lure(path, lure_type)
        return f"✅ Leurre déployé: {path}"

    async def _tool_list_lures(self) -> str:
        """Outil pour lister les leurres actifs."""
        lures = self.tracker.get_active_lures()
        if not lures:
            return "🎭 Aucun leurre actif."
        result = "🎭 Leurres actifs:\n"
        for lure in lures:
            result += f"  - {lure['path']} (type: {lure['type']}, déployé le {time.ctime(lure['deployed_at'])})\n"
        return result

    async def _tool_get_attackers(self) -> str:
        """Outil pour afficher les attaquants."""
        attackers = self.db.get_attackers()
        if not attackers:
            return "👤 Aucun attaquant enregistré."
        result = "👤 Attaquants détectés:\n"
        for att in attackers:
            result += f"  - IP: {att.get('ip', 'inconnue')}, "
            result += f"Signature: {att.get('signature', 'inconnue')}, "
            result += f"Première vue: {time.ctime(att.get('first_seen', 0))}\n"
        return result


# -----------------------------------------------------------------------
# Contrats Pydantic pour les outils
# -----------------------------------------------------------------------
from pydantic import BaseModel, Field

class DeployLureContract(BaseModel):
    directory: Optional[str] = Field(None, description="Répertoire où déployer le leurre")
    lure_type: str = Field("file", description="Type de leurre (file, generic, etc.)")

class ListLuresContract(BaseModel):
    pass

class GetAttackersContract(BaseModel):
    pass