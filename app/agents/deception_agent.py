"""
Deception Agent - Agent de leurre et de déception.
Corrections v2 :
  - import time ajouté
  - event_bus.subscribe() → await (méthode async)
  - Handlers _on_* : signature (event: Event) au lieu de (data, event_id, source)
  - event_bus.publish() → await
  - threat_data: Optional[dict] au lieu de dict = None
  - Contrats Pydantic déplacés avant la classe (référencés dans get_tools)
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.base_agent import BaseAgent, Tool
from app.brain.synapses.event_bus import Event
from app.deception.lures import LureGenerator
from app.deception.tracker import LureTracker
from app.deception.database import AttackerDatabase
from app.utils.logger import logger

from pydantic.v1 import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Contrats Pydantic (AVANT la classe pour éviter NameError dans get_tools)
# ─────────────────────────────────────────────────────────────────────────────
class DeployLureContract(BaseModel):
    directory: Optional[str] = Field(None, description="Répertoire où déployer le leurre")
    lure_type: str            = Field("file", description="Type de leurre (file, generic)")

class ListLuresContract(BaseModel):
    pass

class GetAttackersContract(BaseModel):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# DeceptionAgent
# ─────────────────────────────────────────────────────────────────────────────
class DeceptionAgent(BaseAgent):
    """Agent capable de créer des leurres et de surveiller les interactions."""

    def __init__(self, llm_service: Any, bus: Any, event_bus: Any, config: Dict[str, Any], memory_service: Any = None):
        super().__init__("DeceptionAgent", llm_service, bus, event_bus=event_bus)
        self.memory = memory_service

        self.lures_dir  = Path(config.get("lures_dir",  "~/AgentLucide/lures")).expanduser()
        self.tracker_db = Path(config.get("tracker_db", "~/.agent_lucide/lure_tracker.db")).expanduser()
        self.auto_deploy = config.get("auto_deploy", True)

        self.lures_dir.mkdir(parents=True, exist_ok=True)

        self.lure_gen = LureGenerator(config, self.lures_dir)
        self.tracker  = LureTracker(config, self.tracker_db)
        self.db       = AttackerDatabase(config)

        # FIX v2 : subscribe() est async — on planifie via create_task
        # (sera appelé une fois la boucle démarrée)
        self._pending_subscriptions = True
        logger.info("🎭 DeceptionAgent initialisé (abonnements en attente de set_loop)")

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Appelé par le registre une fois la boucle disponible."""
        if self._pending_subscriptions:
            loop.create_task(self._subscribe())
            self._pending_subscriptions = False

    async def _subscribe(self) -> None:
        """Abonnements async avec token."""
        event_bus = self.event_bus
        if event_bus is None or not self.token:
            logger.error("DeceptionAgent._subscribe : event_bus ou token manquant.")
            return
        try:
            await event_bus.subscribe("cyber.threat",          self._on_cyber_threat,   source=self.name, token=self.token)
            await event_bus.subscribe("healer.threat_detected", self._on_healer_threat, source=self.name, token=self.token)
            await event_bus.subscribe("lure.triggered",         self._on_lure_triggered, source=self.name, token=self.token)
            logger.info("🎭 DeceptionAgent : abonné aux événements")
        except Exception as e:
            logger.error(f"DeceptionAgent._subscribe erreur : {e}")

    def get_tools(self) -> List[Tool]:
        return [
            Tool(name="deploy_lure",   description="Déploie un leurre dans un répertoire.",      contract=DeployLureContract),
            Tool(name="list_lures",    description="Liste les leurres actifs.",                   contract=ListLuresContract),
            Tool(name="get_attackers", description="Affiche les informations sur les attaquants.", contract=GetAttackersContract),
        ]

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in ["leurre", "lure", "déception", "attaquant", "piège"])

    # ── Handlers d'événements (FIX v2 : signature event: Event) ──────────────

    async def _on_cyber_threat(self, event: Event) -> None:
        if not self.auto_deploy:
            return
        data     = event.data if isinstance(event.data, dict) else {}
        pattern  = data.get("pattern", "")
        severity = data.get("severity", 0)
        if severity > 0.6:
            lure_type = self._choose_lure_type(pattern)
            await self._deploy_lure(lure_type, threat_data=data)

    async def _on_healer_threat(self, event: Event) -> None:
        if not self.auto_deploy:
            return
        data     = event.data if isinstance(event.data, dict) else {}
        filepath = data.get("filepath")
        if filepath and os.path.exists(filepath):
            await self._deploy_lure("adjacent", target_path=filepath, threat_data=data)

    async def _on_lure_triggered(self, event: Event) -> None:
        data          = event.data if isinstance(event.data, dict) else {}
        lure_id       = data.get("lure_id")
        attacker_info = data.get("attacker", {})

        logger.warning(f"🎯 Leurre {lure_id} déclenché par {attacker_info}")
        self.db.add_attacker(attacker_info)

        # FIX v2 : publish est async + token requis
        event_bus = self.event_bus
        if event_bus is not None and self.token:
            try:
                await event_bus.publish(
                    channel="deception.attacker_identified",
                    data={"attacker": attacker_info, "lure_id": lure_id, "timestamp": time.time()},
                    source=self.name,
                    token=self.token,
                )
            except Exception as e:
                logger.error(f"DeceptionAgent publish erreur : {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _choose_lure_type(self, pattern: str) -> str:
        if "fichier" in pattern.lower() or "file" in pattern.lower():
            return "file"
        elif "réseau" in pattern.lower() or "network" in pattern.lower():
            return "network_port"
        return "generic"

    async def _deploy_lure(
        self,
        lure_type: str,
        target_path: Optional[str] = None,
        threat_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            if lure_type in ("file", "adjacent"):
                if target_path and os.path.isdir(target_path):
                    directory = target_path
                elif target_path and os.path.isfile(target_path):
                    directory = os.path.dirname(target_path)
                else:
                    directory = str(Path.home())

                name_hint = threat_data.get("pattern", "sensitive_data") if threat_data else None
                lure_path = await self.lure_gen.create_file_lure(directory=directory, name_hint=name_hint)
                logger.info(f"🎭 Leurre déployé: {lure_path}")
                self.tracker.register_lure(lure_path, lure_type, threat_data)

            elif lure_type == "network_port":
                logger.info("🌐 Déploiement de port réseau non implémenté")
            else:
                lure_path = await self.lure_gen.create_generic_lure(
                    directory=str(Path.home() / "Desktop")
                )
                logger.info(f"🎭 Leurre générique déployé: {lure_path}")
                self.tracker.register_lure(lure_path, "generic", threat_data)

        except Exception as e:
            logger.error(f"Erreur déploiement leurre: {e}")

    # ── Outils ────────────────────────────────────────────────────────────────

    async def _tool_deploy_lure(self, directory: Optional[str] = None, lure_type: str = "file") -> str:
        dir_path = directory or str(Path.home())
        if not os.path.isdir(dir_path):
            return f"❌ Répertoire invalide: {dir_path}"
        if lure_type == "file":
            path = await self.lure_gen.create_file_lure(dir_path)
        else:
            path = await self.lure_gen.create_generic_lure(dir_path)
        self.tracker.register_lure(path, lure_type)
        return f"✅ Leurre déployé: {path}"

    async def _tool_list_lures(self) -> str:
        lures = self.tracker.get_active_lures()
        if not lures:
            return "🎭 Aucun leurre actif."
        result = "🎭 Leurres actifs:\n"
        for lure in lures:
            result += f"  - {lure['path']} (type: {lure['type']}, déployé le {time.ctime(lure['deployed_at'])})\n"
        return result

    async def _tool_get_attackers(self) -> str:
        attackers = self.db.get_attackers()
        if not attackers:
            return "👤 Aucun attaquant enregistré."
        result = "👤 Attaquants détectés:\n"
        for att in attackers:
            result += (
                f"  - IP: {att.get('ip', 'inconnue')}, "
                f"Signature: {att.get('signature', 'inconnue')}, "
                f"Première vue: {time.ctime(att.get('first_seen', 0))}\n"
            )
        return result
