"""
HotkeyManager — Raccourci global ⌥Space pour toggle HUD.

Utilise addGlobalMonitorForEventsMatchingMask_ de NSEvent.
Nécessite les permissions d'accessibilité macOS.
"""

from __future__ import annotations

from typing import Any, Optional

import AppKit  # type: ignore[import]

from ..utils.logger import logger


class HotkeyManager:
    """Gestionnaire de raccourci global ⌥Space → toggle HUD."""

    def __init__(self, hud_window: Any) -> None:
        self.hud = hud_window
        self._monitor: Optional[Any] = None
        self._setup()

    def _setup(self) -> None:
        """Enregistre le monitor global pour ⌥Space."""
        # Vérifier les permissions d'accessibilité
        if not AppKit.AXIsProcessTrusted():
            logger.warning(
                "⌨️ Accessibilité non autorisée → ⌥Space désactivé. "
                "Autoriser Lucie dans Réglages → Accessibilité"
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
            logger.info("⌨️ Hotkey ⌥Space enregistré")
        except Exception as e:
            logger.warning(f"⌨️ Hotkey non disponible : {e}")

    def _handle_key(self, event: Any) -> None:
        """Détecte ⌥Space et toggle le HUD."""
        try:
            flags = event.modifierFlags()
            key = event.keyCode()
            # ⌥ (Option) = NSAlternateKeyMask, Space = keyCode 49
            if (flags & AppKit.NSAlternateKeyMask) and key == 49:
                # Exécuter le toggle sur le main thread via AppHelper
                from PyObjCTools import AppHelper  # type: ignore[import]
                AppHelper.callAfter(self._toggle)
        except Exception as _e:
            logger.debug(f"Hotkey handler échoué : {_e}")

    def _toggle(self) -> None:
        """Toggle HUD visible/caché."""
        try:
            if self.hud.isVisible():
                self.hud.orderOut_(None)
            else:
                self.hud.makeKeyAndOrderFront_(None)
                self.hud.orderFrontRegardless()
        except Exception as _e:
            logger.debug(f"Toggle HUD échoué : {_e}")

    def stop(self) -> None:
        """Désenregistre le monitor global."""
        if self._monitor:
            AppKit.NSEvent.removeMonitor_(self._monitor)
            self._monitor = None
