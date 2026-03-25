"""
Test SafariResearchWorkflow — vérifie que le workflow visible fonctionne.

Usage : PYTHONPATH=. python3 scripts/check_safari_workflow.py
"""

import asyncio
import sys
import time
from typing import List


async def test_unit() -> List[str]:
    """Tests unitaires : imports, routing, speed config."""
    print("Phase 1 — Tests unitaires (imports + routing)")
    print("─" * 50)
    failures: List[str] = []

    # Test 1 : import speed_config
    t0 = time.perf_counter()
    try:
        from app.agents.speed_config import ACTIVE_PROFILE, SPEED_DEMO
        ok = ACTIVE_PROFILE.name == "demo" and SPEED_DEMO.move_duration == 0.1
        ms = (time.perf_counter() - t0) * 1000
        status = "✅" if ok else "❌"
        print(f"{status} {ms:.0f}ms — speed_config import (profile={ACTIVE_PROFILE.name})")
        if not ok:
            failures.append("speed_config: profil incorrect")
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        print(f"❌ {ms:.0f}ms — speed_config import ERREUR: {e}")
        failures.append(f"speed_config import: {e}")

    # Test 2 : import safari_research_workflow
    t0 = time.perf_counter()
    try:
        from app.agents.safari_research_workflow import SafariResearchWorkflow
        ok = hasattr(SafariResearchWorkflow, "run")
        ms = (time.perf_counter() - t0) * 1000
        status = "✅" if ok else "❌"
        print(f"{status} {ms:.0f}ms — safari_research_workflow import")
        if not ok:
            failures.append("safari_research_workflow: méthode run() manquante")
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        print(f"❌ {ms:.0f}ms — safari_research_workflow import ERREUR: {e}")
        failures.append(f"safari_research_workflow import: {e}")

    # Test 3 : router détecte visual_research
    t0 = time.perf_counter()
    try:
        from app.brain.cortex.router import PathRouter, RoutePath
        router = PathRouter()
        result = router.route("recherche le cours de l'or consulte 3 sites et fais une synthèse")
        ok = result.path == RoutePath.VISUAL_RESEARCH
        ms = (time.perf_counter() - t0) * 1000
        status = "✅" if ok else "❌"
        print(f"{status} {ms:.0f}ms — router visual_research (path={result.path.value}, agent={result.agent})")
        if not ok:
            failures.append(f"router: attendu visual_research, obtenu {result.path.value}")
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        print(f"❌ {ms:.0f}ms — router ERREUR: {e}")
        failures.append(f"router: {e}")

    # Test 4 : qwen2.5:7b profil (anciennement gemma2)
    t0 = time.perf_counter()
    try:
        from app.providers.model_profiles import get_profile
        profile = get_profile("qwen2.5:7b")
        ok = profile is not None and profile.num_ctx == 8192 and profile.temperature == 0.5
        ms = (time.perf_counter() - t0) * 1000
        status = "✅" if ok else "❌"
        detail = f"num_ctx={profile.num_ctx}, temp={profile.temperature}" if profile else "None"
        print(f"{status} {ms:.0f}ms — qwen2.5:7b profil ({detail})")
        if not ok:
            failures.append(f"qwen2.5:7b profil: {detail}")
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        print(f"❌ {ms:.0f}ms — qwen2.5:7b profil ERREUR: {e}")
        failures.append(f"qwen2.5:7b profil: {e}")

    return failures


async def test_integration() -> List[str]:
    """Test d'intégration : exécute le workflow complet."""
    print("\nPhase 2 — Intégration (workflow complet via LucidEngine)")
    print("─" * 50)
    failures: List[str] = []

    try:
        from app.core.config import Config
        from app.core.engine import LucidEngine
    except ImportError as e:
        print(f"⚠️  Import engine impossible : {e}")
        return [f"import engine: {e}"]

    config = Config.load()
    engine = LucidEngine(config)
    engine.set_loop(asyncio.get_event_loop())

    query = "recherche le cours de l'or consulte 3 sites et fais une synthèse"

    t0 = time.perf_counter()
    try:
        r, _ = await engine.process_async(query)
        ms = (time.perf_counter() - t0) * 1000
        print(f"Temps total : {ms:.0f}ms")
        print(f"Résultat : {str(r)[:200]}...")
        print()

        if ms < 25000:
            print(f"✅ Workflow visible opérationnel ({ms:.0f}ms < 25000ms)")
        else:
            print(f"❌ TROP LENT ({ms:.0f}ms > 25000ms) — EN ATTENTE D'INSTRUCTIONS")
            failures.append(f"workflow trop lent: {ms:.0f}ms > 25000ms")
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        print(f"❌ {ms:.0f}ms — workflow ERREUR: {e}")
        failures.append(f"workflow: {e}")

    try:
        await engine.stop_async()
    except Exception:
        pass

    return failures


async def main() -> None:
    print("Test SafariResearchWorkflow")
    print("═" * 50)
    print()

    failures_unit = await test_unit()

    if failures_unit:
        print()
        print("❌ Phase 1 échouée — STOPPER et reporter sans corriger seul")
        for f in failures_unit:
            print(f"  → {f}")
        sys.exit(1)

    print()
    print("✅ Phase 1 OK — tous les tests unitaires passent")

    failures_integration = await test_integration()

    print()
    print("═" * 50)
    all_failures = failures_unit + failures_integration
    if not all_failures:
        print("✅ SafariResearchWorkflow opérationnel")
    else:
        print("❌ TESTS ÉCHOUÉS — EN ATTENTE D'INSTRUCTIONS")
        for f in all_failures:
            print(f"  → {f}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
