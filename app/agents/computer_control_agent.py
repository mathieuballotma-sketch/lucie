"""
Agent de contrôle de l'ordinateur — version étendue.
Ajoute des outils pour Mail, Safari et l'organisation des fenêtres.
Version avec arrangement de fenêtres amélioré (création de fenêtre pour Mail).
Optimisé pour la rapidité : timeouts réduits, polling plus fréquent.
Incorpore une vérification instantanée via mdfind pour éviter les timeouts sur les applications inexistantes.
Correction : lève ToolExecutionError en cas d'application inexistante ou d'échec de lancement.
Ajout de logs détaillés pour diagnostiquer les problèmes.
Fichier complet : app/agents/computer_control_agent.py
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
    logger.warning(
        "AppKit non disponible — détection d'app active désactivée, arrangement de fenêtres limité."
    )

# Pour la recherche d'applications sans AppKit
import subprocess

# Log de diagnostic pour confirmer le chargement
logger.info(">>> CHARGEMENT DE computer_control_agent.py (version avec mdfind et correction exception) <<<")


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
    "notes",
    "calculatrice",
    "safari",
    "mail",
    "calendar",
    "terminal",
    "finder",
    "chrome",
    "firefox",
    "slack",
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

# Patterns pour l'organisation des fenêtres
ARRANGE_PATTERNS = {
    "side_by_side": r"(c[ôo]te[ -]à[ -]c[ôo]te|side[ -]by[ -]side)",
    "grid_2x2": r"(grille|2x2|quatre|four)",
}


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
    layout: str = Field(
        ..., description="Type de disposition: 'side_by_side', 'grid_2x2'"
    )
    apps: Optional[List[str]] = Field(
        None, description="Liste des applications concernées (optionnel)"
    )


# ---------------------------------------------------------------------------
# Agent principal
# ---------------------------------------------------------------------------
class ComputerControlAgent(BaseAgent):
    """
    Agent capable d'effectuer des actions sur l'ordinateur de façon visible.
    Version étendue avec outils pour Mail, Safari et organisation des fenêtres.
    """

    def __init__(self, llm_service, bus, config: dict):
        super().__init__("ComputerControlAgent", llm_service, bus)
        pyautogui.FAILSAFE = True

        self.visible_mode = config.get("visible_actions", True)
        self.move_duration = config.get("move_duration", 0.5)
        self.type_interval = config.get("type_interval", 0.05)
        self.use_spell_check = config.get("use_spell_check", False)
        self.use_applescript_for_typing = config.get(
            "use_applescript_for_typing", False
        )
        self.use_paste_for_typing = config.get("use_paste_for_typing", True)

        logger.info(f"🖱️ ComputerControlAgent initialisé (mode visible={self.visible_mode})")
        logger.info(f"   FOUND_APPKIT = {FOUND_APPKIT}")

    def get_tools(self) -> list:
        return [
            Tool(
                name="open_application",
                description="Ouvre une application macOS.",
                contract=ComputerControlOpenApplicationContract,
            ),
            Tool(
                name="type_text",
                description="Tape un texte. Si l'app cible est Notes, crée une nouvelle note.",
                contract=ComputerControlTypeTextContract,
            ),
            Tool(
                name="press_key",
                description="Presse une touche spéciale (enter, tab, escape…).",
                contract=ComputerControlPressKeyContract,
            ),
            Tool(
                name="click",
                description="Clique à une position (x, y) à l'écran.",
                contract=ComputerControlClickContract,
            ),
            Tool(
                name="move_mouse",
                description="Déplace la souris à une position (x, y).",
                contract=ComputerControlMoveMouseContract,
            ),
            Tool(
                name="get_screenshot",
                description="Capture l'écran et retourne le chemin du fichier.",
                contract=ComputerControlGetScreenshotContract,
            ),
            Tool(
                name="mail_compose",
                description="Ouvre Mail et crée un nouveau message.",
                contract=ComputerControlMailComposeContract,
            ),
            Tool(
                name="safari_open_url",
                description="Ouvre une URL dans Safari.",
                contract=ComputerControlSafariOpenUrlContract,
            ),
            Tool(
                name="arrange_windows",
                description="Organise les fenêtres selon une disposition (côte à côte, grille).",
                contract=ComputerControlArrangeWindowsContract,
            ),
        ]

    # -----------------------------------------------------------------------
    # Méthodes auxiliaires asynchrones
    # -----------------------------------------------------------------------
    async def _run_applescript(
        self, script: str, timeout: float = 5.0
    ) -> tuple[bool, str]:
        """Exécute un AppleScript avec un timeout (5s par défaut)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
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
        """
        Active (passe au premier plan) une application déjà ouverte.
        Utilise un AppleScript simple et rapide.
        Mesure le temps d'exécution pour diagnostic.
        """
        script = f'tell application "{app_name}" to activate'
        start = time.time()
        try:
            success, error = await self._run_applescript(script, timeout=3.0)
            duration = time.time() - start
            if success:
                logger.debug(f"✅ Activation de '{app_name}' réussie en {duration:.3f}s")
            else:
                logger.error(
                    f"❌ Échec activation de '{app_name}' en {duration:.3f}s : {error}"
                )
                raise Exception(f"Échec activation de '{app_name}': {error}")
        except asyncio.TimeoutError:
            duration = time.time() - start
            logger.error(f"⏰ Timeout activation de '{app_name}' après {duration:.3f}s")
            raise

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
        """Attend que l'application devienne active avec un polling rapide."""
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
        return success

    async def _type_text_with_applescript(
        self, text: str, interval: float = 0.05, use_paste: bool = False
    ) -> bool:
        if use_paste:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pbcopy",
                    stdin=asyncio.subprocess.PIPE,
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
            escaped = (
                text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            )
            script = f"""
            set textToType to "{escaped}"
            repeat with i from 1 to count of characters of textToType
                tell application "System Events" to keystroke (character i of textToType)
                delay {interval}
            end repeat
            """
            success, error = await self._run_applescript(script, timeout=5.0)
            if not success:
                logger.error(f"AppleScript typing échoué : {error}")
            return success

    # -----------------------------------------------------------------------
    # Implémentations des outils
    # -----------------------------------------------------------------------
    async def _tool_open_application(self, app_name: str) -> str:
        """
        Ouvre ou active l'application demandée.
        Vérifie d'abord rapidement l'existence avec mdfind pour éviter les timeouts.
        Si l'application n'existe pas, lève ToolExecutionError immédiatement.
        """
        # Print pour forcer l'affichage
        print(f"🔍 _tool_open_application appelé pour '{app_name}'")

        start = time.time()
        logger.info(f"🔍 _tool_open_application appelé pour '{app_name}' (nouvelle version)")

        # Vérification rapide de l'existence avec mdfind
        try:
            logger.info(f"Exécution de mdfind pour '{app_name}'")
            proc = await asyncio.create_subprocess_exec(
                "mdfind",
                f"kMDItemKind == 'Application' && kMDItemDisplayName == '{app_name}'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=2.0)
            if proc.returncode != 0:
                logger.error(f"mdfind a retourné une erreur: {stderr.decode()}")
            stdout_str = stdout.decode().strip()
            logger.info(f"Résultat mdfind: '{stdout_str}'")

            if not stdout_str:
                duration = time.time() - start
                record_tool_execution(self.name, "open_application", duration, error=True)
                logger.error(f"L'application '{app_name}' n'existe pas sur ce système.")
                raise ToolExecutionError(
                    f"L'application '{app_name}' n'existe pas sur ce système.",
                    suggestion="Vérifiez le nom de l'application."
                )
            else:
                logger.info(f"mdfind a trouvé: {stdout_str}")
        except asyncio.TimeoutError:
            logger.warning("mdfind a timeout, on continue sans vérification d'existence")
        except ToolExecutionError:
            # On relève directement, ne pas continuer
            raise
        except Exception as e:
            logger.error(f"Exception lors de l'appel à mdfind: {e}", exc_info=True)
            # On ne lève pas ici, on continue avec la méthode traditionnelle

        # Ensuite, vérifier si elle est déjà en cours d'exécution (si AppKit dispo)
        app_found = False
        if FOUND_APPKIT:
            try:
                workspace = AppKit.NSWorkspace.sharedWorkspace()
                running_apps = workspace.runningApplications()
                for app in running_apps:
                    if app.localizedName() and app.localizedName().lower() == app_name.lower():
                        app_found = True
                        logger.debug(
                            f"Application trouvée en cours : {app.localizedName()} "
                            f"(PID: {app.processIdentifier()})"
                        )
                        break
            except Exception as e:
                logger.error(f"Erreur lors de la vérification des apps en cours: {e}")

        if app_found:
            # Déjà ouverte → simple activation
            logger.debug(f"Activation de '{app_name}' via AppleScript...")
            await self._activate_app(app_name)
            duration = time.time() - start
            record_tool_execution(self.name, "open_application", duration, error=False)
            logger.info(f"✅ _tool_open_application terminé en {duration:.3f}s (activation)")
            return f"✅ Application '{app_name}' déjà ouverte, activation effectuée."

        # Sinon, lancer l'application
        try:
            logger.debug(f"Lancement de '{app_name}' via 'open -a'...")
            proc = await asyncio.create_subprocess_exec(
                "open",
                "-a",
                app_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            # Timeout de 10s pour l'ouverture
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            if proc.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Erreur inconnue"
                logger.error(f"Échec ouverture '{app_name}' : {error_msg}")
                duration = time.time() - start
                record_tool_execution(self.name, "open_application", duration, error=True)
                raise ToolExecutionError(
                    f"Impossible d'ouvrir '{app_name}' : {error_msg}",
                    suggestion="Vérifiez que l'application n'est pas corrompue ou réinstallez-la."
                )
            # Attendre que l'application devienne active
            logger.debug(f"Attente de l'activation de '{app_name}'...")
            await self._wait_for_app_active(app_name, timeout=2.0)
            await self._activate_app(app_name)
            duration = time.time() - start
            record_tool_execution(self.name, "open_application", duration, error=False)
            logger.info(f"✅ _tool_open_application terminé en {duration:.3f}s (lancement)")
            return f"✅ Application '{app_name}' ouverte."
        except asyncio.TimeoutError:
            logger.error(f"Timeout lors de l'ouverture de '{app_name}'")
            duration = time.time() - start
            record_tool_execution(self.name, "open_application", duration, error=True)
            raise ToolExecutionError(
                f"Timeout lors de l'ouverture de '{app_name}'.",
                suggestion="L'application met trop de temps à démarrer, vérifiez qu'elle n'est pas bloquée."
            )
        except Exception as e:
            logger.error(f"Exception open_application (lancement) pour '{app_name}': {e}")
            duration = time.time() - start
            record_tool_execution(self.name, "open_application", duration, error=True)
            raise ToolExecutionError(
                f"Erreur ouverture '{app_name}': {e}",
                suggestion="Vérifiez les permissions ou réinstallez l'application."
            )

    async def _tool_type_text(
        self,
        text: str,
        interval: float = 0.05,
        app_name: Optional[str] = None,
        correct_spelling: bool = False,
    ) -> str:
        start = time.time()
        logger.info(f"🚀 type_text : '{text[:40]}…' | app={app_name}")
        target_app = app_name
        if app_name:
            await self._activate_app(app_name)
            await self._wait_for_app_active(app_name, timeout=2.0)
        else:
            active = self._get_active_app_name()
            if active and any(n in active.lower() for n in NOTES_APPS):
                target_app = active
        if target_app and any(n in target_app.lower() for n in NOTES_APPS):
            logger.info("   → Notes détectée : création d'une nouvelle note")
            if not await self._create_new_note_in_notes():
                logger.warning("   → Fallback : Cmd+N via pyautogui")
                pyautogui.hotkey("command", "n")
            await self._wait_for_app_active("Notes", timeout=2.0)
        if target_app and any(n in target_app.lower() for n in NOTES_APPS):
            logger.info("   → Utilisation d'AppleScript avec collage pour Notes")
            success = await self._type_text_with_applescript(
                text, interval, use_paste=True
            )
            if success:
                duration = time.time() - start
                record_tool_execution(
                    self.name, "type_text", duration, error=False
                )
                return f"✅ Texte tapé ({len(text)} car.) via AppleScript (collage)."
            else:
                logger.warning("   → Échec AppleScript, fallback sur méthode standard")
        if self.use_applescript_for_typing:
            success = await self._type_text_with_applescript(
                text, interval, use_paste=self.use_paste_for_typing
            )
            if success:
                method = (
                    "collage" if self.use_paste_for_typing else "frappe AppleScript"
                )
                duration = time.time() - start
                record_tool_execution(
                    self.name, "type_text", duration, error=False
                )
                return f"✅ Texte tapé ({len(text)} car.) via {method}."
            else:
                logger.warning("   → Échec AppleScript, fallback pyautogui (dégradé)")
                pyautogui.typewrite(text, interval=interval)
                duration = time.time() - start
                record_tool_execution(
                    self.name, "type_text_degraded", duration, error=True
                )
                return f"⚠️ Texte tapé ({len(text)} car.) via fallback pyautogui."
        else:
            if self.use_paste_for_typing:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "pbcopy",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await proc.communicate(input=text.encode("utf-8"))
                    await asyncio.sleep(0.2)
                    pyautogui.hotkey("command", "v")
                    duration = time.time() - start
                    record_tool_execution(
                        self.name, "type_text", duration, error=False
                    )
                    return f"✅ Texte tapé ({len(text)} car.) via collage."
                except Exception as e:
                    logger.error(f"Erreur collage: {e}")
                    pyautogui.typewrite(text, interval=interval)
                    duration = time.time() - start
                    record_tool_execution(
                        self.name, "type_text_degraded", duration, error=True
                    )
                    return f"⚠️ Texte tapé ({len(text)} car.) via fallback pyautogui."
            else:
                pyautogui.typewrite(text, interval=interval)
                duration = time.time() - start
                record_tool_execution(
                    self.name, "type_text", duration, error=False
                )
                return f"✅ Texte tapé ({len(text)} car.) via pyautogui."

    async def _tool_press_key(self, key: str) -> str:
        start = time.time()
        pyautogui.press(key)
        elapsed = time.time() - start
        record_tool_execution(self.name, "press_key", elapsed, error=False)
        return f"✅ Touche '{key}' pressée."

    async def _tool_click(
        self, x: int, y: int, button: str = "left", move_duration: float = 0.5
    ) -> str:
        """
        Clique à la position (x, y) avec un déplacement éventuel.
        Le paramètre move_duration contrôle la durée du déplacement.
        """
        start = time.time()
        if move_duration > 0:
            pyautogui.moveTo(x, y, duration=move_duration)
            await asyncio.sleep(0.1)
        pyautogui.click(button=button)
        elapsed = time.time() - start
        record_tool_execution(self.name, "click", elapsed, error=False)
        return f"✅ Clic {button} à ({x}, {y}) en {elapsed:.2f}s."

    async def _tool_move_mouse(self, x: int, y: int, duration: float = 0.5) -> str:
        start = time.time()
        pyautogui.moveTo(x, y, duration=duration)
        elapsed = time.time() - start
        record_tool_execution(self.name, "move_mouse", elapsed, error=False)
        return f"✅ Souris déplacée à ({x}, {y}) en {elapsed:.2f}s."

    async def _tool_get_screenshot(self) -> str:
        start = time.time()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        filepath = os.path.join(SCREENSHOT_DIR, filename)
        pyautogui.screenshot(filepath)
        elapsed = time.time() - start
        record_tool_execution(
            self.name, "get_screenshot", elapsed, error=False
        )
        return f"✅ Capture d'écran : {filepath}"

    # -----------------------------------------------------------------------
    # Nouveaux outils
    # -----------------------------------------------------------------------
    async def _tool_mail_compose(
        self, to: str, subject: str = "", body: str = "", send: bool = False
    ) -> str:
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
                elapsed = time.time() - start
                record_tool_execution(
                    self.name, "mail_compose", elapsed, error=False
                )
                return f"✅ Email {action} pour {to}."
            else:
                elapsed = time.time() - start
                record_tool_execution(
                    self.name, "mail_compose", elapsed, error=True
                )
                return f"❌ Erreur lors de la création de l'email: {error}"
        except Exception as e:
            logger.error(f"Exception mail_compose: {e}")
            elapsed = time.time() - start
            record_tool_execution(
                self.name, "mail_compose", elapsed, error=True
            )
            return f"❌ Erreur: {e}"

    async def _tool_safari_open_url(self, url: str, new_tab: bool = False) -> str:
        start = time.time()
        try:
            # Activer Safari (le lance si nécessaire)
            await self._activate_app("Safari")
            # Attendre un peu que Safari soit prêt
            await asyncio.sleep(0.5)
            # Attendre qu'il soit actif
            if not await self._wait_for_app_active("Safari", timeout=3.0):
                raise Exception("Safari ne s'est pas activé dans les temps")
            if new_tab:
                script = f"""
                tell application "Safari"
                    tell window 1 to make new tab with properties {{URL:"{url}"}}
                end tell
                """
            else:
                script = f"""
                tell application "Safari" to set URL of document 1 to "{url}"
                """
            success, error = await self._run_applescript(script, timeout=5.0)
            if success:
                elapsed = time.time() - start
                record_tool_execution(
                    self.name, "safari_open_url", elapsed, error=False
                )
                return "✅ URL ouverte dans Safari."
            else:
                elapsed = time.time() - start
                record_tool_execution(
                    self.name, "safari_open_url", elapsed, error=True
                )
                return f"❌ Erreur: {error}"
        except Exception as e:
            logger.error(f"Exception safari_open_url: {e}")
            elapsed = time.time() - start
            record_tool_execution(
                self.name, "safari_open_url", elapsed, error=True
            )
            return f"❌ Erreur: {e}"

    async def _get_screen_size(self) -> Tuple[int, int]:
        """Retourne la largeur et hauteur de l'écran principal."""
        if FOUND_APPKIT:
            screen = NSScreen.mainScreen()
            frame = screen.frame()
            return int(frame.size.width), int(frame.size.height)
        else:
            # Fallback sur une taille courante (1440x900)
            return 1440, 900

    async def _arrange_side_by_side(self, apps: List[str]) -> str:
        """Place deux applications côte à côte, avec création de fenêtre pour Mail si nécessaire."""
        if len(apps) != 2:
            return "❌ Pour la disposition côte à côte, il faut exactement deux applications."

        width, height = await self._get_screen_size()
        half_width = width // 2
        errors = []

        for i, app in enumerate(apps):
            logger.info(f"Arrangement: traitement de {app}")

            # Activer l'application et attendre qu'elle soit active
            await self._activate_app(app)
            if not await self._wait_for_app_active(app, timeout=3.0):
                errors.append(f"{app} ne s'est pas activée")
                continue

            # Attendre un peu que l'application soit prête
            await asyncio.sleep(0.5)

            # Pour Mail, s'assurer qu'une fenêtre existe
            if app.lower() == "mail":
                # Vérifier si une fenêtre existe déjà
                check_script = """
                tell application "Mail"
                    if exists window 1 then
                        return true
                    else
                        return false
                    end if
                end tell
                """
                success, output = await self._run_applescript(check_script, timeout=3.0)
                if not success or "false" in output.lower():
                    logger.info(
                        "Aucune fenêtre Mail trouvée, création d'une nouvelle fenêtre"
                    )
                    new_window_script = """
                    tell application "Mail"
                        activate
                        make new window
                    end tell
                    """
                    await self._run_applescript(new_window_script, timeout=3.0)
                    await asyncio.sleep(1.0)

            # Positionner la fenêtre
            x = 0 if i == 0 else half_width
            script = f"""
            tell application "System Events"
                tell process "{app}"
                    set position of window 1 to {{{x}, 0}}
                    set size of window 1 to {{{half_width}, {height}}}
                end tell
            end tell
            """
            logger.debug(f"Script pour {app} : {script}")
            success, err = await self._run_applescript(script, timeout=5.0)
            if not success:
                logger.error(f"Erreur arrangement pour {app}: {err}")
                errors.append(f"{app}: {err}")
            else:
                logger.info(f"Fenêtre de {app} positionnée avec succès")

        if errors:
            return f"⚠️ Disposition partielle : {', '.join(errors)}"
        return f"✅ Fenêtres de {apps[0]} et {apps[1]} disposées côte à côte."

    async def _arrange_grid_2x2(self, apps: List[str]) -> str:
        """Place quatre applications en grille 2x2."""
        if len(apps) != 4:
            return (
                "❌ Pour la disposition grille, il faut exactement quatre applications."
            )
        width, height = await self._get_screen_size()
        half_w = width // 2
        half_h = height // 2
        positions = [
            (0, 0),  # haut-gauche
            (half_w, 0),  # haut-droit
            (0, half_h),  # bas-gauche
            (half_w, half_h),  # bas-droit
        ]
        errors = []

        for i, app in enumerate(apps):
            x, y = positions[i]
            logger.info(f"Arrangement grille: traitement de {app}")

            # Activer l'application et attendre qu'elle soit active
            await self._activate_app(app)
            if not await self._wait_for_app_active(app, timeout=3.0):
                errors.append(f"{app} ne s'est pas activée")
                continue

            await asyncio.sleep(0.5)

            # Vérifier/créer une fenêtre pour certaines applications (Mail, etc.)
            if app.lower() == "mail":
                check_script = """
                tell application "Mail"
                    if exists window 1 then
                        return true
                    else
                        return false
                    end if
                end tell
                """
                success, output = await self._run_applescript(check_script, timeout=3.0)
                if not success or "false" in output.lower():
                    logger.info("Aucune fenêtre Mail trouvée, création d'une nouvelle fenêtre")
                    new_window_script = """
                    tell application "Mail"
                        activate
                        make new window
                    end tell
                    """
                    await self._run_applescript(new_window_script, timeout=3.0)
                    await asyncio.sleep(1.0)
            # On pourrait ajouter d'autres cas (ex: Notes, Calendar) si besoin

            script = f"""
            tell application "System Events"
                tell process "{app}"
                    set position of window 1 to {{{x}, {y}}}
                    set size of window 1 to {{{half_w}, {half_h}}}
                end tell
            end tell
            """
            logger.debug(f"Script pour {app} : {script}")
            success, err = await self._run_applescript(script, timeout=5.0)
            if not success:
                logger.error(f"Erreur arrangement pour {app}: {err}")
                errors.append(f"{app}: {err}")
            else:
                logger.info(f"Fenêtre de {app} positionnée avec succès")

        if errors:
            return f"⚠️ Disposition partielle : {', '.join(errors)}"
        return f"✅ Fenêtres disposées en grille 2x2."

    async def _tool_arrange_windows(
        self, layout: str, apps: Optional[List[str]] = None
    ) -> str:
        start = time.time()
        try:
            if layout == "side_by_side":
                if not apps or len(apps) < 2:
                    return (
                        "❌ Paramètre 'apps' manquant ou insuffisant pour la "
                        "disposition côte à côte."
                    )
                result = await self._arrange_side_by_side(apps)
            elif layout == "grid_2x2":
                if not apps or len(apps) < 4:
                    return (
                        "❌ Paramètre 'apps' manquant ou insuffisant pour la "
                        "grille 2x2."
                    )
                result = await self._arrange_grid_2x2(apps)
            else:
                result = f"❌ Disposition '{layout}' inconnue."
            elapsed = time.time() - start
            record_tool_execution(
                self.name, "arrange_windows", elapsed, error=False
            )
            return result
        except Exception as e:
            logger.error(f"Exception arrange_windows: {e}")
            elapsed = time.time() - start
            record_tool_execution(
                self.name, "arrange_windows", elapsed, error=True
            )
            return f"❌ Erreur: {e}"

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
            return (
                "❓ Précise les coordonnées de destination (ex: 'déplace à 800, 400')."
            )

        if any(kw in q for kw in ARRANGE_KEYWORDS):
            layout = None
            if re.search(ARRANGE_PATTERNS["side_by_side"], q, re.IGNORECASE):
                layout = "side_by_side"
            elif re.search(ARRANGE_PATTERNS["grid_2x2"], q, re.IGNORECASE):
                layout = "grid_2x2"
            if layout:
                apps = []
                for app in KNOWN_APPS:
                    if app in q:
                        apps.append(app.capitalize())
                return await self._tool_arrange_windows(
                    layout=layout, apps=apps if apps else None
                )
            return "❓ Précise la disposition souhaitée (ex: 'côte à côte', 'grille')."

        if any(kw in q for kw in MAIL_KEYWORDS):
            # Tentative de parsing simple pour l'outil mail_compose
            # Exemple: "envoie un email à john" → on peut essayer d'extraire le destinataire
            # Pour l'instant, on renvoie un message guidant l'utilisateur
            return "Pour envoyer un email, utilisez l'outil dédié avec la commande 'compose un email à [adresse]' ou activez-le via le menu."

        if any(kw in q for kw in SAFARI_KEYWORDS):
            url_match = re.search(r"https?://[^\s]+", query)
            if url_match:
                url = url_match.group()
                return await self._tool_safari_open_url(url=url)
            # Si pas d'URL, on peut proposer une recherche par défaut
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