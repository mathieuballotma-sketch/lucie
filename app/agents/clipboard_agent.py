"""
ClipboardAgent — Surveillance intelligente du presse-papier macOS.

Surveille le presse-papier en continu et propose des actions contextuelles
selon le type de contenu détecté (URL, email, téléphone, code, texte long).

Règles de confidentialité :
- Aucun contenu du presse-papier n'est jamais loggé
- Traitement en mémoire uniquement, rien n'est persisté
"""

import asyncio
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger

try:
    from AppKit import NSPasteboard as _NSPasteboard
    from AppKit import NSStringPboardType as _NSStringPboardType
    _PYOBJC_AVAILABLE = True
except ImportError:
    _NSPasteboard = None
    _NSStringPboardType = None
    _PYOBJC_AVAILABLE = False


class ContentType(str, Enum):
    """Types de contenu détectables dans le presse-papier."""

    URL = "url"
    EMAIL = "email"
    PHONE = "phone"
    CODE = "code"
    LONG_TEXT = "long_text"
    UNKNOWN = "unknown"


_RE_URL = re.compile(r"^https?://\S+", re.IGNORECASE)
_RE_EMAIL = re.compile(r"^[\w.+\-]+@(?:[\w\-]+\.)+[a-zA-Z]{2,}$")
_RE_PHONE = re.compile(r"^[+\d\s\-().]{7,20}$")
_RE_CODE = re.compile(
    r"(def |class |import |function |const |var |let |#include|<\?php|\{|\}|=>|::|==|!=|&&|\|\|)",
    re.MULTILINE,
)

_MIN_CHARS: int = 50
_POLL_INTERVAL: float = 1.0


def detect_content_type(text: str) -> ContentType:
    """Détecte le type de contenu du texte sans logger son contenu."""
    stripped = text.strip()
    if not stripped:
        return ContentType.UNKNOWN
    if _RE_URL.match(stripped):
        return ContentType.URL
    if _RE_EMAIL.match(stripped):
        return ContentType.EMAIL
    if _RE_PHONE.match(stripped) and any(c.isdigit() for c in stripped):
        return ContentType.PHONE
    if _RE_CODE.search(stripped):
        return ContentType.CODE
    if len(stripped) >= _MIN_CHARS:
        return ContentType.LONG_TEXT
    return ContentType.UNKNOWN


def get_proposals(content_type: ContentType) -> List[str]:
    """Retourne les actions proposées selon le type de contenu détecté."""
    _proposals: Dict[ContentType, List[str]] = {
        ContentType.URL: ["Ouvrir dans Safari", "Résumer la page", "Sauvegarder en favori"],
        ContentType.EMAIL: ["Rechercher dans les contacts", "Composer un mail"],
        ContentType.PHONE: ["Appeler", "Envoyer un message"],
        ContentType.CODE: ["Expliquer le code", "Corriger", "Formatter"],
        ContentType.LONG_TEXT: ["Résumer", "Traduire", "Reformuler"],
        ContentType.UNKNOWN: [],
    }
    return _proposals.get(content_type, [])


class ClipboardAgent(BaseAgent):
    """
    Agent de surveillance intelligente du presse-papier macOS.

    Polling NSPasteboard toutes les secondes via PyObjC.
    Publie sur "clipboard.proposal" quand le contenu est intéressant
    (> 50 chars OU pattern reconnu : URL, email, téléphone, code).

    model_role = "lightweight" — pas besoin d'un gros modèle.
    """

    def __init__(self, llm_service: Any, bus: Any, config: Dict[str, Any]) -> None:
        super().__init__("ClipboardAgent", llm_service, bus)
        self._poll_interval: float = float(
            config.get("clipboard_poll_interval", _POLL_INTERVAL)
        )
        self._last_change_count: int = -1
        self._monitoring_task: Optional["asyncio.Task[None]"] = None
        self._running: bool = False

    def can_handle(self, query: str) -> bool:
        """Cet agent est exclusivement background — pas de requêtes directes."""
        return False

    def get_tools(self) -> List[Tool]:
        return []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Démarre la surveillance asynchrone du presse-papier."""
        if not _PYOBJC_AVAILABLE:
            logger.warning("ClipboardAgent: PyObjC indisponible, surveillance désactivée.")
            return
        if self._running:
            return
        self._running = True
        self._monitoring_task = asyncio.create_task(self._poll_loop())
        logger.info("ClipboardAgent: surveillance du presse-papier démarrée.")

    def stop(self) -> None:
        """Arrête la surveillance du presse-papier."""
        self._running = False
        task = self._monitoring_task
        if task is not None:
            task.cancel()
            self._monitoring_task = None
        logger.info("ClipboardAgent: surveillance arrêtée.")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Boucle de polling async — cadencée par _poll_interval."""
        while self._running:
            try:
                await self._check_clipboard()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"ClipboardAgent: erreur dans la boucle de polling — {exc}")
            await asyncio.sleep(self._poll_interval)

    async def _check_clipboard(self) -> None:
        """Vérifie si le presse-papier a changé et publie si pertinent."""
        loop = asyncio.get_running_loop()
        result: Optional[Tuple[int, str]] = await loop.run_in_executor(
            None, self._read_pasteboard
        )
        if result is None:
            return

        change_count, text = result
        if change_count == self._last_change_count:
            return
        self._last_change_count = change_count

        content_type = detect_content_type(text)
        if content_type == ContentType.UNKNOWN:
            return

        proposals = get_proposals(content_type)
        if not proposals:
            return

        await self._publish_proposal(content_type, proposals, len(text))

    def _read_pasteboard(self) -> Optional[Tuple[int, str]]:
        """
        Lit le presse-papier depuis un thread exécuteur (PyObjC thread-safe).
        Retourne (changeCount, texte) ou None si rien à lire.
        Aucun contenu n'est loggé (vie privée).
        """
        if _NSPasteboard is None or _NSStringPboardType is None:
            return None
        try:
            pb = _NSPasteboard.generalPasteboard()
            count = int(pb.changeCount())
            text = pb.stringForType_(_NSStringPboardType)
            if not text:
                return None
            return (count, str(text))
        except Exception as exc:
            logger.error(f"ClipboardAgent: erreur lecture NSPasteboard — {exc}")
            return None

    async def _publish_proposal(
        self,
        content_type: ContentType,
        proposals: List[str],
        content_length: int,
    ) -> None:
        """Publie la proposition d'action sur l'EventBus (sans le contenu)."""
        event_bus = self.event_bus
        if event_bus is None or not self.token:
            return
        try:
            await event_bus.publish(
                channel="clipboard.proposal",
                data={
                    "content_type": content_type.value,
                    "proposals": proposals,
                    "content_length": content_length,
                },
                source=self.name,
                token=self.token,
            )
            logger.debug(
                f"ClipboardAgent: proposition publiée — type={content_type.value}"
            )
        except Exception as exc:
            logger.warning(f"ClipboardAgent: échec publication EventBus — {exc}")
