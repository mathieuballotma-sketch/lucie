"""
HotkeyManager — Raccourci global Cmd+Shift+L pour toggle HUD.

Utilise addGlobalMonitorForEventsMatchingMask_ de NSEvent.
Nécessite les permissions d'accessibilité macOS.

Raccourci : ⌘⇧L (Cmd+Shift+L) — analogue à Spotlight (⌘Space).
keyCode 37 = L, NSCommandKeyMask | NSShiftKeyMask.
"""

from __future__ import annotations

from typing import Any, Optional

import AppKit
from ApplicationServices import AXIsProcessTrusted

from ..utils.logger import logger

# Cmd+Shift+L
_TARGET_KEYCODE = 37  # L
_TARGET_FLAGS_MASK = AppKit.NSCommandKeyMask | AppKit.NSShiftKeyMask


class HotkeyManager:
    """Gestionnaire de raccourci global Cmd+Shift+L → toggle HUD."""

    def __init__(self, hud_window: Any) -> None:
        self.hud = hud_window
        self._monitor: Optional[Any] = None
        self._setup()

    def _setup(self) -> None:
        """Enregistre le monitor global pour Cmd+Shift+L."""
        if not AXIsProcessTrusted():
            logger.warning(
                "⌨️ Accessibilité non autorisée → Cmd+Shift+L désactivé. "
                "Autoriser Lucie dans Réglages → Confidentialité → Accessibilité"
            )
            try:
                AppKit.NSWorkspace.sharedWorkspace().openURL_(
                    AppKit.NSURL.URLWithString_(
                        "x-apple.systempreferences:"
                        "com.apple.preference.security?Privacy_Accessibility"
                    )
                )
            except Exception as _e:
                logger.debug(f"Ouverture préférences accessibilité échouée : {_e}")
            return

        try:
            mask = AppKit.NSEventMaskKeyDown
            self._monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                mask, self._handle_key,
            )
            logger.info("⌨️ Hotkey Cmd+Shift+L enregistré")
        except Exception as e:
            logger.warning(f"⌨️ Hotkey non disponible : {e}")

    def _handle_key(self, event: Any) -> None:
        """Détecte Cmd+Shift+L et toggle le HUD avec animation."""
        try:
            flags = event.modifierFlags()
            key = event.keyCode()
            # Isoler uniquement les flags qui nous intéressent (ignorer CapsLock, etc.)
            relevant = flags & (AppKit.NSCommandKeyMask | AppKit.NSShiftKeyMask
                                | AppKit.NSAlternateKeyMask | AppKit.NSControlKeyMask)
            if relevant == _TARGET_FLAGS_MASK and key == _TARGET_KEYCODE:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(self._toggle)
        except Exception as _e:
            logger.debug(f"Hotkey handler échoué : {_e}")

    def _toggle(self) -> None:
        """Toggle HUD visible/caché avec spring animations."""
        try:
            if self.hud.isVisible():
                # Sortie avec animation spring si disponible
                if hasattr(self.hud, "animateOut"):
                    self.hud.animateOut()
                else:
                    self.hud.orderOut_(None)
            else:
                self.hud.makeKeyAndOrderFront_(None)
                self.hud.orderFrontRegardless()
                if hasattr(self.hud, "animateIn"):
                    self.hud.animateIn()
        except Exception as _e:
            logger.debug(f"Toggle HUD échoué : {_e}")

    def stop(self) -> None:
        """Désenregistre le monitor global."""
        if self._monitor:
            AppKit.NSEvent.removeMonitor_(self._monitor)
            self._monitor = None
