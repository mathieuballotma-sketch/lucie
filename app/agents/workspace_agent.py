"""
WorkspaceAgent — Intelligence spatiale pour l'organisation des fenêtres.

Lois incarnées :
- Intelligence spatiale : comprend l'espace de travail comme un humain
- Fluidité visuelle : mouvements doux et visibles, jamais brutaux
- Adaptation : détecte les écrans et s'adapte à la configuration
- Moindre action : choisit le layout optimal automatiquement
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from pydantic.v1 import BaseModel, Field as PydField

from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger

try:
    from AppKit import NSScreen
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False


# ─────────────────────────────────────────────────────────────────────────────
# Modèles de données
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ScreenInfo:
    """Informations sur un écran."""
    index: int
    width: int
    height: int
    x: int
    y: int
    visible_width: int
    visible_height: int
    visible_x: int
    visible_y: int
    is_primary: bool


@dataclass
class WindowInfo:
    """Informations sur une fenêtre."""
    app_name: str
    title: str
    x: int
    y: int
    width: int
    height: int
    minimized: bool = False


@dataclass
class LayoutTarget:
    """Position cible d'une fenêtre dans un layout."""
    app_name: str
    x: int
    y: int
    width: int
    height: int


# ─────────────────────────────────────────────────────────────────────────────
# Contrats Pydantic
# ─────────────────────────────────────────────────────────────────────────────
class WorkspaceArrangeContract(BaseModel):
    layout: str = PydField(..., description="Layout: split, main_side, triple, focus, dual_screen")
    apps: List[str] = PydField(..., description="Liste des applications à organiser")

class WorkspaceSmartContract(BaseModel):
    task_description: str = PydField(..., description="Description de la tâche de travail")

class WorkspaceDetectContract(BaseModel):
    pass

class WorkspaceFocusContract(BaseModel):
    app_name: Optional[str] = PydField(None, description="App à mettre en focus (ou app active)")


# ─────────────────────────────────────────────────────────────────────────────
# Constantes — Animation
# ─────────────────────────────────────────────────────────────────────────────
ANIMATION_STEPS = 10
ANIMATION_STEP_DELAY = 0.025  # 25ms entre chaque étape → ~250ms total
MENU_BAR_HEIGHT = 25


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────
class WorkspaceAgent(BaseAgent):
    """Agent d'intelligence spatiale — organise les fenêtres comme un humain."""

    def __init__(self, llm_service: Any, bus: Any, config: dict):
        super().__init__("WorkspaceAgent", llm_service, bus)
        self._screens: Optional[List[ScreenInfo]] = None
        logger.info("🪟 WorkspaceAgent initialisé")

    def get_tools(self) -> list:
        return [
            Tool(name="arrange", description="Organise les fenêtres selon un layout.",
                 contract=WorkspaceArrangeContract),
            Tool(name="smart_arrange", description="Organise selon la tâche décrite.",
                 contract=WorkspaceSmartContract),
            Tool(name="detect_screens", description="Détecte les écrans connectés.",
                 contract=WorkspaceDetectContract),
            Tool(name="focus", description="Met une app en focus, minimise le reste.",
                 contract=WorkspaceFocusContract),
        ]

    # ── Détection environnement ───────────────────────────────────────────

    def detect_screens(self) -> List[ScreenInfo]:
        """Détecte tous les écrans connectés et leur configuration."""
        if not HAS_APPKIT:
            logger.warning("AppKit indisponible, écran par défaut 1440x900")
            return [ScreenInfo(0, 1440, 900, 0, 0, 1440, 875, 0, 0, True)]

        screens: List[ScreenInfo] = []
        ns_screens = NSScreen.screens()
        main = NSScreen.mainScreen()

        for i, s in enumerate(ns_screens):
            f = s.frame()
            v = s.visibleFrame()
            screens.append(ScreenInfo(
                index=i,
                width=int(f.size.width),
                height=int(f.size.height),
                x=int(f.origin.x),
                y=int(f.origin.y),
                visible_width=int(v.size.width),
                visible_height=int(v.size.height),
                visible_x=int(v.origin.x),
                visible_y=int(v.origin.y),
                is_primary=(s == main),
            ))

        self._screens = screens
        logger.info(f"🖥️ {len(screens)} écran(s) détecté(s)")
        for s in screens:
            logger.info(f"  Écran {s.index}: {s.width}x{s.height} @ ({s.x},{s.y}) {'[PRINCIPAL]' if s.is_primary else ''}")
        return screens

    async def detect_open_windows(self) -> List[WindowInfo]:
        """Liste toutes les fenêtres ouvertes avec leur position/taille."""
        script = """
tell application "System Events"
    set windowInfo to ""
    repeat with proc in (every process whose visible is true)
        set procName to name of proc
        try
            repeat with win in windows of proc
                set winName to name of win
                set winPos to position of win
                set winSz to size of win
                set isMini to false
                try
                    set isMini to value of attribute "AXMinimized" of win
                end try
                set windowInfo to windowInfo & procName & "|" & winName & "|" & (item 1 of winPos) & "," & (item 2 of winPos) & "|" & (item 1 of winSz) & "," & (item 2 of winSz) & "|" & isMini & linefeed
            end repeat
        end try
    end repeat
    return windowInfo
end tell
"""
        success, output = await self._run_applescript(script, timeout=5.0)
        windows: List[WindowInfo] = []
        if not success:
            return windows

        for line in output.strip().split("\n"):
            parts = line.split("|")
            if len(parts) < 5:
                continue
            try:
                pos = parts[2].split(",")
                size = parts[3].split(",")
                windows.append(WindowInfo(
                    app_name=parts[0],
                    title=parts[1],
                    x=int(pos[0]),
                    y=int(pos[1]),
                    width=int(size[0]),
                    height=int(size[1]),
                    minimized=parts[4].strip().lower() == "true",
                ))
            except (ValueError, IndexError):
                continue

        return windows

    # ── AppleScript helper ────────────────────────────────────────────────

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

    # ── Animation fluide ──────────────────────────────────────────────────

    async def animate_window(self, app_name: str, target_x: int, target_y: int,
                              target_w: int, target_h: int) -> bool:
        """Anime le déplacement d'une fenêtre avec décélération (ease-out)."""
        # Obtenir la position actuelle
        get_script = f"""
tell application "System Events"
    tell process "{app_name}"
        set winPos to position of window 1
        set winSz to size of window 1
        return (item 1 of winPos) & "," & (item 2 of winPos) & "," & (item 1 of winSz) & "," & (item 2 of winSz)
    end tell
end tell
"""
        success, output = await self._run_applescript(get_script, timeout=2.0)
        if not success:
            # Fallback : placement direct
            set_script = f"""
tell application "System Events"
    tell process "{app_name}"
        set position of window 1 to {{{target_x}, {target_y}}}
        set size of window 1 to {{{target_w}, {target_h}}}
    end tell
end tell
"""
            await self._run_applescript(set_script, timeout=2.0)
            return True

        try:
            parts = output.split(",")
            cur_x, cur_y = int(parts[0]), int(parts[1])
            cur_w, cur_h = int(parts[2]), int(parts[3])
        except (ValueError, IndexError):
            cur_x, cur_y, cur_w, cur_h = 0, MENU_BAR_HEIGHT, target_w, target_h

        # Si déjà en position, skip
        if (abs(cur_x - target_x) < 5 and abs(cur_y - target_y) < 5
                and abs(cur_w - target_w) < 5 and abs(cur_h - target_h) < 5):
            return True

        # Animation par étapes avec ease-out (décélération)
        for i in range(1, ANIMATION_STEPS + 1):
            t = i / ANIMATION_STEPS
            # Ease-out quadratique : rapide au début, doux à la fin
            t = 1 - (1 - t) ** 2

            x = int(cur_x + (target_x - cur_x) * t)
            y = int(cur_y + (target_y - cur_y) * t)
            w = int(cur_w + (target_w - cur_w) * t)
            h = int(cur_h + (target_h - cur_h) * t)

            step_script = f"""
tell application "System Events"
    tell process "{app_name}"
        set position of window 1 to {{{x}, {y}}}
        set size of window 1 to {{{w}, {h}}}
    end tell
end tell
"""
            await self._run_applescript(step_script, timeout=1.0)
            await asyncio.sleep(ANIMATION_STEP_DELAY)

        return True

    # ── Layouts ───────────────────────────────────────────────────────────

    def _get_screen(self, index: int = 0) -> ScreenInfo:
        """Retourne l'écran demandé, ou le principal."""
        if not self._screens:
            self.detect_screens()
        screens = self._screens or []
        if index < len(screens):
            return screens[index]
        return screens[0] if screens else ScreenInfo(0, 1440, 900, 0, 0, 1440, 875, 0, 0, True)

    def _primary_screen(self) -> ScreenInfo:
        screens = self._screens or self.detect_screens()
        for s in screens:
            if s.is_primary:
                return s
        return screens[0]

    def _secondary_screen(self) -> Optional[ScreenInfo]:
        screens = self._screens or self.detect_screens()
        for s in screens:
            if not s.is_primary:
                return s
        return None

    def compute_layout_split(self, apps: List[str], vertical: bool = False) -> List[LayoutTarget]:
        """2 apps côte à côte (horizontal) ou empilées (vertical)."""
        scr = self._primary_screen()
        top = MENU_BAR_HEIGHT
        usable_h = scr.height - top

        if len(apps) < 2:
            return [LayoutTarget(apps[0], 0, top, scr.width, usable_h)]

        if vertical:
            half_h = usable_h // 2
            return [
                LayoutTarget(apps[0], 0, top, scr.width, half_h),
                LayoutTarget(apps[1], 0, top + half_h, scr.width, half_h),
            ]
        else:
            half_w = scr.width // 2
            return [
                LayoutTarget(apps[0], 0, top, half_w, usable_h),
                LayoutTarget(apps[1], half_w, top, half_w, usable_h),
            ]

    def compute_layout_main_side(self, apps: List[str]) -> List[LayoutTarget]:
        """App principale 70% gauche, secondaire 30% droite."""
        scr = self._primary_screen()
        top = MENU_BAR_HEIGHT
        usable_h = scr.height - top
        main_w = int(scr.width * 0.7)
        side_w = scr.width - main_w

        targets = [LayoutTarget(apps[0], 0, top, main_w, usable_h)]
        if len(apps) > 1:
            targets.append(LayoutTarget(apps[1], main_w, top, side_w, usable_h))
        return targets

    def compute_layout_triple(self, apps: List[str]) -> List[LayoutTarget]:
        """3 apps côte à côte, chacune 33%."""
        scr = self._primary_screen()
        top = MENU_BAR_HEIGHT
        usable_h = scr.height - top
        third = scr.width // 3

        targets = []
        for i, app in enumerate(apps[:3]):
            x = third * i
            w = third if i < 2 else scr.width - third * 2
            targets.append(LayoutTarget(app, x, top, w, usable_h))
        return targets

    def compute_layout_dual_screen(self, apps: List[str]) -> List[LayoutTarget]:
        """App principale sur écran 1, secondaire sur écran 2."""
        primary = self._primary_screen()
        secondary = self._secondary_screen()
        top = MENU_BAR_HEIGHT

        targets = [LayoutTarget(
            apps[0], primary.x, top,
            primary.width, primary.height - top,
        )]

        if len(apps) > 1 and secondary:
            targets.append(LayoutTarget(
                apps[1], secondary.x, top,
                secondary.width, secondary.height - top,
            ))
        elif len(apps) > 1:
            # Pas de 2e écran → split sur l'écran principal
            half = primary.width // 2
            targets[0] = LayoutTarget(apps[0], 0, top, half, primary.height - top)
            targets.append(LayoutTarget(apps[1], half, top, half, primary.height - top))

        return targets

    def compute_layout_focus(self, app_name: str) -> List[LayoutTarget]:
        """App en plein écran, tout le reste sera minimisé."""
        scr = self._primary_screen()
        return [LayoutTarget(app_name, 0, MENU_BAR_HEIGHT, scr.width, scr.height - MENU_BAR_HEIGHT)]

    def compute_layout(self, layout: str, apps: List[str]) -> List[LayoutTarget]:
        """Calcule les positions cibles selon le layout choisi."""
        if layout == "focus" and apps:
            return self.compute_layout_focus(apps[0])
        if layout == "main_side":
            return self.compute_layout_main_side(apps)
        if layout == "triple" and len(apps) >= 3:
            return self.compute_layout_triple(apps)
        if layout == "dual_screen":
            return self.compute_layout_dual_screen(apps)
        if layout == "split_vertical":
            return self.compute_layout_split(apps, vertical=True)
        # Default : split horizontal
        return self.compute_layout_split(apps, vertical=False)

    # ── Exécution ─────────────────────────────────────────────────────────

    async def apply_layout(self, targets: List[LayoutTarget],
                            minimize_others: bool = False) -> str:
        """Applique un layout en animant chaque fenêtre."""
        # D'abord, activer chaque app (les ouvrir si nécessaire)
        for target in targets:
            script = f'tell application "{target.app_name}" to activate'
            await self._run_applescript(script, timeout=3.0)
            await asyncio.sleep(0.15)

        # Minimiser les autres si mode focus
        if minimize_others:
            open_windows = await self.detect_open_windows()
            target_apps = {t.app_name.lower() for t in targets}
            for win in open_windows:
                if win.app_name.lower() not in target_apps and not win.minimized:
                    script = f"""
tell application "System Events"
    tell process "{win.app_name}"
        try
            keystroke "m" using command down
        end try
    end tell
end tell
"""
                    await self._run_applescript(script, timeout=2.0)
                    await asyncio.sleep(0.1)

        # Animer chaque fenêtre vers sa position cible
        results = []
        for target in targets:
            # Activer avant de déplacer
            script = f'tell application "{target.app_name}" to activate'
            await self._run_applescript(script, timeout=2.0)
            await asyncio.sleep(0.1)

            ok = await self.animate_window(
                target.app_name, target.x, target.y, target.width, target.height
            )
            pos_str = f"{target.x},{target.y} {target.width}x{target.height}"
            if ok:
                results.append(f"✅ {target.app_name} → {pos_str}")
            else:
                results.append(f"⚠️ {target.app_name} → échec")

        # Remettre le focus sur la première app (principale)
        if targets:
            script = f'tell application "{targets[0].app_name}" to activate'
            await self._run_applescript(script, timeout=2.0)

        return "\n".join(results)

    # ── Intelligence : choix automatique du layout ────────────────────────

    def think_layout(self, task: str, apps: List[str]) -> Tuple[str, List[str]]:
        """Réfléchit au meilleur layout selon la tâche et les apps."""
        t = task.lower()
        n_screens = len(self._screens or self.detect_screens())
        n_apps = len(apps)

        # Focus
        focus_kw = ["concentre", "focus", "une seule", "plein écran", "fullscreen"]
        if any(kw in t for kw in focus_kw) and n_apps >= 1:
            return "focus", apps[:1]

        # Compare → split 50/50
        compare_kw = ["compare", "versus", "différence", "côte à côte", "side by side"]
        if any(kw in t for kw in compare_kw) and n_apps >= 2:
            return "split", apps[:2]

        # Dual screen si disponible et 2+ apps
        if n_screens >= 2 and n_apps >= 2:
            return "dual_screen", apps[:2]

        # 3 apps → triple
        if n_apps >= 3:
            return "triple", apps[:3]

        # 2 apps → main_side (tâche principale + référence)
        if n_apps == 2:
            # Déterminer laquelle est la principale
            write_kw = ["écri", "rédige", "code", "travaille", "modifie"]
            if any(kw in t for kw in write_kw):
                return "main_side", apps
            return "split", apps

        # 1 app
        return "focus", apps[:1]

    # ── Outils exposés ────────────────────────────────────────────────────

    async def _tool_arrange(self, layout: str, apps: List[str]) -> str:
        """Organise les fenêtres selon un layout donné."""
        start = time.time()
        self.detect_screens()
        targets = self.compute_layout(layout, apps)
        logger.info(f"🪟 Layout '{layout}' pour {apps} → {len(targets)} cibles")
        minimize = layout == "focus"
        result = await self.apply_layout(targets, minimize_others=minimize)
        elapsed = time.time() - start
        return f"🪟 Espace organisé ({layout}) en {elapsed:.1f}s\n{result}"

    async def _tool_smart_arrange(self, task_description: str) -> str:
        """Organise l'espace selon la description de la tâche."""
        start = time.time()
        self.detect_screens()

        # Extraire les apps mentionnées dans la tâche
        t = task_description.lower()
        app_map = {
            "safari": "Safari", "chrome": "Google Chrome", "firefox": "Firefox",
            "notes": "Notes", "mail": "Mail", "terminal": "Terminal",
            "code": "Code", "vscode": "Code", "word": "Microsoft Word",
            "pages": "Pages", "numbers": "Numbers", "keynote": "Keynote",
            "finder": "Finder", "messages": "Messages", "calendrier": "Calendar",
            "calendar": "Calendar", "musique": "Music", "spotify": "Spotify",
        }
        apps = []
        for keyword, app_name in app_map.items():
            if keyword in t and app_name not in apps:
                apps.append(app_name)

        if not apps:
            # Utiliser les fenêtres déjà ouvertes
            windows = await self.detect_open_windows()
            seen = set()
            for w in windows:
                if w.app_name not in seen and not w.minimized:
                    apps.append(w.app_name)
                    seen.add(w.app_name)

        if not apps:
            return "Aucune application à organiser."

        layout, selected_apps = self.think_layout(task_description, apps)
        logger.info(f"🧠 Réflexion : layout={layout}, apps={selected_apps}")

        targets = self.compute_layout(layout, selected_apps)
        minimize = layout == "focus"
        result = await self.apply_layout(targets, minimize_others=minimize)
        elapsed = time.time() - start
        return f"🪟 Espace organisé ({layout}) en {elapsed:.1f}s\n{result}"

    async def _tool_detect_screens(self) -> str:
        """Détecte et décrit la configuration des écrans."""
        screens = self.detect_screens()
        lines = [f"🖥️ {len(screens)} écran(s) détecté(s) :"]
        for s in screens:
            role = "PRINCIPAL" if s.is_primary else "SECONDAIRE"
            lines.append(
                f"  Écran {s.index} [{role}] : {s.width}x{s.height} "
                f"@ ({s.x},{s.y}), zone utile {s.visible_width}x{s.visible_height}"
            )
        return "\n".join(lines)

    async def _tool_focus(self, app_name: Optional[str] = None) -> str:
        """Met une app en plein écran et minimise le reste."""
        if not app_name:
            # Utiliser l'app active
            script = """
tell application "System Events"
    return name of first application process whose frontmost is true
end tell
"""
            success, output = await self._run_applescript(script, timeout=2.0)
            app_name = output if success else None
        if not app_name:
            return "Impossible de déterminer l'application active."

        self.detect_screens()
        targets = self.compute_layout_focus(app_name)
        result = await self.apply_layout(targets, minimize_others=True)
        return f"🎯 Focus sur {app_name}\n{result}"

    # ── Interface ─────────────────────────────────────────────────────────

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        kw = ["organise", "arrange", "côte à côte", "côte-à-côte", "split",
              "partage l'écran", "mets à gauche", "mets à droite",
              "plein écran", "concentre", "prépare mon espace",
              "range les fenêtres", "compare", "deux fenêtres",
              "workspace", "layout", "disposition"]
        return any(k in q for k in kw)

    async def handle(self, query: str) -> str:
        q = query.lower()

        # Focus
        if any(kw in q for kw in ["concentre", "focus", "plein écran"]):
            return await self._tool_focus()

        # Détection
        if any(kw in q for kw in ["détecte", "écran", "screen", "moniteur"]):
            return await self._tool_detect_screens()

        # Organisation intelligente par défaut
        return await self._tool_smart_arrange(query)
