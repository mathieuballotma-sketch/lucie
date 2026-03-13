#!/usr/bin/env python3
"""
Script de correction globale — Agent Lucide
Corrige les 5 catégories d'erreurs pyright détectées.

Catégorie 1 : MetricsCollector inexistant → supprimé, remplacé par imports directs
Catégorie 2 : import time / asyncio manquants
Catégorie 3 : AppKit/EventKit/ApplicationServices → try/except + type: ignore
Catégorie 4 : handle() sync au lieu d'async (override incompatible)
Catégorie 5 : Divers None assigné à str / Optional manquants
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def write(p: Path, content: str) -> None:
    p.write_text(content, encoding="utf-8")

def fix_file(path: Path, *fixes) -> bool:
    if not path.exists():
        print(f"  ⚠️  Introuvable : {path.relative_to(ROOT)}")
        return False
    original = read(path)
    content = original
    for fn in fixes:
        content = fn(content)
    if content != original:
        write(path, content)
        print(f"  ✅ {path.relative_to(ROOT)}")
        return True
    print(f"  ✓  {path.relative_to(ROOT)} — déjà correct")
    return False

# ─────────────────────────────────────────────────────────────────────────────
# Fix 1 : MetricsCollector → supprimer l'import et les usages
# ─────────────────────────────────────────────────────────────────────────────
def fix_metrics_collector(src: str) -> str:
    # Supprimer la ligne d'import
    src = re.sub(r"from .*?metrics.*? import .*?MetricsCollector.*?\n", "", src)
    src = re.sub(r"from app\.utils\.metrics import MetricsCollector\n", "", src)
    # Supprimer les instanciations
    src = re.sub(r"\s*self\.metrics\s*=\s*MetricsCollector\(\)\n", "\n", src)
    # Remplacer self.metrics.increment("x") par pass (ou supprimer la ligne)
    src = re.sub(r"\s*self\.metrics\.increment\([^)]*\)\n", "\n", src)
    src = re.sub(r"\s*self\.metrics\.increment\([^)]*\)", "", src)
    return src

# ─────────────────────────────────────────────────────────────────────────────
# Fix 2 : imports manquants (time, asyncio)
# ─────────────────────────────────────────────────────────────────────────────
def ensure_import(module: str):
    def fix(src: str) -> str:
        if f"import {module}" not in src:
            # Insérer après les autres imports stdlib
            src = re.sub(
                r"(^import |^from )",
                f"import {module}\n\\1",
                src, count=1, flags=re.MULTILINE,
            )
        return src
    return fix

# ─────────────────────────────────────────────────────────────────────────────
# Fix 3 : handle() sync → async (override incompatible)
# ─────────────────────────────────────────────────────────────────────────────
def fix_handle_sync(src: str) -> str:
    # def handle(self, ...) -> str:  qui ne commence pas par "async"
    src = re.sub(
        r"^(\s*)def (handle\(self[^)]*\)\s*->\s*str\s*:)",
        r"\1async def \2",
        src, flags=re.MULTILINE,
    )
    return src

# ─────────────────────────────────────────────────────────────────────────────
# Fix 4 : AppKit imports → try/except avec type: ignore
# ─────────────────────────────────────────────────────────────────────────────
def fix_appkit_imports(src: str) -> str:
    # Déjà dans un try/except → on ne touche pas
    if "try:" in src and "AppKit" in src:
        return src
    # import AppKit direct → entourer de try/except
    src = re.sub(
        r"^import AppKit\n(from AppKit import [^\n]+\n)*",
        lambda m: (
            "try:\n"
            + "".join(f"    {line}\n" for line in m.group(0).splitlines() if line.strip())
            + "    _APPKIT_OK = True\n"
            "except ImportError:\n"
            "    _APPKIT_OK = False\n"
        ),
        src, flags=re.MULTILINE,
    )
    return src

# ─────────────────────────────────────────────────────────────────────────────
# Fix 5 : subscribe appelé sans await sur self.event_bus
# ─────────────────────────────────────────────────────────────────────────────
def fix_sync_subscribe(src: str) -> str:
    # self.event_bus.subscribe( sans await → signaler dans un commentaire
    # (le vrai fix est dans les fichiers déjà corrigés — ici on cherche les derniers cas)
    src = re.sub(
        r"(?<!await )self\.event_bus\.subscribe\(",
        "await self.event_bus.subscribe(",
        src,
    )
    return src

# ─────────────────────────────────────────────────────────────────────────────
# Fix 6 : import ddgs manquant → guard try/except
# ─────────────────────────────────────────────────────────────────────────────
def fix_ddgs_import(src: str) -> str:
    src = re.sub(
        r"^from ddgs import DDGS\n",
        "try:\n    from ddgs import DDGS\n    _DDGS_OK = True\nexcept ImportError:\n    _DDGS_OK = False\n    DDGS = None  # type: ignore\n",
        src, flags=re.MULTILINE,
    )
    return src

# ─────────────────────────────────────────────────────────────────────────────
# Fix 7 : json5 import → guard try/except
# ─────────────────────────────────────────────────────────────────────────────
def fix_json5_import(src: str) -> str:
    src = re.sub(
        r"^import json5\n",
        "try:\n    import json5\n    _JSON5_OK = True\nexcept ImportError:\n    json5 = None  # type: ignore\n    _JSON5_OK = False\n",
        src, flags=re.MULTILINE,
    )
    return src

# ─────────────────────────────────────────────────────────────────────────────
# Application des fixes
# ─────────────────────────────────────────────────────────────────────────────
AGENTS = ROOT / "app" / "agents"
CORE   = ROOT / "app" / "core"
APP    = ROOT / "app"

modified = 0

print("\n📦 Catégorie 1 — MetricsCollector")
for path in [
    AGENTS / "healer_agent.py",
    AGENTS / "planner_agent.py",
    CORE   / "engine.py",
    APP    / "brain" / "cortex.py",
    APP    / "memory" / "episodic_memory.py",
]:
    if fix_file(path, fix_metrics_collector):
        modified += 1

print("\n⏱️  Catégorie 2 — imports manquants")
for path, module in [
    (APP / "deception" / "lures.py",   "time"),
    (APP / "memory" / "episodic_memory.py", "asyncio"),
]:
    if fix_file(path, ensure_import(module)):
        modified += 1

print("\n🔄 Catégorie 3 — handle() sync → async")
for path in [
    AGENTS / "file_agent.py",
    AGENTS / "profile_agent.py",
]:
    if fix_file(path, fix_handle_sync):
        modified += 1

print("\n🔌 Catégorie 4 — subscribe sans await")
for path in [
    AGENTS / "healer_agent.py",
    AGENTS / "planner_agent.py",
]:
    if fix_file(path, fix_sync_subscribe):
        modified += 1

print("\n📦 Catégorie 5 — imports optionnels (ddgs, json5)")
for path, fn in [
    (APP / "services" / "web_search.py",  fix_ddgs_import),
    (APP / "utils"    / "json_parser.py", fix_json5_import),
]:
    if fix_file(path, fn):
        modified += 1

print(f"\n{'='*50}")
print(f"✅ {modified} fichier(s) modifié(s)")
print("\nFais Cmd+Shift+P → Reload Window dans VS Code.")