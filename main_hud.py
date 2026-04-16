#!/usr/bin/env python3
"""
Point d'entrée HUD Lucie V1 — interface macOS native.
Lance le HUD PyObjC qui route toutes les requêtes via lucie_v1_standalone/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.ui.hud_native import run_hud


def main() -> None:
    print("🚀 Lancement HUD Lucie V1")
    run_hud()


if __name__ == "__main__":
    main()
