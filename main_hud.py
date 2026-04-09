#!/usr/bin/env python3
"""
Point d'entrée principal avec interface HUD native.
Version avec boucle asyncio dans un thread dédié et HUD dans le thread principal.

Si premier lancement : affiche l'expérience d'onboarding (cocoon → HUD → prénom → guide).
Sinon : lance le HUD directement.
"""

import asyncio
import threading
import sys
from pathlib import Path

# Remplacer le policy asyncio par défaut par uvloop (plus rapide) si disponible
try:
    import uvloop
    uvloop.install()
except ImportError:
    pass

# Ajouter le chemin du projet pour les imports
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import Config
from app.core.engine import LucidEngine
from app.services.onboarding import is_onboarded
from app.ui.hud_native import run_hud

# Événement pour signaler que l'engine est prêt
engine_ready = threading.Event()
engine_instance = None
cocoon_window = None  # référence globale pour le cocoon


def asyncio_thread(progress_callback=None, on_ready=None):
    """Fonction exécutée dans le thread asyncio."""
    global engine_instance
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)

        if progress_callback:
            progress_callback(0.1, 0)

        config = Config.load()
        print("✅ Configuration chargée dans le thread asyncio")
        if progress_callback:
            progress_callback(0.25, 1)

        engine = LucidEngine(config)
        if progress_callback:
            progress_callback(0.6, 2)

        engine.set_loop(loop)
        if progress_callback:
            progress_callback(0.85, 3)

        engine_instance = engine
        if progress_callback:
            progress_callback(1.0, 4)

        engine_ready.set()

        # Signaler que l'engine est prêt (avant run_forever qui bloque)
        if on_ready:
            on_ready()

        loop.run_forever()
    except Exception as e:
        print(f"❌ Erreur dans le thread asyncio: {e}")
        import traceback
        traceback.print_exc()
        engine_ready.set()  # débloquer le main thread même en erreur
    finally:
        loop.close()


def main():
    """Point d'entrée principal."""

    if is_onboarded():
        # ── Utilisateur connu : lancement direct ──
        print("👤 Utilisateur déjà onboardé, lancement direct")
        t = threading.Thread(target=asyncio_thread, daemon=True)
        t.start()

        if not engine_ready.wait(timeout=60):
            print("❌ Timeout en attendant l'engine")
            sys.exit(1)

        print("🚀 Lancement de l'interface HUD dans le thread principal")
        run_hud(engine_instance)

    else:
        # ── Premier lancement : expérience d'onboarding ──
        print("🌱 Premier lancement détecté — onboarding")
        _run_onboarding_experience()


def _run_onboarding_experience():
    """Lance l'expérience premier lancement avec cocoon → HUD."""
    global cocoon_window

    import AppKit  # type: ignore[import]
    from PyObjCTools import AppHelper  # type: ignore[import]

    from app.ui.hud_native import HUDWindow
    from app.ui.onboarding import CocoonWindow, OnboardingFlow, animate_cocoon_to_hud

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    # Phase 1 — Créer et afficher le cocoon
    def on_cocoon_ready(cocoon):
        """Appelé quand la barre de progression atteint 100% et l'engine est prêt."""
        # Phase 2 — Créer le HUD (invisible) et animer la transition
        hud = HUDWindow.alloc().init()
        hud.engine = engine_instance

        def on_transition_complete():
            """Phase 3 — Démarrer l'onboarding interactif."""
            hud.makeFirstResponder_(hud._input)
            flow = OnboardingFlow(hud, engine_instance)
            flow.start()
            print("🎯 Onboarding interactif démarré")

        animate_cocoon_to_hud(cocoon, hud, on_transition_complete)

    cocoon_window = CocoonWindow.alloc().initWithCallback_(on_cocoon_ready)
    cocoon_window.show()

    # Démarrer l'engine dans un thread avec progression
    def progress_callback(value, step):
        if cocoon_window:
            cocoon_window.set_progress(value, step)

    def engine_thread():
        # signal_ready doit être appelé AVANT loop.run_forever() (qui bloque)
        # On passe un callback qui sera appelé juste après engine_ready.set()
        def on_engine_ready():
            if cocoon_window:
                cocoon_window.signal_ready()

        asyncio_thread(progress_callback=progress_callback, on_ready=on_engine_ready)

    t = threading.Thread(target=engine_thread, daemon=True)
    t.start()

    # Le runloop macOS bloque ici
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
