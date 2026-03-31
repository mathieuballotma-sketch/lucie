"""
AccessibilityMonitor — Observe le focus utilisateur via l'Accessibility API.

Utilise AXObserver + AXUIElement pour détecter :
- Quelle application est au premier plan
- Quel champ de texte a le focus
- Changements de fenêtre

NOTE : Ce module nécessite macOS + pyobjc. Sur d'autres plateformes,
le moniteur fonctionne en mode stub (contexte vide).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ...utils.logger import logger

# Import conditionnel macOS
try:
    import AppKit
    import Quartz
    import objc
    _HAS_MACOS = True
except ImportError:
    _HAS_MACOS = False


@dataclass
class FocusContext:
    """Contexte de focus actuel de l'utilisateur."""
    app_name: str = ""
    app_bundle_id: str = ""
    window_title: str = ""
    focused_element: str = ""
    is_text_input: bool = False
    timestamp: float = 0.0

    @property
    def domain(self) -> str:
        """Détermine le domaine d'activité de l'utilisateur."""
        _DOMAIN_MAP = {
            "com.apple.mail": "communication",
            "com.apple.Safari": "web",
            "com.google.Chrome": "web",
            "com.microsoft.VSCode": "code",
            "com.apple.dt.Xcode": "code",
            "com.apple.finder": "files",
            "com.apple.Terminal": "code",
            "com.apple.Notes": "writing",
            "com.apple.Pages": "writing",
            "com.microsoft.Word": "writing",
            "com.microsoft.Excel": "data",
            "com.apple.iCal": "calendar",
            "com.tinyspeck.slackmacgap": "communication",
            "us.zoom.xos": "communication",
            "com.spotify.client": "media",
        }
        return _DOMAIN_MAP.get(self.app_bundle_id, "general")


class AccessibilityMonitor:
    """
    Moniteur d'accessibilité utilisant NSWorkspace notifications
    + AXUIElement pour le contexte de focus.

    Design défensif :
    - Vérifie les permissions au démarrage
    - Fallback gracieux si pas de permission (NSWorkspace seul)
    - Pas de polling — uniquement des observers/notifications
    - Thread dédié pour les callbacks Accessibility

    Mode stub sur Linux : retourne un FocusContext vide.
    """

    def __init__(self) -> None:
        self._current_focus = FocusContext()
        self._listeners: List[Callable[[FocusContext], None]] = []
        self._has_ax_permission: bool = False
        self._running: bool = False
        self._lock = threading.Lock()

    def start(self) -> bool:
        """
        Démarre le monitoring.
        Retourne True si démarré avec succès.
        """
        if self._running:
            return True

        if not _HAS_MACOS:
            logger.info(
                "AccessibilityMonitor: mode stub (non-macOS)"
            )
            self._running = True
            return True

        # Vérifier la permission Accessibility
        self._has_ax_permission = self._check_ax_permission()
        if not self._has_ax_permission:
            logger.warning(
                "AccessibilityMonitor : permission non accordée. "
                "Fonctionnement dégradé (NSWorkspace uniquement). "
                "Activer dans Préférences Système > Confidentialité > Accessibilité"
            )

        # Observer les changements d'application via NSWorkspace
        ws = AppKit.NSWorkspace.sharedWorkspace()
        nc = ws.notificationCenter()

        nc.addObserver_selector_name_object_(
            self,
            objc.selector(self._on_app_activated_, signature=b"v@:@"),
            AppKit.NSWorkspaceDidActivateApplicationNotification,
            None,
        )

        self._running = True
        self._capture_current_focus()

        logger.info(
            f"AccessibilityMonitor démarré "
            f"(AX permission: {self._has_ax_permission})"
        )
        return True

    def stop(self) -> None:
        """Arrêt propre du monitoring."""
        if not self._running:
            return
        self._running = False

        if _HAS_MACOS:
            ws = AppKit.NSWorkspace.sharedWorkspace()
            ws.notificationCenter().removeObserver_(self)

        logger.info("AccessibilityMonitor arrêté")

    def _check_ax_permission(self) -> bool:
        """Vérifie si l'application a la permission Accessibility."""
        if not _HAS_MACOS:
            return False
        try:
            trusted = Quartz.AXIsProcessTrustedWithOptions(
                {Quartz.kAXTrustedCheckOptionPrompt: False}
            )
            return bool(trusted)
        except Exception as e:
            logger.debug(f"AX permission check failed: {e}")
            return False

    def _capture_current_focus(self) -> None:
        """Capture le focus actuel sans attendre de notification."""
        if not _HAS_MACOS:
            return
        try:
            ws = AppKit.NSWorkspace.sharedWorkspace()
            active_app = ws.frontmostApplication()
            if active_app:
                self._update_focus(
                    app_name=active_app.localizedName() or "",
                    bundle_id=active_app.bundleIdentifier() or "",
                )
        except Exception as e:
            logger.debug(f"Capture focus initiale échouée: {e}")

    def _on_app_activated_(self, notification: Any) -> None:
        """Callback NSWorkspace — une app passe au premier plan."""
        try:
            user_info = notification.userInfo()
            app = user_info.get("NSWorkspaceApplicationKey")
            if app:
                app_name = app.localizedName() or ""
                bundle_id = app.bundleIdentifier() or ""
                self._update_focus(app_name=app_name, bundle_id=bundle_id)
        except Exception as e:
            logger.debug(f"App activated callback error: {e}")

    def _update_focus(self, app_name: str, bundle_id: str,
                      window_title: str = "", focused_role: str = "") -> None:
        """Met à jour le contexte de focus et notifie les listeners."""
        is_text = focused_role in ("AXTextField", "AXTextArea", "AXComboBox")

        new_focus = FocusContext(
            app_name=app_name,
            app_bundle_id=bundle_id,
            window_title=window_title,
            focused_element=focused_role,
            is_text_input=is_text,
            timestamp=time.time(),
        )

        with self._lock:
            if (self._current_focus.app_bundle_id == bundle_id and
                    self._current_focus.focused_element == focused_role):
                return
            self._current_focus = new_focus

        for listener in self._listeners:
            try:
                listener(new_focus)
            except Exception as e:
                logger.debug(f"Focus listener error: {e}")

    def add_listener(self, callback: Callable[[FocusContext], None]) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[FocusContext], None]) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    @property
    def current_focus(self) -> FocusContext:
        with self._lock:
            return self._current_focus

    @property
    def has_permission(self) -> bool:
        return self._has_ax_permission
