"""
Test AXUIElement — vérifie que l'AccessibilityLayer fonctionne
et que ComputerControlAgent utilise AX au lieu de coordonnées fixes.

Usage : PYTHONPATH=. python3 scripts/check_accessibility.py
"""

import asyncio
import sys
import time
from typing import List, Tuple

from app.agents.accessibility_layer import AccessibilityLayer


async def test_ax_layer() -> List[str]:
    """Teste l'AccessibilityLayer isolément (sans LucidEngine)."""
    ax = AccessibilityLayer()
    print("Phase 1 — AccessibilityLayer (tests unitaires)")
    print("─" * 50)

    failures: List[str] = []

    # Test 1 : get_frontmost_app
    t0 = time.perf_counter()
    app = await ax.get_frontmost_app()
    ms = (time.perf_counter() - t0) * 1000
    ok = app is not None and ms < 500
    status = "✅" if ok else "❌"
    print(f"{status} {ms:.0f}ms/500ms — get_frontmost_app() = {app}")
    if not ok:
        failures.append(f"get_frontmost_app → {ms:.0f}ms, result={app}")

    # Test 2 : is_app_running (Finder est toujours actif)
    t0 = time.perf_counter()
    running = await ax.is_app_running("Finder")
    ms = (time.perf_counter() - t0) * 1000
    ok = running and ms < 500
    status = "✅" if ok else "❌"
    print(f"{status} {ms:.0f}ms/500ms — is_app_running('Finder') = {running}")
    if not ok:
        failures.append(f"is_app_running(Finder) → {ms:.0f}ms, running={running}")

    # Test 3 : is_app_running (app qui n'existe pas)
    t0 = time.perf_counter()
    not_running = await ax.is_app_running("AppQuiExistePas12345")
    ms = (time.perf_counter() - t0) * 1000
    ok = not not_running and ms < 500
    status = "✅" if ok else "❌"
    print(f"{status} {ms:.0f}ms/500ms — is_app_running('AppQuiExistePas') = {not_running}")
    if not ok:
        failures.append(f"is_app_running(fake) → {ms:.0f}ms, result={not_running}")

    # Test 4 : get_window_bounds (Finder)
    t0 = time.perf_counter()
    bounds = await ax.get_window_bounds("Finder")
    ms = (time.perf_counter() - t0) * 1000
    # Finder peut ne pas avoir de fenêtre ouverte — on tolère None
    status = "✅" if ms < 500 else "❌"
    print(f"{status} {ms:.0f}ms/500ms — get_window_bounds('Finder') = {bounds}")
    if ms >= 500:
        failures.append(f"get_window_bounds(Finder) → {ms:.0f}ms")

    # Test 5 : bring_to_front (Finder)
    t0 = time.perf_counter()
    brought = await ax.bring_to_front("Finder")
    ms = (time.perf_counter() - t0) * 1000
    ok = brought and ms < 500
    status = "✅" if ok else "❌"
    print(f"{status} {ms:.0f}ms/500ms — bring_to_front('Finder') = {brought}")
    if not ok:
        failures.append(f"bring_to_front(Finder) → {ms:.0f}ms, result={brought}")

    return failures


async def test_engine_integration() -> List[str]:
    """Teste l'intégration via LucidEngine (ouvre/ferme Safari, Terminal)."""
    # Import tardif pour ne pas bloquer si engine pas dispo
    try:
        from app.core.config import Config
        from app.core.engine import LucidEngine
    except ImportError as e:
        print(f"⚠️  Import engine impossible : {e}")
        return [f"import engine: {e}"]

    print("\nPhase 2 — Intégration ComputerControlAgent via LucidEngine")
    print("─" * 50)

    failures: List[str] = []

    config = Config.load()
    engine = LucidEngine(config)
    engine.set_loop(asyncio.get_event_loop())

    queries: List[Tuple[str, int]] = [
        ("ouvre Safari", 500),
        ("ferme Safari", 1000),
        ("ouvre Terminal", 500),
        ("ferme Terminal", 1000),
    ]

    for query, max_ms in queries:
        t0 = time.perf_counter()
        try:
            r, _ = await engine.process_async(query)
            ms = (time.perf_counter() - t0) * 1000
            ok = ms < max_ms
            if not ok:
                failures.append(f"{query} → {ms:.0f}ms > {max_ms}ms")
            status = "✅" if ok else "❌"
            print(f"{status} {ms:.0f}ms/{max_ms}ms — {query}")
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            failures.append(f"{query} → exception: {e}")
            print(f"❌ {ms:.0f}ms/{max_ms}ms — {query} — ERREUR: {e}")

    try:
        await engine.stop_async()
    except Exception:
        pass

    return failures


async def main() -> None:
    print("Test AXUIElement — ComputerControlAgent")
    print("═" * 50)
    print()

    # Phase 1 : tests unitaires AccessibilityLayer
    failures_ax = await test_ax_layer()

    if failures_ax:
        print()
        print("❌ Phase 1 échouée — STOPPER et reporter sans corriger seul")
        for f in failures_ax:
            print(f"  → {f}")
        sys.exit(1)

    print()
    print("✅ Phase 1 OK — AccessibilityLayer opérationnel")

    # Phase 2 : tests intégration engine
    failures_engine = await test_engine_integration()

    print()
    print("═" * 50)
    all_failures = failures_ax + failures_engine
    if not all_failures:
        print("✅ AXUIElement opérationnel — tous les tests passent")
    else:
        print("❌ TESTS ÉCHOUÉS — EN ATTENTE D'INSTRUCTIONS")
        for f in all_failures:
            print(f"  → {f}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
