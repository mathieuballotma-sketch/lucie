"""
Healer Agent - Agent de guérison et de neutralisation des menaces.
Analyse les fichiers suspects, les met en quarantaine, et crée des leurres.
Version refactorisée avec gestion d'erreurs avancée, métriques, et sécurité renforcée.

Corrections v2 :
  - Handlers : signature corrigée (event: Event) au lieu de (data, event_id, source)
  - subscribe() : déplacé dans set_loop() après enregistrement de la source
  - Token injecté via set_token() hérité de BaseAgent

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
from pydantic.v1 import BaseModel, Field, validator

from app.agents.base_agent import BaseAgent, Tool
from app.healer.scanner import FileScanner
from app.healer.analyzer import ThreatAnalyzer
from app.healer.neutralizer import ThreatNeutralizer
from app.healer.stealth import StealthMode
from app.brain.synapses.event_bus import EventBus, Event
from app.utils.logger import logger
from app.utils.errors import ToolExecutionError


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
        if '..' in v or '/' in v or '\\' in v:
            raise ValueError("Nom de fichier invalide (caractères interdits)")
        return v


class ListQuarantineContract(BaseModel):
    pass


# -----------------------------------------------------------------------
# Nettoyeur de leurres
# -----------------------------------------------------------------------
class LureCleaner:
    """Gère le nettoyage périodique des leurres expirés."""

    def __init__(self, lures_dir: Path, lure_ttl: int, event_bus: EventBus):
        self.lures_dir = lures_dir
        self.lure_ttl = lure_ttl
        self.event_bus = event_bus
        self._task: Optional[asyncio.Task] = None

    def start(self, loop: asyncio.AbstractEventLoop):
        self._task = loop.create_task(self._cleanup_loop())
        logger.debug("LureCleaner démarré")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(3600)
            await self._cleanup_once()

    async def _cleanup_once(self):
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
                        logger.error(f"Erreur nettoyage {item}: {e}")
                else:
                    try:
                        stat = item.stat()
                        if now - stat.st_mtime > self.lure_ttl:
                            item.unlink()
                            deleted += 1
                    except Exception as e:
                        logger.error(f"Erreur stats {item}: {e}")
        if deleted:
            logger.info(f"🧹 {deleted} leurres supprimés")


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
        memory_service=None,
        token: Optional[str] = None,
    ):
        # FIX v2 : on passe event_bus et token à BaseAgent
        super().__init__("HealerAgent", llm_service, bus, event_bus=event_bus, token=token)
        self.memory = memory_service

        # Configuration
        self.quarantine_dir = Path(config.get("quarantine_dir", "~/AgentLucide/quarantine")).expanduser()
        self.lures_dir = Path(config.get("lures_dir", "~/AgentLucide/lures")).expanduser()
        self.auto_quarantine = config.get("auto_quarantine", True)
        self.stealth_mode = config.get("stealth_mode", False)
        self.lure_ttl = config.get("lure_ttl", 86400)
        self.auto_test = config.get("auto_test", False)

        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.lures_dir.mkdir(parents=True, exist_ok=True)

        self.scanner = FileScanner(config)
        self.analyzer = ThreatAnalyzer(config, memory_service)
        self.neutralizer = ThreatNeutralizer(config, self.quarantine_dir, self.lures_dir)
        self.stealth = StealthMode(config) if self.stealth_mode else None

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.lure_cleaner = LureCleaner(self.lures_dir, self.lure_ttl, event_bus)

        # FIX v2 : PAS de subscribe ici — les subscriptions sont async et
        # nécessitent un token. Elles sont faites dans set_loop().
        logger.info("🩺 HealerAgent initialisé (subscriptions en attente de set_loop)")

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """
        Injecte la boucle asyncio, démarre le nettoyeur de leurres
        et enregistre les abonnements EventBus.

        FIX v2 : les subscribe() sont déclenchés ici via create_task,
        une fois que le token est disponible et la boucle active.
        """
        self._loop = loop
        self.lure_cleaner.start(loop)

        # Lancer les abonnements de manière asynchrone
        loop.create_task(self._setup_subscriptions())

        if self.auto_test:
            loop.create_task(self._test_scan())

    async def _setup_subscriptions(self) -> None:
        """
        Enregistre les abonnements sur l'EventBus.
        Appelé depuis set_loop() via create_task.

        FIX v2 : vérifie que le token est disponible avant de souscrire.
        """
        if not self.token:
            logger.error(
                "HealerAgent._setup_subscriptions : token manquant — "
                "abonnements non enregistrés. Appelez set_token() avant set_loop()."
            )
            return

        event_bus = self.event_bus
        if event_bus is None:
            return
        try:
            await event_bus.subscribe(
                "file.created", self._on_file_created,
                source=self.name, token=self.token
            )
            await event_bus.subscribe(
                "file.modified", self._on_file_modified,
                source=self.name, token=self.token
            )
            await event_bus.subscribe(
                "cyber.threat", self._on_cyber_threat,
                source=self.name, token=self.token
            )
            logger.info("🩺 HealerAgent : abonné à file.created / file.modified / cyber.threat")
        except Exception as e:
            logger.error(f"HealerAgent._setup_subscriptions erreur : {e}")

    async def _test_scan(self):
        await asyncio.sleep(5)
        test_file = Path("/tmp/test_malware.txt")
        if test_file.exists():
            logger.info("🔍 Test auto : scan de /tmp/test_malware.txt")
            await self._handle_new_file(str(test_file))
        else:
            logger.debug("Test auto ignoré : fichier absent")

    # -----------------------------------------------------------------------
    # Handlers d'événements
    # FIX v2 : signature corrigée — reçoit un objet Event, pas (data, event_id, source)
    # -----------------------------------------------------------------------
    async def _on_file_created(self, event: Event) -> None:
        """Déclenché quand un fichier est créé."""
        filepath = event.data.get("path") if isinstance(event.data, dict) else None
        if not filepath:
            return
        await self._handle_new_file(filepath)

    async def _on_file_modified(self, event: Event) -> None:
        """Déclenché quand un fichier est modifié."""
        filepath = event.data.get("path") if isinstance(event.data, dict) else None
        if not filepath:
            return
        await self._handle_new_file(filepath)

    async def _on_cyber_threat(self, event: Event) -> None:
        """Réagit à une menace cyber en cherchant un fichier associé."""
        if not isinstance(event.data, dict):
            return
        pattern = event.data.get("pattern")
        if pattern and "fichier" in pattern.lower():
            match = re.search(r"['\"]([^'\"]+\.\w+)['\"]", pattern)
            if match:
                await self._handle_new_file(match.group(1))

    async def _handle_new_file(self, filepath: str):
        """Analyse un nouveau fichier et agit en conséquence."""
        logger.info(f"🔍 Analyse : {filepath}")

        path = Path(filepath)
        if not path.exists():
            logger.warning(f"Fichier introuvable : {filepath}")
            return

        try:
            scan_result = await self.scanner.scan(filepath)
        except Exception as e:
            logger.error(f"Scan échoué ({filepath}): {e}")
            await self._publish_tool_error(f"Scan failed: {e}", "Vérifiez les permissions.")
            return

        if not scan_result["threat_detected"]:
            logger.debug(f"Sain : {filepath}")
            return

        try:
            threat_info = await self.analyzer.analyze(filepath, scan_result)
        except Exception as e:
            logger.error(f"Analyse échouée ({filepath}): {e}")
            await self._publish_tool_error(f"Analysis failed: {e}", "Fichier peut-être corrompu.")
            return

        if self.event_bus and self.token:
            await self.event_bus.publish(
                "healer.threat_detected",
                {
                    "filepath": filepath,
                    "threat_name": threat_info.get("name", "Inconnu"),
                    "severity": threat_info.get("severity", 0.5),
                    "signature": threat_info.get("signature"),
                },
                source=self.name,
                token=self.token,
            )

        if self.auto_quarantine:
            await self._quarantine_file(filepath, threat_info)

    async def _quarantine_file(self, filepath: str, threat_info: dict):
        """Met un fichier en quarantaine et crée un leurre."""
        try:
            dest = await self.neutralizer.quarantine(filepath, threat_info)

            lure_path = await self.neutralizer.create_lure(filepath, threat_info)

            if self.event_bus and self.token:
                await self.event_bus.publish(
                    "healer.file_quarantined",
                    {
                        "original": filepath,
                        "quarantine_path": str(dest),
                        "lure_path": str(lure_path),
                        "threat": threat_info.get("name"),
                    },
                    source=self.name,
                    token=self.token,
                )
        except Exception as e:
            logger.error(f"Quarantaine échouée ({filepath}): {e}")
            await self._publish_tool_error(f"Quarantine failed: {e}", "Vérifiez l'espace disque.")

    async def _publish_tool_error(self, error: str, suggestion: str = "") -> None:
        """Publie une erreur sur l'EventBus si le token est disponible."""
        if not self.token:
            return
        if not self.event_bus:
            return
        try:
            await self.event_bus.publish(
                "tool.error",
                {"agent": self.name, "error": error, "suggestion": suggestion},
                source=self.name,
                token=self.token,
            )
        except Exception as e:
            logger.debug(f"_publish_tool_error impossible : {e}")

    # -----------------------------------------------------------------------
    # Implémentations des outils
    # -----------------------------------------------------------------------
    async def _tool_scan_file(self, filepath: str) -> str:
        path = Path(filepath)
        if not path.exists():
            raise ToolExecutionError(f"Fichier introuvable: {filepath}")

        try:
            result = await self.scanner.scan(filepath)
        except Exception as e:
            raise ToolExecutionError(f"Erreur scan: {e}")

        if result["threat_detected"]:
            try:
                threat_info = await self.analyzer.analyze(filepath, result)
            except Exception as e:
                return f"⚠️ Menace détectée, analyse impossible: {e}"
            return (
                f"⚠️ Menace : {threat_info.get('name', 'Inconnue')} "
                f"(sévérité {threat_info.get('severity', 0):.2f})"
            )
        return "✅ Aucune menace détectée."

    async def _tool_quarantine_file(self, filepath: str) -> str:
        if not Path(filepath).exists():
            raise ToolExecutionError(f"Fichier introuvable: {filepath}")

        try:
            result = await self.scanner.scan(filepath)
        except Exception as e:
            raise ToolExecutionError(f"Erreur scan: {e}")

        threat_info = (
            await self.analyzer.analyze(filepath, result)
            if result["threat_detected"]
            else {"name": "Inconnu", "severity": 0}
        )
        try:
            dest = await self.neutralizer.quarantine(filepath, threat_info)
        except Exception as e:
            raise ToolExecutionError(f"Erreur quarantaine: {e}")
        return f"✅ Fichier mis en quarantaine : {dest}"

    async def _tool_restore_file(self, filename: str) -> str:
        safe_name = Path(filename).name
        for item in self.quarantine_dir.iterdir():
            if item.name == safe_name or item.name.endswith(f"_{safe_name}"):
                original_name = item.name.split("_", 1)[-1] if "_" in item.name else item.name
                original_path = Path.home() / original_name
                try:
                    await self.neutralizer.restore(item, original_path)
                except Exception as e:
                    raise ToolExecutionError(f"Erreur restauration: {e}")
                return f"✅ Restauré : {original_path}"
        raise ToolExecutionError(f"'{filename}' non trouvé en quarantaine.")

    async def _tool_list_quarantine(self) -> str:
        files = [f for f in self.quarantine_dir.iterdir() if f.suffix != '.meta.json']
        if not files:
            return "📂 Aucun fichier en quarantaine."
        lines = ["📂 Fichiers en quarantaine :"]
        for f in files:
            try:
                stat = f.stat()
                lines.append(f"  - {f.name} ({stat.st_size} octets) — {time.ctime(stat.st_mtime)}")
            except Exception:
                lines.append(f"  - {f.name} (infos indisponibles)")
        return "\n".join(lines)

    def get_tools(self) -> list:
        return [
            Tool("scan_file", "Analyse un fichier à la recherche de menaces.", ScanFileContract),
            Tool("quarantine_file", "Met un fichier en quarantaine.", QuarantineFileContract),
            Tool("restore_file", "Restaure un fichier depuis la quarantaine.", RestoreFileContract),
            Tool("list_quarantine", "Liste les fichiers en quarantaine.", ListQuarantineContract),
        ]

    def can_handle(self, query: str) -> bool:
        return False

    async def stop(self):
        await self.lure_cleaner.stop()
        logger.info("🩺 HealerAgent arrêté.") 
 