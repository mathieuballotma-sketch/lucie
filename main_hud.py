#!/usr/bin/env python3
"""
Point d'entrée HUD Lucie V1 — interface macOS native.
Lance le HUD PyObjC qui route toutes les requêtes via lucie_v1_standalone/.

Au démarrage, un warm-up Ollama est lancé en background thread (R2 sprint S1)
pour éliminer le cold-start gemma4:e4b (~62 s prompt_eval mesurés au 1er call,
cf. baseline P0 du 2026-04-21) du chemin utilisateur. Le warm-up amorce aussi
le keep_alive 24 h déjà câblé dans ollama_client.
"""

import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

log = logging.getLogger("lucie.warmup")


def _warmup_blocking() -> None:
    """Charge gemma4:e4b en VRAM dès le boot pour éliminer le cold-start.

    Lancée dans un thread daemon depuis main() : ne bloque jamais l'UI.
    Skippable via LUCIE_SKIP_WARMUP=1 (CI / dev sans Ollama). Toute exception
    est avalée (warning log) — un warm-up qui rate ne doit jamais empêcher
    le HUD de démarrer.
    """
    if os.environ.get("LUCIE_SKIP_WARMUP", "0") == "1":
        log.info("warmup skipped via LUCIE_SKIP_WARMUP")
        return
    # Garde-fou : asyncio.run() crée un event loop qui entrerait en conflit
    # avec AppKit.runEventLoop() si exécuté sur le main thread.
    assert threading.current_thread() is not threading.main_thread(), (
        "_warmup_blocking doit tourner dans un thread séparé"
    )
    from lucie_v1_standalone import ollama_client
    from lucie_v1_standalone.config import SPEED_MODEL

    t0 = time.perf_counter()
    try:
        asyncio.run(
            ollama_client.generate(
                model=SPEED_MODEL,
                prompt=" ",
                options={"num_predict": 1, "temperature": 0},
            )
        )
        log.info("warmup ok in %.1fs", time.perf_counter() - t0)
    except Exception as exc:  # noqa: BLE001 — non-fatal par design
        log.warning("warmup failed (non-fatal): %s", exc)


def main() -> None:
    print("🚀 Lancement HUD Lucie V1")
    threading.Thread(
        target=_warmup_blocking,
        name="lucie-warmup",
        daemon=True,
    ).start()
    # Lazy import : laisse les tests importer _warmup_blocking sans tirer AppKit.
    from app.ui.hud_native import run_hud
    run_hud()


if __name__ == "__main__":
    main()
