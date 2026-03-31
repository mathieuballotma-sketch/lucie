"""
InputActivityMonitor — Détecte l'activité clavier/souris via CGEventTap.

Mode PASSIF uniquement (kCGEventTapOptionListenOnly) :
- Ne modifie AUCUN événement
- Ne bloque AUCUNE entrée
- Détecte uniquement la présence/absence d'activité

SÉCURITÉ :
- Aucun keylogging — on ne lit PAS les caractères
- Seuls les timestamps et types d'événements sont capturés

NOTE : Ce module nécessite macOS + pyobjc. Sur d'autres plateformes,
le moniteur retourne toujours ActivityState.ACTIVE.
"""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Any, Callable, List, Optional

from ...utils.logger import logger

# Import conditionnel macOS
try:
    import Quartz
    _HAS_QUARTZ = True
except ImportError:
    _HAS_QUARTZ = False


class ActivityState(Enum):
    """État d'activité de l'utilisateur."""
    ACTIVE = "active"
    IDLE = "idle"
    TYPING_BURST = "typing"
    AWAY = "away"


class InputActivityMonitor:
    """
    Moniteur d'activité passive via CGEventTap.

    Architecture :
    - Un CGEventTap en mode ListenOnly sur la session
    - Un CFRunLoop dans un thread dédié
    - Calcul de l'état via timestamps (pas de capture de contenu)

    Contraintes M3 16GB :
    - Zéro allocation dans le callback
    - Overhead mémoire : ~4KB (juste des compteurs)

    Mode stub sur Linux : retourne toujours ACTIVE.
    """

    IDLE_THRESHOLD = 30.0
    AWAY_THRESHOLD = 300.0
    TYPING_BURST_RATE = 3.0

    def __init__(self) -> None:
        self._state = ActivityState.IDLE
        self._last_event_time: float = time.monotonic()
        self._key_timestamps: List[float] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._run_loop_ref: Optional[Any] = None
        self._tap_ref: Optional[Any] = None
        self._listeners: List[Callable[[ActivityState], None]] = []
        self._lock = threading.Lock()

    def start(self) -> bool:
        """
        Crée le CGEventTap et démarre le thread CFRunLoop.
        Retourne False si pas de permission ou non-macOS.
        """
        if self._running:
            return True

        if not _HAS_QUARTZ:
            logger.info("InputActivityMonitor: mode stub (non-macOS)")
            self._state = ActivityState.ACTIVE
            self._running = True
            return True

        try:
            if not Quartz.AXIsProcessTrustedWithOptions(
                {Quartz.kAXTrustedCheckOptionPrompt: False}
            ):
                logger.warning(
                    "InputActivityMonitor : permission Accessibility requise. "
                    "Fonctionnement en mode dégradé."
                )
                self._state = ActivityState.ACTIVE
                self._running = True
                return False

            event_mask = (
                (1 << Quartz.kCGEventKeyDown) |
                (1 << Quartz.kCGEventMouseMoved) |
                (1 << Quartz.kCGEventLeftMouseDown) |
                (1 << Quartz.kCGEventRightMouseDown) |
                (1 << Quartz.kCGEventScrollWheel)
            )

            self._tap_ref = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap,
                Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionListenOnly,
                event_mask,
                self._event_callback,
                None,
            )

            if self._tap_ref is None:
                logger.error("CGEventTapCreate failed — permission denied?")
                return False

            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop_thread,
                name="BrainFeed-InputMonitor",
                daemon=True,
            )
            self._thread.start()

            logger.info("InputActivityMonitor démarré (CGEventTap passif)")
            return True

        except Exception as e:
            logger.error(f"InputActivityMonitor start failed: {e}")
            return False

    def stop(self) -> None:
        """Arrêt propre."""
        if not self._running:
            return
        self._running = False

        if _HAS_QUARTZ:
            if self._run_loop_ref:
                Quartz.CFRunLoopStop(self._run_loop_ref)
            if self._tap_ref:
                Quartz.CGEventTapEnable(self._tap_ref, False)
            if self._thread:
                self._thread.join(timeout=2.0)

        self._tap_ref = None
        self._run_loop_ref = None
        logger.info("InputActivityMonitor arrêté")

    def _run_loop_thread(self) -> None:
        """Thread dédié au CFRunLoop pour le CGEventTap."""
        try:
            source = Quartz.CFMachPortCreateRunLoopSource(
                None, self._tap_ref, 0
            )
            loop = Quartz.CFRunLoopGetCurrent()
            self._run_loop_ref = loop

            Quartz.CFRunLoopAddSource(loop, source, Quartz.kCFRunLoopDefaultMode)
            Quartz.CGEventTapEnable(self._tap_ref, True)

            timer = Quartz.CFRunLoopTimerCreate(
                None,
                Quartz.CFAbsoluteTimeGetCurrent() + 5.0,
                5.0,
                0, 0,
                self._idle_check_callback,
                None,
            )
            Quartz.CFRunLoopAddTimer(loop, timer, Quartz.kCFRunLoopDefaultMode)
            Quartz.CFRunLoopRun()

        except Exception as e:
            logger.error(f"InputActivityMonitor run loop error: {e}")
        finally:
            self._running = False

    def _event_callback(self, proxy: Any, event_type: int,
                        event: Any, user_info: Any) -> Any:
        """Callback CGEventTap — ultra-rapide, pas d'allocation."""
        now = time.monotonic()
        self._last_event_time = now

        if _HAS_QUARTZ and event_type == Quartz.kCGEventKeyDown:
            self._key_timestamps.append(now)
            cutoff = now - 2.0
            self._key_timestamps = [
                t for t in self._key_timestamps if t > cutoff
            ]

        old_state = self._state
        if len(self._key_timestamps) > self.TYPING_BURST_RATE * 2:
            new_state = ActivityState.TYPING_BURST
        else:
            new_state = ActivityState.ACTIVE

        if new_state != old_state:
            self._state = new_state
            self._notify_state_change(new_state)

        return event

    def _idle_check_callback(self, timer: Any, info: Any) -> None:
        """Timer callback — vérifie si l'utilisateur est idle."""
        elapsed = time.monotonic() - self._last_event_time
        old_state = self._state

        if elapsed >= self.AWAY_THRESHOLD:
            new_state = ActivityState.AWAY
        elif elapsed >= self.IDLE_THRESHOLD:
            new_state = ActivityState.IDLE
        else:
            return

        if new_state != old_state:
            self._state = new_state
            self._notify_state_change(new_state)

    def _notify_state_change(self, state: ActivityState) -> None:
        """Notifie les listeners d'un changement d'état."""
        for listener in self._listeners:
            try:
                listener(state)
            except Exception as e:
                logger.debug(f"Input listener error: {e}")

    def add_listener(self, callback: Callable[[ActivityState], None]) -> None:
        self._listeners.append(callback)

    @property
    def state(self) -> ActivityState:
        return self._state

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self._last_event_time

    @property
    def typing_rate(self) -> float:
        """Taux de frappe actuel (touches/seconde)."""
        now = time.monotonic()
        recent = [t for t in self._key_timestamps if now - t < 2.0]
        if len(recent) < 2:
            return 0.0
        return len(recent) / 2.0
