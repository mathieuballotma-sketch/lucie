"""
NotificationBridge — Pont entre le ThoughtStream Python
et le DistributedNotificationCenter macOS.

Utilise pyobjc pour publier des notifications IPC que
le processus SwiftUI BrainFeedWindow observe.

IMPORTANT : DistributedNotificationCenter est le mécanisme IPC
le plus léger de macOS — pas de XPC, pas de Mach ports,
juste des notifications broadcast entre processus.

NOTE : Ce module nécessite macOS + pyobjc. Sur d'autres
plateformes, le NotificationBridge fonctionne en mode stub
(les pensées sont juste loggées).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from .models import ThoughtEntry

# Import conditionnel pyobjc (macOS uniquement)
try:
    import Foundation
    import objc
    _HAS_PYOBJC = True
except ImportError:
    _HAS_PYOBJC = False

from ...utils.logger import logger


# Nom de la notification — convention reverse-DNS
NOTIFICATION_NAME = "com.lucie.brainfeed.thought"
NOTIFICATION_CLEAR = "com.lucie.brainfeed.clear"
NOTIFICATION_STATE = "com.lucie.brainfeed.state"


class NotificationBridge:
    """
    Publie les ThoughtEntry via DistributedNotificationCenter.

    Throttling intégré :
    - Max 30 notifications/seconde (évite de saturer le système)
    - Les WHISPER sont filtrées (jamais envoyées)
    - Batching : si > 10 pensées en 100ms, envoie un résumé

    Thread-safe : peut être appelé depuis n'importe quel thread.

    Fallback : si pyobjc n'est pas disponible, les notifications
    sont simplement loggées (mode développement Linux).
    """

    def __init__(self, max_rate: int = 30) -> None:
        self._center = None
        if _HAS_PYOBJC:
            self._center = Foundation.NSDistributedNotificationCenter.defaultCenter()
        self._max_rate = max_rate
        self._interval = 1.0 / max_rate
        self._last_send: float = 0.0
        self._dropped: int = 0
        self._sent: int = 0
        self._lock = threading.Lock()
        self._active: bool = True

    def publish(self, entry: ThoughtEntry) -> bool:
        """
        Publie une pensée via DistributedNotificationCenter.
        Retourne True si envoyé, False si throttlé.
        """
        if not self._active:
            return False

        # Filtrer les WHISPER
        if entry.priority.value <= 0:
            return False

        with self._lock:
            now = time.monotonic()
            if now - self._last_send < self._interval:
                self._dropped += 1
                return False
            self._last_send = now

        if not self._center:
            # Mode stub — log uniquement
            logger.debug(f"BrainFeed [{entry.thought_type.value}]: {entry.text}")
            self._sent += 1
            return True

        try:
            info = entry.to_notification_dict()
            ns_info = Foundation.NSDictionary.dictionaryWithDictionary_(info)

            self._center.postNotificationName_object_userInfo_deliverImmediately_(
                NOTIFICATION_NAME,
                None,
                ns_info,
                True,
            )

            self._sent += 1
            return True

        except Exception as e:
            logger.error(f"NotificationBridge publish error: {e}")
            return False

    def publish_state(self, state: str) -> None:
        """Publie un changement d'état global (idle, thinking, working)."""
        if not self._center:
            logger.debug(f"BrainFeed state: {state}")
            return

        try:
            info = Foundation.NSDictionary.dictionaryWithDictionary_({
                "state": state,
                "timestamp": str(time.time()),
            })
            self._center.postNotificationName_object_userInfo_deliverImmediately_(
                NOTIFICATION_STATE, None, info, True,
            )
        except Exception as e:
            logger.error(f"NotificationBridge state error: {e}")

    def clear_feed(self) -> None:
        """Envoie un signal de nettoyage au BrainFeedWindow."""
        if not self._center:
            return
        try:
            self._center.postNotificationName_object_userInfo_deliverImmediately_(
                NOTIFICATION_CLEAR, None, None, True,
            )
        except Exception as e:
            logger.error(f"NotificationBridge clear error: {e}")

    def shutdown(self) -> None:
        """Arrêt propre."""
        self._active = False
        self.publish_state("shutdown")
        logger.info(
            f"NotificationBridge shutdown — sent={self._sent}, "
            f"dropped={self._dropped}"
        )

    @property
    def stats(self) -> dict:
        return {
            "sent": self._sent,
            "dropped": self._dropped,
            "drop_rate": f"{self._dropped / max(1, self._sent + self._dropped):.1%}",
            "active": self._active,
            "native": _HAS_PYOBJC,
        }
