# app/agents/action_broker.py
"""
ActionBroker — Gestion centralisée des actions macOS.

Pipeline : Intent → Execute → StateVerifier → CorrectionSteps (≤2) → ActionTrace SQLite WAL.
StateVerifier utilise AXUIElement via PyObjC pour vérifier l'état de l'app cible.

Principes :
- Homéostasie : correction automatique bornée (max 2 tentatives)
- Entropie : traçabilité complète via SQLite WAL
- Moindre action : vérification rapide via AXUIElement
"""

import asyncio
import ctypes
import hashlib
import platform
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import aiosqlite
from pydantic.v1 import BaseModel, Field

from AppKit import NSWorkspace

try:
    from ApplicationServices import (
        AXUIElementCreateApplication,
        kAXFocusedWindowAttribute,
        AXUIElementCopyAttributeValue,
    )
    _HAS_AX = True
except ImportError:
    _HAS_AX = False

from app.agents.speed_config import ACTIVE_PROFILE
from app.utils.logger import logger


# -----------------------------------------------------------------------
# Contrats Pydantic
# -----------------------------------------------------------------------
class Intent(BaseModel):
    """Intention d'action macOS à exécuter."""
    intent_type: str
    params: Dict[str, Any] = Field(default_factory=dict)
    expected_state: Optional[Dict[str, Any]] = None


# -----------------------------------------------------------------------
# StateVerifier — vérification via AXUIElement
# -----------------------------------------------------------------------
class StateVerifier:
    """
    Vérifie que l'application ciblée est frontmost.
    Utilise bundleIdentifier + AXUIElement pour une vérification fiable.
    """

    # Correspondance nom d'app → bundleIdentifier
    BUNDLE_IDS: Dict[str, str] = {
        "Safari": "com.apple.Safari",
        "TextEdit": "com.apple.TextEdit",
        "Mail": "com.apple.Mail",
        "Finder": "com.apple.finder",
        "Terminal": "com.apple.Terminal",
        "Notes": "com.apple.Notes",
        "Pages": "com.apple.iWork.Pages",
        "Numbers": "com.apple.iWork.Numbers",
        "Keynote": "com.apple.iWork.Keynote",
        "Calendar": "com.apple.iCal",
        "Messages": "com.apple.MobileSMS",
        "Xcode": "com.apple.dt.Xcode",
    }

    @staticmethod
    def verify(app_name: str) -> bool:
        """
        Vérifie que l'application 'app_name' est frontmost.
        Retourne True si oui, False sinon.
        """
        front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        front_bundle = front_app.bundleIdentifier()

        expected_bundle = StateVerifier.BUNDLE_IDS.get(app_name)
        if expected_bundle is None:
            logger.warning(f"Vérification impossible : bundleIdentifier inconnu pour {app_name}")
            return False

        if front_bundle != expected_bundle:
            logger.info(f"{app_name} n'est pas frontmost (bundle={front_bundle})")
            return False

        # Vérification AXUIElement sur la fenêtre front (si disponible)
        if _HAS_AX:
            try:
                pid = front_app.processIdentifier()
                ax_app = AXUIElementCreateApplication(pid)
                focused_window = ctypes.c_void_p()
                result = AXUIElementCopyAttributeValue(
                    ax_app, kAXFocusedWindowAttribute, ctypes.byref(focused_window)
                )
                if result != 0 or not focused_window:
                    logger.info(f"{app_name} détecté mais pas de fenêtre focus via AX")
                    return False
            except Exception as e:
                logger.error(f"Erreur AXUIElement pour {app_name}: {e}")
                return False

        logger.info(f"{app_name} est frontmost ✅")
        return True


# -----------------------------------------------------------------------
# ActionTrace — modèle de traçabilité
# -----------------------------------------------------------------------
class ActionTrace(BaseModel):
    """Trace d'une action exécutée par le broker."""
    id: str
    intent_type: str
    app_target: str
    success: bool
    state_before: bool
    state_after: bool
    corrections_used: int
    duration_ms: float
    timestamp: float
    error_message: Optional[str]
    environment_hash: str


# -----------------------------------------------------------------------
# ActionBroker — orchestrateur central
# -----------------------------------------------------------------------
class ActionBroker:
    """
    Broker centralisé pour exécuter des intents macOS
    avec correction bornée (≤2) et traçabilité SQLite WAL.
    """

    MAX_CORRECTIONS = 2

    def __init__(self, db_path: Path):
        self.db_path = db_path.expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[aiosqlite.Connection] = None

    async def init_db(self) -> None:
        """Initialise la base SQLite WAL pour les traces d'actions."""
        self._conn = await aiosqlite.connect(self.db_path, isolation_level=None)
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS action_trace (
                id TEXT PRIMARY KEY,
                intent_type TEXT,
                app_target TEXT,
                success INTEGER,
                state_before INTEGER,
                state_after INTEGER,
                corrections_used INTEGER,
                duration_ms REAL,
                timestamp REAL,
                error_message TEXT,
                environment_hash TEXT
            );
        """)
        logger.info("⚡ ActionBroker : base SQLite initialisée")

    async def close_db(self) -> None:
        """Ferme proprement la connexion SQLite."""
        if self._conn:
            await self._conn.close()

    async def execute_intent(self, intent: Intent) -> ActionTrace:
        """Exécute un intent avec correction bornée et traçabilité."""
        start_time = time.time()
        corrections = 0
        success = False
        app_name = intent.params.get("app_name", "")
        state_before = StateVerifier.verify(app_name)
        state_after = False
        error_msg: Optional[str] = None

        while corrections <= self.MAX_CORRECTIONS and not success:
            try:
                await self._execute(intent)
                # Pause adaptée au profil de vitesse actif
                await asyncio.sleep(ACTIVE_PROFILE.sleep_after_activate)
                state_after = StateVerifier.verify(app_name)
                success = state_after
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Intent {intent.intent_type} échec : {e}")
            if not success:
                corrections += 1
                logger.info(
                    f"Correction {corrections}/{self.MAX_CORRECTIONS} "
                    f"pour {intent.intent_type}"
                )

        duration_ms = (time.time() - start_time) * 1000

        trace = ActionTrace(
            id=str(uuid.uuid4()),
            intent_type=intent.intent_type,
            app_target=app_name,
            success=success,
            state_before=state_before,
            state_after=state_after,
            corrections_used=corrections,
            duration_ms=duration_ms,
            timestamp=time.time(),
            error_message=error_msg,
            environment_hash=self._compute_env_hash(),
        )
        await self._log_trace(trace)
        return trace

    async def _execute(self, intent: Intent) -> None:
        """Exécute l'intent via AppleScript async avec timeout."""
        app_name = intent.params.get("app_name")
        if not app_name:
            raise ValueError("Paramètre 'app_name' manquant pour l'intent")

        script = f'tell application "{app_name}" to activate'
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Timeout AppleScript pour '{app_name}' (10s)")
        if proc.returncode != 0:
            raise RuntimeError(f"Erreur AppleScript : {stderr.decode().strip()}")
        logger.info(f"Intent exécuté : {intent.intent_type} ({app_name})")

    async def _log_trace(self, trace: ActionTrace) -> None:
        """Enregistre la trace dans SQLite."""
        if not self._conn:
            return
        await self._conn.execute("""
            INSERT INTO action_trace (
                id, intent_type, app_target, success, state_before, state_after,
                corrections_used, duration_ms, timestamp, error_message, environment_hash
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            trace.id,
            trace.intent_type,
            trace.app_target,
            int(trace.success),
            int(trace.state_before),
            int(trace.state_after),
            trace.corrections_used,
            trace.duration_ms,
            trace.timestamp,
            trace.error_message,
            trace.environment_hash,
        ))
        await self._conn.commit()
        logger.debug(f"Trace enregistrée : {trace.intent_type} ({trace.app_target})")

    def _compute_env_hash(self) -> str:
        """Hash stable de l'environnement pour comparaison entre sessions."""
        env_data = (
            f"{platform.mac_ver()[0]}_"
            f"Lucie_1.0"
        ).encode()
        h = hashlib.blake2b(env_data, digest_size=16)
        return h.hexdigest()
