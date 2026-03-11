#!/usr/bin/env python3
"""
Point d'entrée principal avec interface HUD native.
Version avec boucle asyncio dans un thread dédié et HUD dans le thread principal.
"""

import asyncio
import threading
import sys
import time
from pathlib import Path

# Ajouter le chemin du projet pour les imports
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import Config
from app.core.engine import LucidEngine
from app.ui.hud_native import run_hud

# Événement pour signaler que l'engine est prêt
engine_ready = threading.Event()
engine_instance = None

def asyncio_thread():
    """Fonction exécutée dans le thread asyncio."""
    global engine_instance
    try:
        # Créer une nouvelle boucle pour ce thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Charger la configuration
        config = Config.load()
        print("✅ Configuration chargée dans le thread asyncio")

        # Créer l'engine
        engine = LucidEngine(config)

        # Définir la boucle pour l'engine
        engine.set_loop(loop)

        # Rendre l'engine disponible pour l'autre thread
        engine_instance = engine
        engine_ready.set()

        # Exécuter la boucle asyncio
        loop.run_forever()
    except Exception as e:
        print(f"❌ Erreur dans le thread asyncio: {e}")
        import traceback
        traceback.print_exc()
    finally:
        loop.close()

def main():
    """Point d'entrée principal."""
    # Démarrer le thread asyncio
    t = threading.Thread(target=asyncio_thread, daemon=True)
    t.start()

    # Attendre que l'engine soit prêt
    if not engine_ready.wait(timeout=10):
        print("❌ Timeout en attendant l'engine")
        sys.exit(1)

    print("🚀 Lancement de l'interface HUD dans le thread principal")
    # run_hud est synchrone et bloque jusqu'à la fermeture
    run_hud(engine_instance)

if __name__ == "__main__":
    main()