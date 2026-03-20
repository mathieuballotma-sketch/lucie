"""
Agent de contrôle de l'ordinateur — version étendue et optimisée.
Corrections v2 :
  - NSScreen utilisé uniquement si FOUND_APPKIT (type-narrowing)
  - _tool_click, _tool_get_screenshot, _tool_move_mouse implémentés
    (étaient référencés dans handle() mais absents)
"""

import asyncio
import os
import re
import time
from datetime import datetime
from typing import List, Optional, Tuple

import pyautogui
from pydantic.v1 import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.utils.errors import ToolExecutionError
from app.utils.logger import logger
from app.utils.metrics import record_tool_execution

try:
    import AppKit
    from AppKit import NSScreen
    FOUND_APPKIT = True
except ImportError:
    FOUND_APPKIT = False
    logger.warning("AppKit non disponible — certaines fonctionnalités sont limitées.")



# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────
OPEN_KEYWORDS       = ["ouvre", "lance", "open", "launch"]
TYPE_KEYWORDS       = ["tape", "écris", "type"]
CLICK_KEYWORDS      = ["clique", "click"]
SCREENSHOT_KEYWORDS = ["screenshot", "capture écran"]
MOVE_KEYWORDS       = ["déplace", "move"]
ARRANGE_KEYWORDS    = ["côte à côte", "side by side", "organise", "grille", "disposition"]
MAIL_KEYWORDS       = ["mail", "email", "courriel", "message"]
SAFARI_KEYWORDS     = ["safari", "navigateur", "internet", "page web", "url"]

NOTES_APPS = ["notes"]
KNOWN_APPS = [
    "notes", "calculatrice", "safari", "mail", "calendar", "terminal",
    "finder", "chrome", "firefox", "slack", "discord", "spotify",
    "visual studio code", "code", "pages", "numbers", "keynote",
    "app store", "calendrier", "contacts", "messages", "facetime",
    "musique", "photos", "préférences système", "réglages",
    "reminders", "rappel",
]

OPEN_PATTERNS = [
    r"ouvre (?:l'application\s+)?([a-zA-Z0-9\s]+)",
    r"lance (?:l'application\s+)?([a-zA-Z0-9\s]+)",
    r"open (?:the )?([a-zA-Z0-9\s]+)",
    r"launch (?:the )?([a-zA-Z0-9\s]+)",
]
TYPE_PATTERNS  = [r"tape (.*)", r"écris (.*)", r"type (.*)"]
QUOTE_PATTERN  = r"['\"](.+?)['\"]"
COORDS_PATTERN = r"(\d+)\s*[,\s]\s*(\d+)"
ARTICLE_PATTERN = r"^(l'|le |la |les )"

SCREENSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "screenshots"
)

ARRANGE_PATTERNS = {
    "side_by_side": r"(c[ôo]te[ -]à[ -]c[ôo]te|side[ -]by[ -]side)",
    "grid_2x2":     r"(grille|2x2|quatre|four)",
}

APPS_NEEDING_WINDOW = ["mail", "notes", "calendar", "messages", "facetime"]

# Caractères interdits dans les chaînes injectées dans les scripts AppleScript.
# Vecteurs d'injection : " (délimiteur de chaîne), \ (escape), & (concat AS), { } (enregistrement AS)
APPLESCRIPT_FORBIDDEN_CHARS: frozenset = frozenset('"\\&{}')


# ─────────────────────────────────────────────────────────────────────────────
# Contrats Pydantic
# ─────────────────────────────────────────────────────────────────────────────
class ComputerControlOpenApplicationContract(BaseModel):
    app_name: str = Field(..., description="Nom exact de l'application")

class ComputerControlTypeTextContract(BaseModel):
    text:             str           = Field(...,   description="Texte à taper")
    interval:         float         = Field(0.05,  description="Intervalle entre frappes (s)")
    app_name:         Optional[str] = Field(None,  description="Application cible")
    correct_spelling: bool          = Field(False, description="Corriger orthographe")

class ComputerControlPressKeyContract(BaseModel):
    key: str = Field(..., description="Touche à presser")

class ComputerControlClickContract(BaseModel):
    x:             int   = Field(...,   description="Coordonnée X")
    y:             int   = Field(...,   description="Coordonnée Y")
    button:        str   = Field("left", description="Bouton (left/right/middle)")
    move_duration: float = Field(0.5,   description="Durée du déplacement (s)")

class ComputerControlMoveMouseContract(BaseModel):
    x:        int   = Field(...,  description="Coordonnée X")
    y:        int   = Field(...,  description="Coordonnée Y")
    duration: float = Field(0.5, description="Durée déplacement (s)")

class ComputerControlGetScreenshotContract(BaseModel):
    pass

class ComputerControlMailComposeContract(BaseModel):
    to:      str  = Field(...,   description="Destinataire (adresse email)")
    subject: str  = Field("",   description="Sujet du message")
    body:    str  = Field("",   description="Corps du message")
    send:    bool = Field(False, description="Envoyer immédiatement après rédaction")

class ComputerControlSafariOpenUrlContract(BaseModel):
    url:     str  = Field(...,   description="URL à ouvrir")
    new_tab: bool = Field(False, description="Ouvrir dans un nouvel onglet")

class ComputerControlArrangeWindowsContract(BaseModel):
    layout: str               = Field(...,  description="Type: 'side_by_side', 'grid_2x2'")
    apps:   Optional[List[str]] = Field(None, description="Liste des applications")


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────
class ComputerControlAgent(BaseAgent):
    """Agent capable d'effectuer des actions visibles sur l'ordinateur."""

    def __init__(self, llm_service, bus, config: dict):
        super().__init__("ComputerControlAgent", llm_service, bus)
        pyautogui.FAILSAFE = True

        self.visible_mode                = config.get("visible_actions", True)
        self.move_duration               = config.get("move_duration", 0.5)
        self.type_interval               = config.get("type_interval", 0.05)
        self.use_spell_check             = config.get("use_spell_check", False)
        self.use_applescript_for_typing  = config.get("use_applescript_for_typing", False)
        self.use_paste_for_typing        = config.get("use_paste_for_typing", True)

        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        logger.info(f"🖱️ ComputerControlAgent initialisé (mode visible={self.visible_mode})")

    @staticmethod
    def _check_applescript_safety(value: str, field_name: str) -> None:
        """Rejette toute valeur contenant des caractères dangereux pour AppleScript.

        Vecteurs d'injection : guillemet (délimiteur), backslash (escape),
        & (concaténation AppleScript), { } (enregistrement AppleScript).
        Lève ToolExecutionError si un caractère interdit est détecté.
        """
        found = APPLESCRIPT_FORBIDDEN_CHARS.intersection(value)
        if found:
            raise ToolExecutionError(
                f"Valeur interdite pour AppleScript — champ '{field_name}' "
                f"contient les caractères dangereux : {sorted(found)}"
            )

    def get_tools(self) -> list:
        return [
            Tool(name="open_application",  description="Ouvre une application macOS.",                        contract=ComputerControlOpenApplicationContract),
            Tool(name="type_text",         description="Tape un texte.",                                      contract=ComputerControlTypeTextContract),
            Tool(name="press_key",         description="Presse une touche spéciale.",                         contract=ComputerControlPressKeyContract),
            Tool(name="click",             description="Clique à une position (x, y).",                       contract=ComputerControlClickContract),
            Tool(name="move_mouse",        description="Déplace la souris à une position (x, y).",            contract=ComputerControlMoveMouseContract),
            Tool(name="get_screenshot",    description="Capture l'écran.",                                    contract=ComputerControlGetScreenshotContract),
            Tool(name="mail_compose",      description="Ouvre Mail et crée un nouveau message.",              contract=ComputerControlMailComposeContract),
            Tool(name="safari_open_url",   description="Ouvre une URL dans Safari.",                         contract=ComputerControlSafariOpenUrlContract),
            Tool(name="arrange_windows",   description="Organise les fenêtres (côte à côte, grille).",       contract=ComputerControlArrangeWindowsContract),
        ]

    # ── AppleScript helpers ───────────────────────────────────────────────────

    async def _run_applescript(self, script: str, timeout: float = 5.0) -> Tuple[bool, str]:
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

    async def _activate_app(self, app_name: str) -> None:
        # Valider contre la whitelist d'applications connues
        if app_name.lower().strip() not in KNOWN_APPS:
            raise ToolExecutionError(f"Application non reconnue dans la whitelist : '{app_name}'")
        # Rejeter les caractères dangereux pour AppleScript
        self._check_applescript_safety(app_name, "app_name")
        script = f'tell application "{app_name}" to activate'
        success, error = await self._run_applescript(script, timeout=8.0)
        if not success:
            raise Exception(f"Échec activation de '{app_name}': {error}")

    def _get_active_app_name(self) -> Optional[str]:
        if not FOUND_APPKIT:
            return None
        try:
            workspace = AppKit.NSWorkspace.sharedWorkspace()  # type: ignore[attr-defined]
            active_app = workspace.frontmostApplication()
            return active_app.localizedName() if active_app else None
        except Exception as e:
            logger.debug(f"Erreur get_active_app_name : {e}")
            return None

    async def _wait_for_app_active(self, app_name: str, timeout: float = 2.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            active = self._get_active_app_name()
            if active and app_name.lower() in active.lower():
                return True
            await asyncio.sleep(0.1)
        return False

    async def _create_new_note_in_notes(self) -> bool:
        script = """
tell application "Notes"
    activate
end tell
tell application "System Events"
    keystroke "n" using command down
end tell
"""
        success, _ = await self._run_applescript(script, timeout=3.0)
        if not success:
            pyautogui.hotkey("command", "n")
            await asyncio.sleep(0.5)
        return True

    async def _focus_note_body(self) -> None:
        await self._wait_for_app_active("Notes", timeout=2.0)
        pyautogui.press("tab")
        await asyncio.sleep(0.2)

    async def _type_text_with_applescript(self, text: str, interval: float = 0.05, use_paste: bool = False) -> bool:
        if use_paste:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pbcopy", stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.communicate(input=text.encode("utf-8"))
                await asyncio.sleep(0.1)
                script = 'tell application "System Events" to keystroke "v" using command down'
                success, _ = await self._run_applescript(script, timeout=2.0)
                return success
            except Exception as e:
                logger.error(f"Erreur collage AppleScript: {e}")
                return False
        else:
            escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            script = f"""
set textToType to "{escaped}"
repeat with i from 1 to count of characters of textToType
    tell application "System Events" to keystroke (character i of textToType)
    delay {interval}
end repeat
"""
            success, _ = await self._run_applescript(script, timeout=5.0)
            return success

    async def _ensure_app_window(self, app_name: str) -> None:
        app_lower = app_name.lower()
        if app_lower not in APPS_NEEDING_WINDOW:
            return
        scripts = {
            "mail":     ('tell application "Mail" to exists window 1',     'tell application "Mail" to make new window'),
            "notes":    ('tell application "Notes" to exists window 1',    'tell application "Notes" to activate\ntell application "System Events" to keystroke "n" using command down'),
            "calendar": ('tell application "Calendar" to exists window 1', 'tell application "Calendar" to activate'),
            "messages": ('tell application "Messages" to exists window 1', 'tell application "Messages" to activate'),
            "facetime": ('tell application "FaceTime" to exists window 1', 'tell application "FaceTime" to activate'),
        }
        if app_lower not in scripts:
            return
        check_script, new_script = scripts[app_lower]
        success, output = await self._run_applescript(check_script, timeout=3.0)
        if success and output.strip().lower() == "true":
            return
        await self._run_applescript(new_script, timeout=3.0)
        await asyncio.sleep(0.5)

    # ── Outils ───────────────────────────────────────────────────────────────

    async def _tool_open_application(self, app_name: str) -> str:
        start = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                "open", "-a", app_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Erreur inconnue"
                record_tool_execution(self.name, "open_application", time.time() - start, error=True)
                raise ToolExecutionError(f"Impossible d'ouvrir '{app_name}' : {error_msg}")
        except asyncio.TimeoutError:
            record_tool_execution(self.name, "open_application", time.time() - start, error=True)
            raise ToolExecutionError(f"Timeout lors de l'ouverture de '{app_name}'.")

        await self._wait_for_app_active(app_name, timeout=3.0)
        await self._ensure_app_window(app_name)
        record_tool_execution(self.name, "open_application", time.time() - start, error=False)
        return f"✅ Application '{app_name}' ouverte."

    async def _tool_type_text(
        self, text: str, interval: float = 0.05,
        app_name: Optional[str] = None, correct_spelling: bool = False
    ) -> str:
        if not await self.submit_action({
            "action_type": "type_text",
            "preview": f"type_text: {text[:50]!r}",
            "reversible": True,
        }):
            return "⛔ Action 'type_text' bloquée par ActionGate."
        start = time.time()
        if app_name:
            try:
                await self._activate_app(app_name)
                await self._wait_for_app_active(app_name, timeout=2.0)
            except Exception as e:
                logger.warning(f"Impossible d'activer {app_name}: {e}")

        active = self._get_active_app_name()
        target_is_notes = (
            (app_name and "notes" in app_name.lower())
            or (active and "notes" in active.lower())
        )

        if target_is_notes:
            await self._create_new_note_in_notes()
            await self._focus_note_body()
            success = await self._type_text_with_applescript(text, interval, use_paste=False)
            if not success:
                pyautogui.typewrite(text, interval=interval)
        else:
            success = False
            if self.use_applescript_for_typing and self.use_paste_for_typing:
                success = await self._type_text_with_applescript(text, interval, use_paste=True)
            if not success and self.use_applescript_for_typing:
                success = await self._type_text_with_applescript(text, interval, use_paste=False)
            if not success:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "pbcopy", stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await proc.communicate(input=text.encode("utf-8"))
                    await asyncio.sleep(0.2)
                    pyautogui.hotkey("command", "v")
                    success = True
                except Exception as e:
                    logger.error(f"Erreur collage: {e}")
            if not success:
                pyautogui.typewrite(text, interval=interval)

        record_tool_execution(self.name, "type_text", time.time() - start, error=False)
        return f"✅ Texte tapé ({len(text)} caractères)."

    async def _tool_press_key(self, key: str) -> str:
        if not await self.submit_action({
            "action_type": "press_key",
            "preview": f"press_key: {key!r}",
            "reversible": True,
        }):
            return "⛔ Action 'press_key' bloquée par ActionGate."
        pyautogui.press(key)
        return f"✅ Touche '{key}' pressée."

    async def _tool_click(self, x: int, y: int, button: str = "left", move_duration: float = 0.5) -> str:
        """FIX v2 : méthode manquante ajoutée."""
        if not await self.submit_action({
            "action_type": "click",
            "preview": f"click {button} at ({x}, {y})",
            "reversible": True,
        }):
            return "⛔ Action 'click' bloquée par ActionGate."
        start = time.time()
        try:
            pyautogui.moveTo(x, y, duration=move_duration)
            pyautogui.click(x, y, button=button)
            record_tool_execution(self.name, "click", time.time() - start, error=False)
            return f"✅ Clic {button} en ({x}, {y})."
        except Exception as e:
            record_tool_execution(self.name, "click", time.time() - start, error=True)
            raise ToolExecutionError(f"Erreur clic : {e}")

    async def _tool_move_mouse(self, x: int, y: int, duration: float = 0.5) -> str:
        """FIX v2 : méthode manquante ajoutée."""
        start = time.time()
        try:
            pyautogui.moveTo(x, y, duration=duration)
            record_tool_execution(self.name, "move_mouse", time.time() - start, error=False)
            return f"✅ Souris déplacée en ({x}, {y})."
        except Exception as e:
            record_tool_execution(self.name, "move_mouse", time.time() - start, error=True)
            raise ToolExecutionError(f"Erreur déplacement souris : {e}")

    async def _tool_get_screenshot(self) -> str:
        """FIX v2 : méthode manquante ajoutée."""
        start = time.time()
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(SCREENSHOT_DIR, f"screenshot_{timestamp}.png")
            screenshot = pyautogui.screenshot()
            screenshot.save(path)
            record_tool_execution(self.name, "get_screenshot", time.time() - start, error=False)
            return f"✅ Screenshot sauvegardé : {path}"
        except Exception as e:
            record_tool_execution(self.name, "get_screenshot", time.time() - start, error=True)
            raise ToolExecutionError(f"Erreur screenshot : {e}")

    async def _tool_mail_compose(self, to: str, subject: str = "", body: str = "", send: bool = False) -> str:
        if not await self.submit_action({
            "action_type": "mail_compose",
            "preview": f"mail to={to!r} subject={subject!r} send={send}",
            "reversible": not send,
        }):
            return "⛔ Action 'mail_compose' bloquée par ActionGate."
        start = time.time()

        # Valider les champs injectés directement dans le script AppleScript
        self._check_applescript_safety(to, "to")
        self._check_applescript_safety(subject, "subject")
        # Le corps est transmis via clipboard — aucune vérification de contenu nécessaire

        # Copier le corps dans le clipboard pour éviter toute injection AppleScript
        try:
            proc = await asyncio.create_subprocess_exec(
                "pbcopy", stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate(input=body.encode("utf-8"))
            await asyncio.sleep(0.1)
        except Exception as exc:
            raise ToolExecutionError(
                f"Impossible de copier le corps dans le clipboard : {exc}"
            ) from exc

        to_esc      = to.replace('"', '\\"')
        subject_esc = subject.replace('"', '\\"')

        # Le contenu est lu depuis le clipboard — aucune variable user dans l'f-string
        script = f"""
tell application "Mail"
    activate
    set newMessage to make new outgoing message with properties {{subject:"{subject_esc}", content:(the clipboard as text)}}
    tell newMessage
        make new to recipient at end of to recipients with properties {{address:"{to_esc}"}}
    end tell
    {"send newMessage" if send else ""}
end tell
"""
        success, error = await self._run_applescript(script, timeout=8.0)
        record_tool_execution(self.name, "mail_compose", time.time() - start, error=not success)
        if success:
            return f"✅ Email {'envoyé' if send else 'préparé'} pour {to}."
        raise ToolExecutionError(f"Erreur email: {error}")

    async def _tool_safari_open_url(self, url: str, new_tab: bool = False) -> str:
        if not await self.submit_action({
            "action_type": "safari_open_url",
            "preview": f"safari_open_url: {url!r}",
            "reversible": True,
        }):
            return "⛔ Action 'safari_open_url' bloquée par ActionGate."
        start = time.time()

        # Valider le format URL — doit commencer par http:// ou https://
        if not re.match(r'^https?://', url):
            raise ToolExecutionError(
                f"URL non sécurisée (doit commencer par http:// ou https://) : {url}"
            )

        # Passer l'URL via clipboard pour éviter toute injection dans l'f-string AppleScript
        try:
            proc = await asyncio.create_subprocess_exec(
                "pbcopy", stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate(input=url.encode("utf-8"))
            await asyncio.sleep(0.1)
        except Exception as exc:
            raise ToolExecutionError(
                f"Impossible de copier l'URL dans le clipboard : {exc}"
            ) from exc

        await self._activate_app("Safari")
        if not await self._wait_for_app_active("Safari", timeout=3.0):
            raise ToolExecutionError("Safari ne s'est pas activé")

        # L'URL est lue depuis le clipboard — aucune variable user dans le script AppleScript
        script = (
            'tell application "Safari" to tell window 1 to make new tab with properties {URL:(the clipboard as text)}'
            if new_tab
            else 'tell application "Safari" to set URL of document 1 to (the clipboard as text)'
        )
        success, error = await self._run_applescript(script, timeout=8.0)
        record_tool_execution(self.name, "safari_open_url", time.time() - start, error=not success)
        if success:
            return "✅ URL ouverte dans Safari."
        raise ToolExecutionError(f"Erreur Safari: {error}")

    async def _get_screen_size(self) -> Tuple[int, int]:
        # FIX v2 : NSScreen utilisé uniquement si FOUND_APPKIT
        if FOUND_APPKIT:
            try:
                screen = NSScreen.mainScreen()  # type: ignore[name-defined]
                frame = screen.frame()
                return int(frame.size.width), int(frame.size.height)
            except Exception:
                pass
        return 1440, 900

    async def _arrange_side_by_side(self, apps: List[str]) -> str:
        if len(apps) != 2:
            return "❌ Pour la disposition côte à côte, il faut exactement deux applications."
        width, height = await self._get_screen_size()
        half_width = width // 2
        errors = []
        for i, app in enumerate(apps):
            try:
                await self._activate_app(app)
                if not await self._wait_for_app_active(app, timeout=3.0):
                    errors.append(f"{app} ne s'est pas activée")
                    continue
                await asyncio.sleep(0.5)
                await self._ensure_app_window(app)
                x = 0 if i == 0 else half_width
                script = f"""
tell application "System Events"
    tell process "{app}"
        set position of window 1 to {{{x}, 0}}
        set size of window 1 to {{{half_width}, {height}}}
    end tell
end tell
"""
                success, err = await self._run_applescript(script, timeout=5.0)
                if not success:
                    errors.append(f"{app}: {err}")
            except Exception as e:
                errors.append(f"{app}: {e}")
        if errors:
            return f"⚠️ Disposition partielle : {', '.join(errors)}"
        return f"✅ {apps[0]} et {apps[1]} côte à côte."

    async def _arrange_grid_2x2(self, apps: List[str]) -> str:
        if len(apps) != 4:
            return "❌ Pour la grille, il faut exactement quatre applications."
        width, height = await self._get_screen_size()
        half_w, half_h = width // 2, height // 2
        positions = [(0, 0), (half_w, 0), (0, half_h), (half_w, half_h)]
        errors = []
        for i, app in enumerate(apps):
            x, y = positions[i]
            try:
                await self._activate_app(app)
                if not await self._wait_for_app_active(app, timeout=3.0):
                    errors.append(f"{app} ne s'est pas activée")
                    continue
                await asyncio.sleep(0.5)
                await self._ensure_app_window(app)
                script = f"""
tell application "System Events"
    tell process "{app}"
        set position of window 1 to {{{x}, {y}}}
        set size of window 1 to {{{half_w}, {half_h}}}
    end tell
end tell
"""
                success, err = await self._run_applescript(script, timeout=5.0)
                if not success:
                    errors.append(f"{app}: {err}")
            except Exception as e:
                errors.append(f"{app}: {e}")
        if errors:
            return f"⚠️ Disposition partielle : {', '.join(errors)}"
        return "✅ Fenêtres disposées en grille 2x2."

    async def _tool_arrange_windows(self, layout: str, apps: Optional[List[str]] = None) -> str:
        if not await self.submit_action({
            "action_type": "arrange_windows",
            "preview": f"arrange_windows: layout={layout!r} apps={apps}",
            "reversible": True,
        }):
            return "⛔ Action 'arrange_windows' bloquée par ActionGate."
        start = time.time()
        if layout == "side_by_side":
            if not apps or len(apps) < 2:
                return "❌ Paramètre 'apps' manquant (2 apps requises)."
            result = await self._arrange_side_by_side(apps)
        elif layout == "grid_2x2":
            if not apps or len(apps) < 4:
                return "❌ Paramètre 'apps' manquant (4 apps requises)."
            result = await self._arrange_grid_2x2(apps)
        else:
            result = f"❌ Disposition '{layout}' inconnue."
        record_tool_execution(self.name, "arrange_windows", time.time() - start, error=False)
        return result

    # ── Interface ─────────────────────────────────────────────────────────────

    def can_handle(self, query: str) -> bool:
        return self.can_handle_quick(query) >= 0.5

    def can_handle_quick(self, query: str) -> float:
        q = query.lower()
        score = 0.0
        if any(kw in q for kw in OPEN_KEYWORDS):
            score = max(score, 0.7)
            if any(app in q for app in KNOWN_APPS):
                score = max(score, 0.9)
        if any(kw in q for kw in TYPE_KEYWORDS):
            score = max(score, 0.6)
            if re.search(QUOTE_PATTERN, q):
                score = max(score, 0.85)
        if any(kw in q for kw in CLICK_KEYWORDS):
            score = max(score, 0.5)
            if re.search(COORDS_PATTERN, q):
                score = max(score, 0.8)
        if any(kw in q for kw in SCREENSHOT_KEYWORDS):
            score = max(score, 0.95)
        if any(kw in q for kw in MOVE_KEYWORDS) and re.search(COORDS_PATTERN, q):
            score = max(score, 0.8)
        if any(kw in q for kw in ARRANGE_KEYWORDS):
            score = max(score, 0.7)
        if any(kw in q for kw in MAIL_KEYWORDS):
            score = max(score, 0.7)
        if any(kw in q for kw in SAFARI_KEYWORDS):
            score = max(score, 0.7)
        return score

    async def handle(self, query: str) -> str:
        q = query.lower()

        if any(kw in q for kw in OPEN_KEYWORDS):
            app = self._parse_open_application(query)
            if app:
                return await self._tool_open_application(app_name=app)

        if any(kw in q for kw in TYPE_KEYWORDS):
            text = self._parse_type_text(query)
            if text:
                app_name = next((a for a in NOTES_APPS if a in q), None)
                return await self._tool_type_text(text=text, app_name=app_name)

        if any(kw in q for kw in CLICK_KEYWORDS):
            coords = self._parse_coords(query)
            if coords:
                return await self._tool_click(**coords)
            return "❓ Précise les coordonnées du clic (ex: 'clique à 500, 300')."

        if any(kw in q for kw in SCREENSHOT_KEYWORDS):
            return await self._tool_get_screenshot()

        if any(kw in q for kw in MOVE_KEYWORDS):
            coords = self._parse_coords(query)
            if coords:
                return await self._tool_move_mouse(**coords)
            return "❓ Précise les coordonnées de destination."

        if any(kw in q for kw in ARRANGE_KEYWORDS):
            layout = None
            if re.search(ARRANGE_PATTERNS["side_by_side"], q, re.IGNORECASE):
                layout = "side_by_side"
            elif re.search(ARRANGE_PATTERNS["grid_2x2"], q, re.IGNORECASE):
                layout = "grid_2x2"
            if layout:
                apps = [app.capitalize() for app in KNOWN_APPS if app in q]
                return await self._tool_arrange_windows(layout=layout, apps=apps or None)
            return "❓ Précise la disposition souhaitée."

        if any(kw in q for kw in MAIL_KEYWORDS):
            to_match = re.search(r"à\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", query)
            to = to_match.group(1) if to_match else ""
            subject_match = re.search(r"sujet\s*[:\s]\s*([^,\.]+)", query, re.IGNORECASE)
            subject = subject_match.group(1).strip() if subject_match else ""
            body_match = re.search(r"corps\s*[:\s]\s*(.+)", query, re.IGNORECASE)
            body = body_match.group(1).strip() if body_match else ""
            if to:
                return await self._tool_mail_compose(to=to, subject=subject, body=body)
            return "Pour envoyer un email, précisez le destinataire."

        if any(kw in q for kw in SAFARI_KEYWORDS):
            url_match = re.search(r"https?://[^\s]+", query)
            url = url_match.group() if url_match else "https://www.google.com"
            return await self._tool_safari_open_url(url=url)

        return await super().handle(query)

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_open_application(self, query: str) -> Optional[str]:
        for pat in OPEN_PATTERNS:
            match = re.search(pat, query, re.IGNORECASE)
            if match and match.lastindex:
                app = match.group(match.lastindex).strip()
                app = re.sub(ARTICLE_PATTERN, "", app, flags=re.IGNORECASE)
                return app.strip()
        return None

    def _parse_type_text(self, query: str) -> Optional[str]:
        match = re.search(QUOTE_PATTERN, query)
        if match:
            return match.group(1)
        for pat in TYPE_PATTERNS:
            match = re.search(pat, query, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _parse_coords(self, query: str) -> Optional[dict]:
        match = re.search(COORDS_PATTERN, query)
        if match:
            return {"x": int(match.group(1)), "y": int(match.group(2))}
        return None
