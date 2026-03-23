"""
AccessibilityLayer — interface AXUIElement via osascript pour les apps Apple natives.

Remplace les coordonnées fixes PyAutoGUI par des requêtes dynamiques
aux éléments UI via System Events / AXUIElement.
PyAutoGUI reste en fallback si AX échoue.
"""

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Any, Optional, Tuple

import pyautogui

from app.utils.logger import logger

# Chemin du journal d'accessibilité
_JOURNAL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "memory", "journals",
)
_JOURNAL_PATH = os.path.join(_JOURNAL_DIR, "accessibility_log.jsonl")


def _log_ax_event(
    action: str, app: str, success: bool, duration_ms: float,
    detail: str = "",
) -> None:
    """Ajoute une entrée au journal d'accessibilité."""
    try:
        os.makedirs(_JOURNAL_DIR, exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(),
            "action": action,
            "app": app,
            "success": success,
            "duration_ms": round(duration_ms, 1),
            "detail": detail,
        }
        with open(_JOURNAL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as _e:
        logger.debug(f"Journal AX échoué : {_e}")


class AccessibilityLayer:
    """Couche d'abstraction AXUIElement pour les interactions UI macOS."""

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    async def _run_osascript(script: str, timeout: float = 5.0) -> Tuple[bool, str]:
        """Exécute un script osascript et retourne (success, output)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode == 0:
                return True, stdout.decode().strip()
            return False, stderr.decode().strip()
        except asyncio.TimeoutError:
            return False, "Timeout"
        except Exception as e:
            return False, str(e)

    # ── API publique ──────────────────────────────────────────────────────

    async def get_frontmost_app(self) -> Optional[str]:
        """Retourne le nom du processus frontmost via System Events."""
        script = """
tell application "System Events"
    return name of first application process whose frontmost is true
end tell
"""
        t0 = time.perf_counter()
        success, output = await self._run_osascript(script, timeout=3.0)
        ms = (time.perf_counter() - t0) * 1000
        if success and output:
            _log_ax_event("get_frontmost_app", output, True, ms)
            return output
        _log_ax_event("get_frontmost_app", "?", False, ms, detail=output)
        return None

    async def get_element_position(
        self, app: str, element_type: str, title: str,
    ) -> Optional[Tuple[int, int]]:
        """Récupère la position (x, y) d'un élément UI via AXUIElement.

        Args:
            app: nom du processus (ex: "Safari", "Notes")
            element_type: type d'élément AX (ex: "button", "text field", "menu item")
            title: titre / description de l'élément

        Returns:
            (x, y) centre de l'élément, ou None si non trouvé.
        """
        escaped_title = title.replace('"', '\\"')
        escaped_app = app.replace('"', '\\"')
        script = f"""
tell application "System Events"
    tell process "{escaped_app}"
        try
            set el to first {element_type} whose title is "{escaped_title}"
            set pos to position of el
            set sz to size of el
            set cx to (item 1 of pos) + (item 1 of sz) div 2
            set cy to (item 2 of pos) + (item 2 of sz) div 2
            return (cx as text) & "," & (cy as text)
        on error
            try
                set el to first {element_type} whose description is "{escaped_title}"
                set pos to position of el
                set sz to size of el
                set cx to (item 1 of pos) + (item 1 of sz) div 2
                set cy to (item 2 of pos) + (item 2 of sz) div 2
                return (cx as text) & "," & (cy as text)
            on error
                return "NOT_FOUND"
            end try
        end try
    end tell
end tell
"""
        t0 = time.perf_counter()
        success, output = await self._run_osascript(script, timeout=5.0)
        ms = (time.perf_counter() - t0) * 1000

        if success and output and output != "NOT_FOUND":
            try:
                parts = output.split(",")
                x, y = int(parts[0].strip()), int(parts[1].strip())
                _log_ax_event(
                    "get_element_position", app, True, ms,
                    detail=f"{element_type}:{title} -> ({x},{y})",
                )
                return (x, y)
            except (ValueError, IndexError):
                pass

        _log_ax_event(
            "get_element_position", app, False, ms,
            detail=f"{element_type}:{title} -> {output}",
        )
        return None

    async def click_element(
        self, app: str, element_type: str, title: str,
    ) -> bool:
        """Clique sur un élément UI identifié par AX.

        Récupère la position via get_element_position, puis clique
        avec PyAutoGUI sur la position réelle.
        Retourne False si l'élément n'est pas trouvé.
        """
        pos = await self.get_element_position(app, element_type, title)
        if pos is None:
            logger.warning(
                f"AX click_element: élément non trouvé "
                f"({app}/{element_type}/{title}) — fallback nécessaire"
            )
            return False

        x, y = pos
        t0 = time.perf_counter()
        try:
            pyautogui.click(x, y)
            ms = (time.perf_counter() - t0) * 1000
            _log_ax_event(
                "click_element", app, True, ms,
                detail=f"{element_type}:{title} @ ({x},{y})",
            )
            logger.debug(f"AX click OK: {element_type}:{title} @ ({x},{y})")
            return True
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            _log_ax_event(
                "click_element", app, False, ms,
                detail=f"pyautogui error: {e}",
            )
            return False

    async def get_window_bounds(self, app: str) -> Optional[dict[str, Any]]:
        """Retourne {x, y, width, height} de la première fenêtre de l'app."""
        escaped_app = app.replace('"', '\\"')
        script = f"""
tell application "System Events"
    tell process "{escaped_app}"
        set pos to position of window 1
        set sz to size of window 1
        return (item 1 of pos as text) & "," & (item 2 of pos as text) & "," & (item 1 of sz as text) & "," & (item 2 of sz as text)
    end tell
end tell
"""
        t0 = time.perf_counter()
        success, output = await self._run_osascript(script, timeout=3.0)
        ms = (time.perf_counter() - t0) * 1000

        if success and output:
            try:
                parts = [int(p.strip()) for p in output.split(",")]
                result = {"x": parts[0], "y": parts[1], "width": parts[2], "height": parts[3]}
                _log_ax_event("get_window_bounds", app, True, ms, detail=str(result))
                return result
            except (ValueError, IndexError):
                pass

        _log_ax_event("get_window_bounds", app, False, ms, detail=output)
        return None

    async def is_app_running(self, app: str) -> bool:
        """Vérifie si une application est en cours d'exécution."""
        escaped_app = app.replace('"', '\\"')
        script = f"""
tell application "System Events"
    return (name of processes) contains "{escaped_app}"
end tell
"""
        t0 = time.perf_counter()
        success, output = await self._run_osascript(script, timeout=3.0)
        ms = (time.perf_counter() - t0) * 1000
        running = success and output.strip().lower() == "true"
        _log_ax_event("is_app_running", app, running, ms)
        return running

    async def bring_to_front(self, app: str) -> bool:
        """Active l'application et la met au premier plan."""
        escaped_app = app.replace('"', '\\"')
        script = f'tell application "{escaped_app}" to activate'
        t0 = time.perf_counter()
        success, output = await self._run_osascript(script, timeout=3.0)
        ms = (time.perf_counter() - t0) * 1000
        _log_ax_event("bring_to_front", app, success, ms, detail=output if not success else "")
        if not success:
            logger.warning(f"AX bring_to_front échoué pour {app}: {output}")
        return success
