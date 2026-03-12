"""
Healer Agent - Agent de guérison et de neutralisation des menaces.
Analyse les fichiers suspects, les met en quarantaine, et les neutralise.
Version avec répertoire dédié pour les leurres, nettoyage périodique et asynchrone.
"""

import asyncio
import os
import shutil
import time
import json  # <-- AJOUT
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List

import aiofiles  # <-- AJOUT
from pydantic import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.healer.scanner import FileScanner
from app.healer.analyzer import ThreatAnalyzer
from app.healer.neutralizer import ThreatNeutralizer
from app.healer.stealth import StealthMode
from app.utils.logger import logger
from app.utils.errors import ToolExecutionError


# -----------------------------------------------------------------------
# Contrats Pydantic pour les outils
# -----------------------------------------------------------------------
class ScanFileContract(BaseModel):
    filepath: str = Field(..., description="Chemin complet du fichier à scanner")

class QuarantineFileContract(BaseModel):
    filepath: str = Field(..., description="Chemin complet du fichier à mettre en quarantaine")

class RestoreFileContract(BaseModel):
    filename: str = Field(..., description="Nom du fichier à restaurer (sans chemin)")

class ListQuarantineContract(BaseModel):
    pass


class HealerAgent(BaseAgent):
    """
    Agent capable de scanner, analyser et neutraliser les fichiers malveillants.
    """

    def __init__(self, llm_service, bus, event_bus, config: dict, memory_service=None):
        super().__init__("HealerAgent", llm_service, bus)
        self.event_bus = event_bus
        self.memory = memory_service

        # Configuration
        self.quarantine_dir = Path(config.get("quarantine_dir", "~/AgentLucide/quarantine")).expanduser()
        self.lures_dir = Path(config.get("lures_dir", "~/AgentLucide/lures")).expanduser()
        self.auto_quarantine = config.get("auto_quarantine", True)
        self.stealth_mode = config.get("stealth_mode", False)
        self.lure_ttl = config.get("lure_ttl", 86400)  # 24h

        # Créer les répertoires
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.lures_dir.mkdir(parents=True, exist_ok=True)

        # Initialiser les sous-modules
        self.scanner = FileScanner(config)
        self.analyzer = ThreatAnalyzer(config, memory_service)
        self.neutralizer = ThreatNeutralizer(config, self.quarantine_dir, self.lures_dir)
        self.stealth = StealthMode(config) if self.stealth_mode else None

        # Souscrire aux événements
        self.event_bus.subscribe("file.created", self._on_file_created)
        self.event_bus.subscribe("file.modified", self._on_file_modified)
        self.event_bus.subscribe("cyber.threat", self._on_cyber_threat)

        # Tâche de nettoyage périodique
        self._cleanup_task = None
        self._start_cleanup()

        logger.info("🩺 HealerAgent initialisé")

    def _start_cleanup(self):
        """Démarre la boucle de nettoyage périodique des leurres."""
        async def cleanup_loop():
            while True:
                await asyncio.sleep(3600)  # toutes les heures
                await self._cleanup_old_lures()

        self._cleanup_task = asyncio.create_task(cleanup_loop())

    async def _cleanup_old_lures(self):
        """Supprime les leurres plus vieux que lure_ttl."""
        now = time.time()
        deleted = 0
        for item in self.lures_dir.iterdir():
            if item.is_file() and not item.name.endswith('.meta.json'):
                meta_file = item.with_suffix('.meta.json')
                if meta_file.exists():
                    try:
                        async with aiofiles.open(meta_file, 'r') as f:
                            meta = json.loads(await f.read())
                        created = meta.get("created", 0)
                        if now - created > self.lure_ttl:
                            item.unlink()
                            meta_file.unlink()
                            deleted += 1
                    except Exception as e:  # <-- Exception spécifique avec log
                        logger.error(f"Erreur lors du nettoyage de {item}: {e}")
                else:
                    # Si pas de métadonnées, utiliser la date de modification
                    try:
                        stat = item.stat()
                        if now - stat.st_mtime > self.lure_ttl:
                            item.unlink()
                            deleted += 1
                    except Exception as e:
                        logger.error(f"Erreur lors de l'accès aux stats de {item}: {e}")
        if deleted:
            logger.info(f"🧹 Nettoyage: {deleted} leurres supprimés")

    # -----------------------------------------------------------------------
    # Gestion des événements
    # -----------------------------------------------------------------------
    async def _on_file_created(self, data: dict, event_id: str, source: str):
        """Callback quand un fichier est créé."""
        filepath = data.get("path")
        if not filepath:
            return
        await self._handle_new_file(filepath)

    async def _on_file_modified(self, data: dict, event_id: str, source: str):
        """Callback quand un fichier est modifié."""
        filepath = data.get("path")
        if not filepath:
            return
        await self._handle_new_file(filepath)

    async def _on_cyber_threat(self, data: dict, event_id: str, source: str):
        """Callback quand une menace cyber est détectée."""
        pattern = data.get("pattern")
        if pattern and "fichier" in pattern.lower():
            import re
            match = re.search(r"['\"]([^'\"]+\.\w+)['\"]", pattern)
            if match:
                filepath = match.group(1)
                await self._handle_new_file(filepath)

    async def _handle_new_file(self, filepath: str):
        """Traite un nouveau fichier (créé ou modifié)."""
        logger.info(f"🔍 Analyse du fichier: {filepath}")

        if not os.path.exists(filepath):
            logger.warning(f"Fichier introuvable: {filepath}")
            return

        # Scanner
        try:
            scan_result = await self.scanner.scan(filepath)
        except Exception as e:
            logger.error(f"Erreur lors du scan de {filepath}: {e}")
            return

        if not scan_result["threat_detected"]:
            logger.debug(f"Fichier sain: {filepath}")
            return

        # Analyser
        try:
            threat_info = await self.analyzer.analyze(filepath, scan_result)
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse de {filepath}: {e}")
            return

        # Publier l'événement
        self.event_bus.publish(
            "healer.threat_detected",
            {
                "filepath": filepath,
                "threat_name": threat_info.get("name", "Inconnu"),
                "severity": threat_info.get("severity", 0.5),
                "signature": threat_info.get("signature"),
            },
            self.name,
        )

        # Mettre en quarantaine si activé
        if self.auto_quarantine:
            await self._quarantine_file(filepath, threat_info)

    async def _quarantine_file(self, filepath: str, threat_info: dict):
        """Met un fichier en quarantaine et crée un leurre."""
        try:
            # Déplacer vers quarantaine
            dest = await self.neutralizer.quarantine(filepath, threat_info)
            logger.info(f"✅ Fichier mis en quarantaine: {dest}")

            # Créer un leurre
            lure_path = await self.neutralizer.create_lure(filepath, threat_info)
            logger.info(f"🎭 Leurre créé: {lure_path}")

            # Publier l'événement
            self.event_bus.publish(
                "healer.file_quarantined",
                {
                    "original": filepath,
                    "quarantine_path": str(dest),
                    "lure_path": str(lure_path),
                    "threat": threat_info.get("name"),
                },
                self.name,
            )
        except Exception as e:
            logger.error(f"Erreur lors de la mise en quarantaine de {filepath}: {e}")

    # -----------------------------------------------------------------------
    # Implémentations des outils
    # -----------------------------------------------------------------------
    async def _tool_scan_file(self, filepath: str) -> str:
        """Outil pour scanner un fichier."""
        if not os.path.exists(filepath):
            return f"❌ Fichier introuvable: {filepath}"

        try:
            result = await self.scanner.scan(filepath)
        except Exception as e:
            logger.error(f"Erreur lors du scan de {filepath}: {e}")
            return f"❌ Erreur lors du scan: {e}"

        if result["threat_detected"]:
            try:
                threat_info = await self.analyzer.analyze(filepath, result)
            except Exception as e:
                logger.error(f"Erreur lors de l'analyse de {filepath}: {e}")
                return f"⚠️ Menace détectée mais impossible d'analyser: {e}"
            return f"⚠️ Menace détectée: {threat_info.get('name', 'Inconnue')} (sévérité {threat_info.get('severity', 0):.2f})"
        else:
            return "✅ Aucune menace détectée."

    async def _tool_quarantine_file(self, filepath: str) -> str:
        """Outil pour mettre un fichier en quarantaine."""
        if not os.path.exists(filepath):
            return f"❌ Fichier introuvable: {filepath}"

        try:
            result = await self.scanner.scan(filepath)
        except Exception as e:
            logger.error(f"Erreur lors du scan de {filepath}: {e}")
            return f"❌ Erreur lors du scan: {e}"

        threat_info = await self.analyzer.analyze(filepath, result) if result["threat_detected"] else {"name": "Inconnu", "severity": 0}
        try:
            dest = await self.neutralizer.quarantine(filepath, threat_info)
        except Exception as e:
            logger.error(f"Erreur lors de la mise en quarantaine de {filepath}: {e}")
            return f"❌ Erreur lors de la mise en quarantaine: {e}"
        return f"✅ Fichier mis en quarantaine: {dest}"

    async def _tool_restore_file(self, filename: str) -> str:
        """Outil pour restaurer un fichier depuis la quarantaine."""
        for item in self.quarantine_dir.iterdir():
            if item.name == filename or item.name.endswith(f"_{filename}"):
                original_name = item.name.split("_", 1)[-1] if "_" in item.name else item.name
                original_path = Path.home() / original_name  # À adapter
                try:
                    await self.neutralizer.restore(item, original_path)
                except Exception as e:
                    logger.error(f"Erreur lors de la restauration de {item}: {e}")
                    return f"❌ Erreur lors de la restauration: {e}"
                return f"✅ Fichier restauré: {original_path}"
        return f"❌ Fichier '{filename}' non trouvé en quarantaine."

    async def _tool_list_quarantine(self) -> str:
        """Outil pour lister les fichiers en quarantaine."""
        files = list(self.quarantine_dir.iterdir())
        if not files:
            return "📂 Aucun fichier en quarantaine."
        result = "📂 Fichiers en quarantaine:\n"
        for f in files:
            if f.suffix == '.meta.json':
                continue
            try:
                stat = f.stat()
                size = stat.st_size
                mtime = time.ctime(stat.st_mtime)
                result += f"  - {f.name} ({size} octets) - {mtime}\n"
            except Exception as e:
                logger.error(f"Erreur lors de la lecture des infos de {f}: {e}")
                result += f"  - {f.name} (informations indisponibles)\n"
        return result

    def get_tools(self) -> list:
        return [
            Tool(name="scan_file", description="Analyse un fichier à la recherche de menaces.", contract=ScanFileContract),
            Tool(name="quarantine_file", description="Met un fichier en quarantaine.", contract=QuarantineFileContract),
            Tool(name="restore_file", description="Restaure un fichier depuis la quarantaine.", contract=RestoreFileContract),
            Tool(name="list_quarantine", description="Liste les fichiers en quarantaine.", contract=ListQuarantineContract),
        ]

    async def stop(self):
        """Arrête proprement l'agent."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Erreur lors de l'arrêt de la tâche de nettoyage: {e}")
        logger.info("HealerAgent arrêté.")