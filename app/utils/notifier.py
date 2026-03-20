"""
Notifier — notifications macOS.
Corrections v2 :
  - filepath: Optional[str] partout
  - UserNotifications guard complet
  - NSUserNotification déprécié → type: ignore
"""

import subprocess
from typing import Optional

from .logger import logger

# ── AppKit (PyObjC) ───────────────────────────────────────────────────────────
try:
    import AppKit  # type: ignore[import]
    _APPKIT_OK = True
except ImportError:
    _APPKIT_OK = False

# ── UserNotifications (macOS 10.14+) ─────────────────────────────────────────
try:
    import UserNotifications  # type: ignore[import]  # noqa: F401
    HAS_UN = True
except ImportError:
    HAS_UN = False


def send_notification(
    title: str,
    message: str,
    filepath: Optional[str] = None,  # FIX : Optional[str]
) -> None:
    """Envoie une notification macOS interactive avec son."""
    if HAS_UN:
        _send_via_un(title, message, filepath)
    elif _APPKIT_OK:
        _send_via_ns(title, message, filepath)
    else:
        _send_via_osascript(title, message, filepath)


def _send_via_un(title: str, message: str, filepath: Optional[str] = None) -> None:
    """Utilise UNUserNotificationCenter (moderne, macOS 10.14+)."""
    if not HAS_UN:
        _send_via_ns(title, message, filepath)
        return

    import UserNotifications as UN  # type: ignore[import]

    center = UN.UNUserNotificationCenter.currentNotificationCenter()

    def check_auth(granted: bool, error: object) -> None:
        if not granted:
            logger.warning("Notifications UN non autorisées, fallback NSUserNotification")
            _send_via_ns(title, message, filepath)
            return

        content = UN.UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(message)
        content.setSound_(UN.UNNotificationSound.defaultSound())

        if filepath:
            content.setUserInfo_({"filepath": filepath, "action": "open_file"})
            action = UN.UNNotificationAction.actionWithIdentifier_title_options_(
                "OPEN_ACTION", "Ouvrir", 1
            )
            category = UN.UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
                "OPEN_CATEGORY", [action], [], 1
            )
            center.setNotificationCategories_([category])
            content.setCategoryIdentifier_("OPEN_CATEGORY")

        request = UN.UNNotificationRequest.requestWithIdentifier_content_trigger_(
            f"notif_{title}_{message[:20]}", content, None
        )
        center.addNotificationRequest_withCompletionHandler_(request, lambda err: None)

    center.requestAuthorizationWithOptions_completionHandler_(3, check_auth)


def _send_via_ns(title: str, message: str, filepath: Optional[str] = None) -> None:
    """Fallback NSUserNotification (déprécié mais fonctionnel)."""
    if not _APPKIT_OK:
        _send_via_osascript(title, message, filepath)
        return
    try:
        notification = AppKit.NSUserNotification.alloc().init()  # type: ignore[attr-defined]
        notification.setTitle_(title)
        notification.setInformativeText_(message)
        notification.setSoundName_("NSUserNotificationDefaultSoundName")

        if filepath:
            notification.setActionButtonTitle_("Ouvrir")
            notification.setUserInfo_({"filepath": filepath, "action": "open_file"})
            notification.setHasActionButton_(True)
        else:
            notification.setHasActionButton_(False)

        centre = AppKit.NSUserNotificationCenter.defaultUserNotificationCenter()  # type: ignore[attr-defined]
        centre.scheduleNotification_(notification)
    except Exception as e:
        logger.warning(f"Échec NSUserNotification: {e}")
        _send_via_osascript(title, message, filepath)


def _send_via_osascript(title: str, message: str, filepath: Optional[str] = None) -> None:
    """Ultime fallback osascript."""
    try:
        script = f'display notification "{message}" with title "{title}" sound name "default"'
        if filepath:
            script += ' subtitle "Cliquez pour ouvrir"'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception as e:
        logger.error(f"Impossible d'envoyer la notification : {e}")
