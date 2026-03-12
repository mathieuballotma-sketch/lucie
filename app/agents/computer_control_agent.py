"""
Agent de contrôle de l'ordinateur — version étendue et optimisée.
Ajoute des outils pour Mail, Safari et l'organisation des fenêtres.
Inclut des vérifications rapides et des fallbacks robustes.
Correction : saisie dans Notes avec focus sur le corps.
"""

import asyncio
import os
import re
import time
from datetime import datetime
from typing import List, Optional, Tuple

import pyautogui
from pydantic import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.utils.errors import ToolExecutionError
from app.utils.logger import logger
from app.utils.metrics import record_tool_execution

try:
    import AppKit
    FOUND_APPKIT = True
    from AppKit import NSScreen
except ImportError:
    FOUND_APPKIT = False
    logger.warning("AppKit non disponible — certaines fonctionnalités sont limitées.")

import subprocess


# ---------------------------------------------------------------------------
# Constantes centralisées
# ---------------------------------------------------------------------------
OPEN_KEYWORDS = ["ouvre", "lance", "open", "launch"]
TYPE_KEYWORDS = ["tape", "écris", "type"]
CLICK_KEYWORDS = ["clique", "click"]
SCREENSHOT_KEYWORDS = ["screenshot", "capture écran"]
MOVE_KEYWORDS = ["déplace", "move"]
ARRANGE_KEYWORDS = ["côte à côte", "side by side", "organise", "grille", "disposition"]
MAIL_KEYWORDS = ["mail", "email", "courriel", "message"]
SAFARI_KEYWORDS = ["safari", "navigateur", "internet", "page web", "url"]

NOTES_APPS = ["notes"]
KNOWN_APPS = [
    "notes", "calculatrice", "safari", "mail", "calendar", "terminal",
    "finder", "chrome", "firefox", "slack", "discord", "spotify",
    "visual studio code", "code", "pages", "numbers", "keynote",
    "app store", "calendrier", "contacts", "messages", "facetime",
    "musique", "photos", "préférences système", "réglages",
]

OPEN_PATTERNS = [
    r"ouvre (?:l'application\s+)?([a-zA-Z0-9\s]+)",
    r"lance (?:l'application\s+)?([a-zA-Z0-9\s]+)",
    r"open (?:the )?([a-zA-Z0-9\s]+)",
    r"launch (?:the )?([a-zA-Z0-9\s]+)",
]
TYPE_PATTERNS = [
    r"tape (.*)",
    r"écris (.*)",
    r"type (.*)",
]
QUOTE_PATTERN = r"['\"](.+?)['\"]"
COORDS_PATTERN = r"(\d+)\s*[,\s]\s*(\d+)"
ARTICLE_PATTERN = r"^(l'|le |la |les )"

SCREENSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "screenshots"
)

ARRANGE_PATTERNS = {
    "side_by_side": r"(c[ôo]te[ -]à[ -]c[ôo]te|side[ -]by[ -]side)",
    "grid_2x2": r"(grille|2x2|quatre|four)",
}

# Applications qui nécessitent une création de fenêtre explicite
APPS_NEEDING_WINDOW = ["mail", "notes", "calendar", "messages", "facetime"]


# ---------------------------------------------------------------------------
# Contrats Pydantic
# ---------------------------------------------------------------------------
class ComputerControlOpenApplicationContract(BaseModel):
    app_name: str = Field(..., description="Nom exact de l'application")


class ComputerControlTypeTextContract(BaseModel):
    text: str = Field(..., description="Texte à taper")
    interval: float = Field(0.05, description="Intervalle entre frappes (s)")
    app_name: Optional[str] = Field(None, description="Application cible")
    correct_spelling: bool = Field(False, description="Corriger orthographe")


class ComputerControlPressKeyContract(BaseModel):
    key: str = Field(..., description="Touche à presser")


class ComputerControlClickContract(BaseModel):
    x: int = Field(..., description="Coordonnée X")
    y: int = Field(..., description="Coordonnée Y")
    button: str = Field("left", description="Bouton (left/right/middle)")
    move_duration: float = Field(0.5, description="Durée du déplacement (s)")


class ComputerControlMoveMouseContract(BaseModel):
    x: int = Field(..., description="Coordonnée X")
    y: int = Field(..., description="Coordonnée Y")
    duration: float = Field(0.5, description="Durée déplacement (s)")


class ComputerControlGetScreenshotContract(BaseModel):
    pass


class ComputerControlMailComposeContract(BaseModel):
    to: str = Field(..., description="Destinataire (adresse email)")
    subject: str = Field("", description="Sujet du message")
    body: str = Field("", description="Corps du message")
    send: bool = Field(False, description="Envoyer immédiatement après rédaction")


class ComputerControlSafariOpenUrlContract(BaseModel):
    url: str = Field(..., description="URL à ouvrir")
    new_tab: bool = Field(False, description="Ouvrir dans un nouvel onglet")


class ComputerControlArrangeWindowsContract(BaseModel):
    layout: str = Field(..., description="Type de disposition: 'side_by_side', 'grid_2x2'")
    apps: Optional[List[str]] = Field(None, description="Liste des applications concernées")


# ---------------------------------------------------------------------------
# Agent principal
# ---------------------------------------------------------------------------
class ComputerControlAgent(BaseAgent):
    """
    Agent capable d'effectuer des actions sur l'ordinateur de façon visible.
    """

    def __init__(self, llm_service, bus, config: dict):
        super().__init__("ComputerControlAgent", llm_service, bus)
        pyautogui.FAILSAFE = True

        self.visible_mode = config.get("visible_actions", True)
        self.move_duration = config.get("move_duration", 0.5)
        self.type_interval = config.get("type_interval", 0.05)
        self.use_spell_check = config.get("use_spell_check", False)
        self.use_applescript_for_typing = config.get("use_applescript_for_typing", False)
        self.use_paste_for_typing = config.get("use_paste_for_typing", True)

        logger.info(f"🖱️ ComputerControlAgent initialisé (mode visible={self.visible_mode})")
        logger.info(f"   FOUND_APPKIT = {FOUND_APPKIT}")

    def get_tools(self) -> list:
        return [
            Tool(name="open_application", description="Ouvre une application macOS.", contract=ComputerControlOpenApplicationContract),
            Tool(name="type_text", description="Tape un texte. Si l'app cible est Notes, crée une nouvelle note.", contract=ComputerControlTypeTextContract),
            Tool(name="press_key", description="Presse une touche spéciale (enter, tab, escape…).", contract=ComputerControlPressKeyContract),
            Tool(name="click", description="Clique à une position (x, y) à l'écran.", contract=ComputerControlClickContract),
            Tool(name="move_mouse", description="Déplace la souris à une position (x, y).", contract=ComputerControlMoveMouseContract),
            Tool(name="get_screenshot", description="Capture l'écran et retourne le chemin du fichier.", contract=ComputerControlGetScreenshotContract),
            Tool(name="mail_compose", description="Ouvre Mail et crée un nouveau message.", contract=ComputerControlMailComposeContract),
            Tool(name="safari_open_url", description="Ouvre une URL dans Safari.", contract=ComputerControlSafariOpenUrlContract),
            Tool(name="arrange_windows", description="Organise les fenêtres selon une disposition (côte à côte, grille).", contract=ComputerControlArrangeWindowsContract),
        ]

    # -----------------------------------------------------------------------
    # Méthodes auxiliaires asynchrones
    # -----------------------------------------------------------------------
    async def _run_applescript(self, script: str, timeout: float = 5.0) -> tuple[bool, str]:
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
            logger.error(f"AppleScript timeout après {timeout}s")
            return False, "Timeout"
        except Exception as e:
            logger.error(f"Erreur AppleScript inattendue : {e}")
            return False, str(e)

    async def _activate_app(self, app_name: str):
        script = f'tell application "{app_name}" to activate'
        success, error = await self._run_applescript(script, timeout=3.0)
        if not success:
            raise Exception(f"Échec activation de '{app_name}': {error}")

    def _get_active_app_name(self) -> Optional[str]:
        if not FOUND_APPKIT:
            return None
        try:
            workspace = AppKit.NSWorkspace.sharedWorkspace()
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
        logger.warning(f"'{app_name}' non détectée au premier plan après {timeout}s")
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
        success, error = await self._run_applescript(script, timeout=3.0)
        if not success:
            logger.error(f"Création de note échouée : {error}")
            # Fallback : Cmd+N via pyautogui
            pyautogui.hotkey("command", "n")
            await asyncio.sleep(0.5)
        return True

    async def _focus_note_body(self):
        """Met le focus dans le corps de la note (après l'avoir ouverte)."""
        # Attendre que Notes soit actif
        await self._wait_for_app_active("Notes", timeout=2.0)
        # Appuyer sur Tab pour aller dans le corps
        pyautogui.press('tab')
        await asyncio.sleep(0.2)
        # Optionnel : un clic pour être sûr (à ajuster selon la position)
        # pyautogui.click(x=200, y=200)

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
                success, error = await self._run_applescript(script, timeout=2.0)
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
            success, error = await self._run_applescript(script, timeout=5.0)
            return success

    async def _ensure_app_window(self, app_name: str):
        """Pour certaines applications, s'assurer qu'une fenêtre existe."""
        app_lower = app_name.lower()
        if app_lower not in APPS_NEEDING_WINDOW:
            return
        # Vérifier par AppleScript
        if app_lower == "mail":
            check_script = 'tell application "Mail" to exists window 1'
        elif app_lower == "notes":
            check_script = 'tell application "Notes" to exists window 1'
        elif app_lower == "calendar":
            check_script = 'tell application "Calendar" to exists window 1'
        elif app_lower == "messages":
            check_script = 'tell application "Messages" to exists window 1'
        elif app_lower == "facetime":
            check_script = 'tell application "FaceTime" to exists window 1'
        else:
            return

        success, output = await self._run_applescript(check_script, timeout=3.0)
        if success and output.strip().lower() == "true":
            return
        # Pas de fenêtre, en créer une
        if app_lower == "mail":
            new_script = 'tell application "Mail" to make new window'
        elif app_lower == "notes":
            new_script = 'tell application "Notes" to activate\n' \
                         'tell application "System Events" to keystroke "n" using command down'
        elif app_lower == "calendar":
            new_script = 'tell application "Calendar" to activate'
        elif app_lower == "messages":
            new_script = 'tell application "Messages" to activate'
        elif app_lower == "facetime":
            new_script = 'tell application "FaceTime" to activate'
        else:
            return
        await self._run_applescript(new_script, timeout=3.0)
        await asyncio.sleep(0.5)

    # -----------------------------------------------------------------------
    # Implémentation des outils
    # -----------------------------------------------------------------------
    async def _tool_open_application(self, app_name: str) -> str:
        start = time.time()
        logger.info(f"🔍 Ouverture de '{app_name}'")

        # 1. Vérification rapide avec mdfind
        try:
            proc = await asyncio.create_subprocess_exec(
                "mdfind",
                f"kMDItemKind == 'Application' && kMDItemDisplayName == '{app_name}'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
            if not stdout.strip():
                logger.warning(f"'{app_name}' non trouvé par mdfind, tentative avec open -a")
        except asyncio.TimeoutError:
            logger.warning("mdfind a timeout, on continue avec open -a")

        # 2. Lancer avec open -a
        try:
            proc = await asyncio.create_subprocess_exec(
                "open", "-a", app_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Erreur inconnue"
                duration = time.time() - start
                record_tool_execution(self.name, "open_application", duration, error=True)
                raise ToolExecutionError(
                    f"Impossible d'ouvrir '{app_name}' : {error_msg}",
                    suggestion="Vérifiez le nom de l'application."
                )
        except asyncio.TimeoutError:
            duration = time.time() - start
            record_tool_execution(self.name, "open_application", duration, error=True)
            raise ToolExecutionError(
                f"Timeout lors de l'ouverture de '{app_name}'.",
                suggestion="L'application met trop de temps à démarrer."
            )

        # 3. Attendre que l'application soit active
        await self._wait_for_app_active(app_name, timeout=3.0)
        # S'assurer qu'une fenêtre existe pour certaines apps
        await self._ensure_app_window(app_name)

        duration = time.time() - start
        record_tool_execution(self.name, "open_application", duration, error=False)
        return f"✅ Application '{app_name}' ouverte."

    async def _tool_type_text(self, text: str, interval: float = 0.05, app_name: Optional[str] = None, correct_spelling: bool = False) -> str:
        start = time.time()
        logger.info(f"✏️ Typage de texte: {text[:40]}...")

        # Si une application cible est spécifiée, l'activer
        if app_name:
            try:
                await self._activate_app(app_name)
                await self._wait_for_app_active(app_name, timeout=2.0)
            except Exception as e:
                logger.warning(f"Impossible d'activer {app_name}, on tape quand même: {e}")

        # Cas spécial Notes
        active = self._get_active_app_name()
        target_is_notes = (app_name and "notes" in app_name.lower()) or (active and "notes" in active.lower())

        if target_is_notes:
            logger.info("Notes détectée, création d'une nouvelle note")
            await self._create_new_note_in_notes()
            await self._focus_note_body()  # <-- mise au point dans le corps

        # Choisir la méthode de saisie
        success = False

        # Méthode 1 : AppleScript avec collage (si activé)
        if self.use_applescript_for_typing and self.use_paste_for_typing:
            logger.debug("Tentative AppleScript avec collage")
            success = await self._type_text_with_applescript(text, interval, use_paste=True)

        # Méthode 2 : AppleScript caractère par caractère
        if not success and self.use_applescript_for_typing:
            logger.debug("Tentative AppleScript caractère par caractère")
            success = await self._type_text_with_applescript(text, interval, use_paste=False)

        # Méthode 3 : Collage via pbcopy + Cmd+V (pyautogui)
        if not success:
            logger.debug("Tentative collage via pbcopy")
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

        # Méthode 4 : pyautogui.typewrite (fallback ultime)
        if not success:
            logger.debug("Fallback : pyautogui.typewrite")
            pyautogui.typewrite(text, interval=interval)
            success = True

        duration = time.time() - start
        record_tool_execution(self.name, "type_text", duration, error=not success)
        return f"✅ Texte tapé ({len(text)} caractères)."

    async def _tool_mail_compose(self, to: str, subject: str = "", body: str = "", send: bool = False) -> str:
        start = time.time()
        try:
            to_esc = to.replace('"', '\\"')
            subject_esc = subject.replace('"', '\\"')
            body_esc = body.replace('"', '\\"').replace("\n", "\\n")
            script = f"""
            tell application "Mail"
                activate
                set newMessage to make new outgoing message with properties {{subject:"{subject_esc}", content:"{body_esc}"}}
                tell newMessage
                    make new to recipient at end of to recipients with properties {{address:"{to_esc}"}}
                end tell
                {"send newMessage" if send else ""}
            end tell
            """
            success, error = await self._run_applescript(script, timeout=10.0)
            if success:
                action = "envoyé" if send else "préparé"
                duration = time.time() - start
                record_tool_execution(self.name, "mail_compose", duration, error=False)
                return f"✅ Email {action} pour {to}."
            else:
                duration = time.time() - start
                record_tool_execution(self.name, "mail_compose", duration, error=True)
                raise ToolExecutionError(f"Erreur lors de la création de l'email: {error}")
        except Exception as e:
            logger.error(f"Exception mail_compose: {e}")
            duration = time.time() - start
            record_tool_execution(self.name, "mail_compose", duration, error=True)
            raise ToolExecutionError(f"Erreur: {e}")

    async def _tool_safari_open_url(self, url: str, new_tab: bool = False) -> str:
        start = time.time()
        try:
            # Activer Safari (le lance si nécessaire)
            await self._activate_app("Safari")
            if not await self._wait_for_app_active("Safari", timeout=3.0):
                raise Exception("Safari ne s'est pas activé")
            if new_tab:
                script = f'tell application "Safari" to tell window 1 to make new tab with properties {{URL:"{url}"}}'
            else:
                script = f'tell application "Safari" to set URL of document 1 to "{url}"'
            success, error = await self._run_applescript(script, timeout=5.0)
            if success:
                duration = time.time() - start
                record_tool_execution(self.name, "safari_open_url", duration, error=False)
                return "✅ URL ouverte dans Safari."
            else:
                duration = time.time() - start
                record_tool_execution(self.name, "safari_open_url", duration, error=True)
                raise ToolExecutionError(f"Erreur: {error}")
        except Exception as e:
            logger.error(f"Exception safari_open_url: {e}")
            duration = time.time() - start
            record_tool_execution(self.name, "safari_open_url", duration, error=True)
            raise ToolExecutionError(f"Erreur: {e}")

    async def _get_screen_size(self) -> Tuple[int, int]:
        if FOUND_APPKIT:
            screen = NSScreen.mainScreen()
            frame = screen.frame()
            return int(frame.size.width), int(frame.size.height)
        else:
            return 1440, 900  # fallback

    async def _arrange_side_by_side(self, apps: List[str]) -> str:
        if len(apps) != 2:
            return "❌ Pour la disposition côte à côte, il faut exactement deux applications."
        width, height = await self._get_screen_size()
        half_width = width // 2
        errors = []
        for i, app in enumerate(apps):
            logger.info(f"Arrangement: traitement de {app}")
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
        return f"✅ Fenêtres de {apps[0]} et {apps[1]} disposées côte à côte."

    async def _arrange_grid_2x2(self, apps: List[str]) -> str:
        if len(apps) != 4:
            return "❌ Pour la disposition grille, il faut exactement quatre applications."
        width, height = await self._get_screen_size()
        half_w, half_h = width // 2, height // 2
        positions = [(0, 0), (half_w, 0), (0, half_h), (half_w, half_h)]
        errors = []
        for i, app in enumerate(apps):
            x, y = positions[i]
            logger.info(f"Arrangement grille: traitement de {app}")
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
        start = time.time()
        try:
            if layout == "side_by_side":
                if not apps or len(apps) < 2:
                    return "❌ Paramètre 'apps' manquant ou insuffisant."
                result = await self._arrange_side_by_side(apps)
            elif layout == "grid_2x2":
                if not apps or len(apps) < 4:
                    return "❌ Paramètre 'apps' manquant ou insuffisant."
                result = await self._arrange_grid_2x2(apps)
            else:
                result = f"❌ Disposition '{layout}' inconnue."
            duration = time.time() - start
            record_tool_execution(self.name, "arrange_windows", duration, error=False)
            return result
        except Exception as e:
            logger.error(f"Exception arrange_windows: {e}")
            duration = time.time() - start
            record_tool_execution(self.name, "arrange_windows", duration, error=True)
            raise ToolExecutionError(f"Erreur: {e}")

    # -----------------------------------------------------------------------
    # Interface de l'agent
    # -----------------------------------------------------------------------
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

        # Ouverture d'application
        if any(kw in q for kw in OPEN_KEYWORDS):
            app = self._parse_open_application(query)
            if app:
                return await self._tool_open_application(app_name=app)

        # Saisie de texte
        if any(kw in q for kw in TYPE_KEYWORDS):
            text = self._parse_type_text(query)
            if text:
                app_name = next((a for a in NOTES_APPS if a in q), None)
                return await self._tool_type_text(text=text, app_name=app_name)

        # Clic
        if any(kw in q for kw in CLICK_KEYWORDS):
            coords = self._parse_coords(query)
            if coords:
                return await self._tool_click(**coords)
            return "❓ Précise les coordonnées du clic (ex: 'clique à 500, 300')."

        # Capture d'écran
        if any(kw in q for kw in SCREENSHOT_KEYWORDS):
            return await self._tool_get_screenshot()

        # Déplacement souris
        if any(kw in q for kw in MOVE_KEYWORDS):
            coords = self._parse_coords(query)
            if coords:
                return await self._tool_move_mouse(**coords)
            return "❓ Précise les coordonnées de destination."

        # Arrangement fenêtres
        if any(kw in q for kw in ARRANGE_KEYWORDS):
            layout = None
            if re.search(ARRANGE_PATTERNS["side_by_side"], q, re.IGNORECASE):
                layout = "side_by_side"
            elif re.search(ARRANGE_PATTERNS["grid_2x2"], q, re.IGNORECASE):
                layout = "grid_2x2"
            if layout:
                apps = [app.capitalize() for app in KNOWN_APPS if app in q]
                return await self._tool_arrange_windows(layout=layout, apps=apps if apps else None)
            return "❓ Précise la disposition souhaitée."

        # Email
        if any(kw in q for kw in MAIL_KEYWORDS):
            # Parsing simple : extraire destinataire, sujet, corps
            to_match = re.search(r"à\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", query)
            to = to_match.group(1) if to_match else ""
            subject_match = re.search(r"sujet\s*[:\s]\s*([^,\.]+)", query, re.IGNORECASE)
            subject = subject_match.group(1).strip() if subject_match else ""
            body_match = re.search(r"corps\s*[:\s]\s*(.+)", query, re.IGNORECASE)
            body = body_match.group(1).strip() if body_match else ""
            if to:
                return await self._tool_mail_compose(to=to, subject=subject, body=body, send=False)
            return "Pour envoyer un email, précisez le destinataire (ex: 'compose un email à jean@exemple.fr')."

        # Safari
        if any(kw in q for kw in SAFARI_KEYWORDS):
            url_match = re.search(r"https?://[^\s]+", query)
            if url_match:
                url = url_match.group()
                return await self._tool_safari_open_url(url=url)
            # Sinon, ouvrir Google par défaut
            return await self._tool_safari_open_url(url="https://www.google.com")

        return await super().handle(query)

    # -----------------------------------------------------------------------
    # Méthodes de parsing
    # -----------------------------------------------------------------------
    def _parse_open_application(self, query: str) -> Optional[str]:
        for pat in OPEN_PATTERNS:
            match = re.search(pat, query, re.IGNORECASE)
            if match:
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