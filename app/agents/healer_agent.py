"""
Healer Agent - Agent de guérison et de neutralisation des menaces.
Analyse les fichiers suspects, les met en quarantaine, et crée des leurres.
Version refactorisée avec gestion d'erreurs avancée, métriques, et sécurité renforcée.
Incarne les principes :
- Homéostasie : gestion robuste des erreurs, publication sur event bus.
- Évolution : métriques pour l'auto-amélioration.
- Immunité adaptative : quarantaine, leurres.
- Symbiose : événements pour informer les autres agents.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
import re

import aiofiles
from pydantic import BaseModel, Field, validator

from app.agents.base_agent import BaseAgent, Tool
from app.healer.scanner import FileScanner
from app.healer.analyzer import ThreatAnalyzer
from app.healer.neutralizer import ThreatNeutralizer
from app.healer.stealth import StealthMode
from app.brain.synapses.event_bus import EventBus
from app.utils.logger import logger
from app.utils.errors import ToolExecutionError
from app.utils.metrics import MetricsCollector


# -----------------------------------------------------------------------
# Exceptions personnalisées
# -----------------------------------------------------------------------
class HealerError(Exception):
    """Erreur de base pour HealerAgent."""
    pass


class FileScanError(HealerError):
    """Erreur lors du scan d'un fichier."""
    pass


class QuarantineError(HealerError):
    """Erreur lors de la mise en quarantaine."""
    pass


class RestoreError(HealerError):
    """Erreur lors de la restauration."""
    pass


# -----------------------------------------------------------------------
# Contrats Pydantic pour les outils
# -----------------------------------------------------------------------
class ScanFileContract(BaseModel):
    filepath: str = Field(..., description="Chemin complet du fichier à scanner")

    @validator('filepath')
    def path_must_exist(cls, v):
        if not Path(v).exists():
            raise ValueError(f"Le fichier {v} n'existe pas")
        return v


class QuarantineFileContract(BaseModel):
    filepath: str = Field(..., description="Chemin complet du fichier à mettre en quarantaine")

    @validator('filepath')
    def path_must_exist(cls, v):
        if not Path(v).exists():
            raise ValueError(f"Le fichier {v} n'existe pas")
        return v


class RestoreFileContract(BaseModel):
    filename: str = Field(..., description="Nom du fichier à restaurer (sans chemin)")

    @validator('filename')
    def prevent_path_traversal(cls, v):
        # Évite les tentatives de traversée de répertoire
        if '..' in v or '/' in v or '\\' in v:
            raise ValueError("Nom de fichier invalide (caractères interdits)")
        return v


class ListQuarantineContract(BaseModel):
    pass


# -----------------------------------------------------------------------
# Nettoyeur de leurres (extrait)
# -----------------------------------------------------------------------
class LureCleaner:
    """
    Gère le nettoyage périodique des leurres expirés.
    """

    def __init__(self, lures_dir: Path, lure_ttl: int, event_bus: EventBus):
        self.lures_dir = lures_dir
        self.lure_ttl = lure_ttl
        self.event_bus = event_bus
        self._task: Optional[asyncio.Task] = None

    def start(self, loop: asyncio.AbstractEventLoop):
        """Démarre la boucle de nettoyage."""
        self._task = loop.create_task(self._cleanup_loop())
        logger.debug("LureCleaner démarré")

    async def stop(self):
        """Arrête la boucle de nettoyage."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _cleanup_loop(self):
        """Boucle infinie avec intervalle d'une heure."""
        while True:
            await asyncio.sleep(3600)
            await self._cleanup_once()

    async def _cleanup_once(self):
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
                    except Exception as e:
                        logger.error(f"Erreur lors du nettoyage de {item}: {e}")
                        await self.event_bus.publish("tool.error", {
                            "agent": "LureCleaner",
                            "error": str(e),
                            "suggestion": "Vérifiez les permissions du répertoire des leurres."
                        })
                else:
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
# Agent guérisseur
# -----------------------------------------------------------------------
class HealerAgent(BaseAgent):
    """
    Agent capable de scanner, analyser et neutraliser les fichiers malveillants.
    """

    def __init__(
        self,
        llm_service,
        bus,
        event_bus: EventBus,
        config: dict,
        memory_service=None
    ):
        super().__init__("HealerAgent", llm_service, bus)
        self.event_bus = event_bus
        self.memory = memory_service

        # Configuration
        self.quarantine_dir = Path(config.get("quarantine_dir", "~/AgentLucide/quarantine")).expanduser()
        self.lures_dir = Path(config.get("lures_dir", "~/AgentLucide/lures")).expanduser()
        self.auto_quarantine = config.get("auto_quarantine", True)
        self.stealth_mode = config.get("stealth_mode", False)
        self.lure_ttl = config.get("lure_ttl", 86400)  # 24h
        self.auto_test = config.get("auto_test", False)  # désactivé par défaut

        # Créer les répertoires
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.lures_dir.mkdir(parents=True, exist_ok=True)

        # Initialiser les sous-modules
        self.scanner = FileScanner(config)
        self.analyzer = ThreatAnalyzer(config, memory_service)
        self.neutralizer = ThreatNeutralizer(config, self.quarantine_dir, self.lures_dir)
        self.stealth = StealthMode(config) if self.stealth_mode else None

        # Boucle asyncio (sera injectée plus tard)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Nettoyeur de leurres
        self.lure_cleaner = LureCleaner(self.lures_dir, self.lure_ttl, event_bus)

        # Métriques
        self.metrics = MetricsCollector()

        # Souscrire aux événements
        self.event_bus.subscribe("file.created", self._on_file_created)
        self.event_bus.subscribe("file.modified", self._on_file_modified)
        self.event_bus.subscribe("cyber.threat", self._on_cyber_threat)

        logger.info("🩺 HealerAgent initialisé (en attente de la boucle asyncio)")

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Injecte la boucle asyncio et démarre les tâches."""
        self._loop = loop
        self.lure_cleaner.start(loop)
        if self.auto_test:
            loop.create_task(self._test_scan())

    async def _test_scan(self):
        """Test automatique : scanne un fichier de test après 5 secondes (optionnel)."""
        await asyncio.sleep(5)
        test_file = Path("/tmp/test_malware.txt")
        if test_file.exists():
            logger.info("🔍 Test automatique : scan de /tmp/test_malware.txt")
            await self._handle_new_file(str(test_file))
        else:
            logger.debug("Test automatique ignoré : fichier /tmp/test_malware.txt absent")

    # -----------------------------------------------------------------------
    # Gestion des événements
    # -----------------------------------------------------------------------
    async def _on_file_created(self, data: dict, event_id: str, source: str):
        filepath = data.get("path")
        if not filepath:
            return
        await self._handle_new_file(filepath)

    async def _on_file_modified(self, data: dict, event_id: str, source: str):
        filepath = data.get("path")
        if not filepath:
            return
        await self._handle_new_file(filepath)

    async def _on_cyber_threat(self, data: dict, event_id: str, source: str):
        pattern = data.get("pattern")
        if pattern and "fichier" in pattern.lower():
            match = re.search(r"['\"]([^'\"]+\.\w+)['\"]", pattern)
            if match:
                filepath = match.group(1)
                await self._handle_new_file(filepath)

    async def _handle_new_file(self, filepath: str):
        """Analyse un nouveau fichier et agit en conséquence."""
        logger.info(f"🔍 Analyse du fichier: {filepath}")
        self.metrics.increment("files_scanned")

        path = Path(filepath)
        if not path.exists():
            logger.warning(f"Fichier introuvable: {filepath}")
            return

        try:
            scan_result = await self.scanner.scan(filepath)
        except Exception as e:
            logger.error(f"Erreur lors du scan de {filepath}: {e}")
            await self.event_bus.publish("tool.error", {
                "agent": self.name,
                "error": f"Scan failed: {e}",
                "suggestion": "Vérifiez les permissions du fichier."
            })
            self.metrics.increment("scan_errors")
            return

        if not scan_result["threat_detected"]:
            logger.debug(f"Fichier sain: {filepath}")
            return

        self.metrics.increment("threats_detected")

        try:
            threat_info = await self.analyzer.analyze(filepath, scan_result)
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse de {filepath}: {e}")
            await self.event_bus.publish("tool.error", {
                "agent": self.name,
                "error": f"Analysis failed: {e}",
                "suggestion": "Le fichier pourrait être corrompu."
            })
            return

        # Publier la détection
        await self.event_bus.publish(
            "healer.threat_detected",
            {
                "filepath": filepath,
                "threat_name": threat_info.get("name", "Inconnu"),
                "severity": threat_info.get("severity", 0.5),
                "signature": threat_info.get("signature"),
            },
            self.name,
        )

        if self.auto_quarantine:
            await self._quarantine_file(filepath, threat_info)

    async def _quarantine_file(self, filepath: str, threat_info: dict):
        """Met un fichier en quarantaine et crée un leurre."""
        try:
            dest = await self.neutralizer.quarantine(filepath, threat_info)
            logger.info(f"✅ Fichier mis en quarantaine: {dest}")
            self.metrics.increment("files_quarantined")

            lure_path = await self.neutralizer.create_lure(filepath, threat_info)
            logger.info(f"🎭 Leurre créé: {lure_path}")
            self.metrics.increment("lures_created")

            await self.event_bus.publish(
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
            await self.event_bus.publish("tool.error", {
                "agent": self.name,
                "error": f"Quarantine failed: {e}",
                "suggestion": "Vérifiez l'espace disque ou les permissions."
            })
            self.metrics.increment("quarantine_errors")

    # -----------------------------------------------------------------------
    # Implémentations des outils
    # -----------------------------------------------------------------------
    async def _tool_scan_file(self, filepath: str) -> str:
        """Outil de scan synchrone (pour requêtes utilisateur)."""
        self.metrics.increment("tool_calls", {"tool": "scan_file"})
        path = Path(filepath)
        if not path.exists():
            raise ToolExecutionError(f"Fichier introuvable: {filepath}")

        try:
            result = await self.scanner.scan(filepath)
        except Exception as e:
            logger.error(f"Erreur lors du scan de {filepath}: {e}")
            raise ToolExecutionError(f"Erreur lors du scan: {e}")

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
        """Met un fichier en quarantaine (même s'il n'est pas détecté comme menace)."""
        self.metrics.increment("tool_calls", {"tool": "quarantine_file"})
        path = Path(filepath)
        if not path.exists():
            raise ToolExecutionError(f"Fichier introuvable: {filepath}")

        try:
            result = await self.scanner.scan(filepath)
        except Exception as e:
            logger.error(f"Erreur lors du scan de {filepath}: {e}")
            raise ToolExecutionError(f"Erreur lors du scan: {e}")

        threat_info = await self.analyzer.analyze(filepath, result) if result["threat_detected"] else {"name": "Inconnu", "severity": 0}
        try:
            dest = await self.neutralizer.quarantine(filepath, threat_info)
        except Exception as e:
            logger.error(f"Erreur lors de la mise en quarantaine de {filepath}: {e}")
            raise ToolExecutionError(f"Erreur lors de la mise en quarantaine: {e}")
        return f"✅ Fichier mis en quarantaine: {dest}"

    async def _tool_restore_file(self, filename: str) -> str:
        """Restaure un fichier depuis la quarantaine."""
        self.metrics.increment("tool_calls", {"tool": "restore_file"})
        # Sécurité supplémentaire : on utilise Path(filename).name pour éviter les traversées
        safe_name = Path(filename).name
        for item in self.quarantine_dir.iterdir():
            if item.name == safe_name or item.name.endswith(f"_{safe_name}"):
                original_name = item.name.split("_", 1)[-1] if "_" in item.name else item.name
                original_path = Path.home() / original_name
                try:
                    await self.neutralizer.restore(item, original_path)
                except Exception as e:
                    logger.error(f"Erreur lors de la restauration de {item}: {e}")
                    raise ToolExecutionError(f"Erreur lors de la restauration: {e}")
                self.metrics.increment("files_restored")
                return f"✅ Fichier restauré: {original_path}"
        raise ToolExecutionError(f"Fichier '{filename}' non trouvé en quarantaine.")

    async def _tool_list_quarantine(self) -> str:
        """Liste les fichiers en quarantaine."""
        self.metrics.increment("tool_calls", {"tool": "list_quarantine"})
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
        await self.lure_cleaner.stop()
        logger.info("🩺 HealerAgent arrêté.")