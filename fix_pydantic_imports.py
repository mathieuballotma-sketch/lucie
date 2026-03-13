#!/usr/bin/env python3
"""
Fix pydantic imports dans tous les agents pour compatibilité pydantic v2.

Stratégie : utiliser pydantic.v1 (couche de compatibilité intégrée dans pydantic v2)
  from pydantic import BaseModel  →  from pydantic.v1 import BaseModel
  from pydantic import Field      →  from pydantic.v1 import Field
  from pydantic import validator  →  from pydantic.v1 import validator

Aussi : base_agent.py utilise .dict() → remplacé par .model_dump() avec fallback v1.
"""

import re
import sys
from pathlib import Path

# ── Fichiers à corriger ───────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
AGENTS_DIR   = PROJECT_ROOT / "app" / "agents"

FILES = [
    AGENTS_DIR / "document_agent.py",
    AGENTS_DIR / "strategist_agent.py",
    AGENTS_DIR / "creator_agent.py",
    AGENTS_DIR / "base_agent.py",
    AGENTS_DIR / "planner_agent.py",
    AGENTS_DIR / "vision" / "text_extractor.py",
    AGENTS_DIR / "healer_agent.py",
    AGENTS_DIR / "team_leader_agent.py",
    AGENTS_DIR / "deception_agent.py",
    AGENTS_DIR / "knowledge_agent.py",
    AGENTS_DIR / "soul_agent.py",
    AGENTS_DIR / "reminder_agent.py",
    AGENTS_DIR / "computer_control_agent.py",
]

# ── Patterns de remplacement ──────────────────────────────────────────────────
REPLACEMENTS = [
    # Import simple : from pydantic import X, Y, Z  →  from pydantic.v1 import X, Y, Z
    (
        r"from pydantic import ([^\n]+)",
        r"from pydantic.v1 import \1",
    ),
    # Import avec alias : import pydantic  (rare, mais au cas où)
    # On ne touche pas "from pydantic.v1" déjà corrigé
    # .dict() → .model_dump() n'est PAS fait ici car pydantic.v1 garde .dict()
]

def fix_file(path: Path) -> bool:
    """Applique les corrections à un fichier. Retourne True si modifié."""
    if not path.exists():
        print(f"  ⚠️  Fichier introuvable : {path}")
        return False

    original = path.read_text(encoding="utf-8")
    content  = original

    for pattern, replacement in REPLACEMENTS:
        content = re.sub(pattern, replacement, content)

    # Évite de doubler si déjà corrigé (ex: "from pydantic.v1.v1")
    content = content.replace("from pydantic.v1.v1 import", "from pydantic.v1 import")

    if content == original:
        print(f"  ✓  {path.name} — déjà correct ou pas d'import pydantic")
        return False

    path.write_text(content, encoding="utf-8")
    print(f"  ✅ {path.name} — corrigé")
    return True


def main():
    print("🔧 Correction des imports pydantic → pydantic.v1\n")
    modified = 0
    for f in FILES:
        if fix_file(f):
            modified += 1

    print(f"\n{'='*50}")
    print(f"✅ {modified} fichier(s) modifié(s)")
    print("\nRechargez VS Code pour voir les changements.")


if __name__ == "__main__":
    main()