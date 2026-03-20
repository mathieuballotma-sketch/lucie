"""
Simulation cerveau numérique complet — LUCIE.
ContextWave + MemoryGraph + Thalamus + DefaultModeNetwork ensemble.

Lance : PYTHONPATH=. python3 tests/simulation/sim_full_brain.py
"""

import asyncio
import sys
sys.path.insert(0, ".")

from tests.simulation.sim_context_wave import ContextWave
from tests.simulation.sim_memory_graph import MemoryGraph
from tests.simulation.sim_thalamus import detect_frequency
from tests.simulation.sim_default_mode import DefaultModeNetwork


async def simulate_full_brain():
    print("=" * 55)
    print("SIMULATION CERVEAU NUMÉRIQUE COMPLET — LUCIE")
    print("=" * 55)
    print()

    # ── 1. Créer l'onde contextuelle ────────────────────────────
    ctx = ContextWave.create("cherche le cours de l'or", budget=15.0)
    assert ctx.remaining() > 14.0
    print(f"1️⃣  Onde créée : '{ctx.query}' (budget {ctx.budget}s)")

    # ── 2. Thalamus détecte la fréquence ───────────────────────
    signal = detect_frequency(ctx.query)
    assert signal in ("finance_query", "research_query")
    print(f"2️⃣  Thalamus → signal : {signal}")

    # ── 3. MemoryGraph trouve les concepts liés ────────────────
    graph = MemoryGraph()
    graph.link("or", "bitcoin", 0.8)
    graph.link("or", "bourse", 0.9)
    graph.link("bitcoin", "crypto", 0.7)
    graph.link("bourse", "investissement", 0.6)
    graph.link("finance", "or", 1.0)

    related = graph.resonate("or")
    assert len(related) > 0
    print(f"3️⃣  MemoryGraph → concepts liés : {[r[0] for r in related]}")

    # ── 4. ContextWave propage avec mémoire enrichie ───────────
    child_ctx = ctx.next_wave(memory=tuple(r[0] for r in related))
    assert child_ctx.chain_step == 1
    assert len(child_ctx.memory) > 0
    print(f"4️⃣  Onde propagée : étape {child_ctx.chain_step}, mémoire {child_ctx.memory}")

    # ── 5. DefaultModeNetwork tourne en parallèle ──────────────
    dmn = DefaultModeNetwork(interval=1.5)
    memories = [
        {"content": "cours or bitcoin finance bourse"},
        {"content": "recherche investissement marché actions"},
        {"content": "python code erreur fonction debug"},
    ]

    dmn_task = asyncio.create_task(dmn.run(lambda: memories))

    # ── 6. Simuler 3 sources parallèles (comme Safari workflow) ─
    async def fake_source(name: str, delay: float) -> str:
        await asyncio.sleep(delay)
        return f"résultat {name}"

    results = await asyncio.gather(
        fake_source("boursorama", 0.3),
        fake_source("google_finance", 0.5),
        fake_source("investing.com", 0.4),
    )
    assert len(results) == 3
    print(f"5️⃣  3 sources parallèles : {results}")

    # ── 7. Budget vérifié tout du long ─────────────────────────
    assert ctx.remaining() > 0
    assert not ctx.is_expired()
    print(f"6️⃣  Budget restant : {ctx.remaining():.1f}s ✅")

    # ── 8. Attendre que DMN ait réfléchi au moins 1 fois ───────
    await asyncio.sleep(2.0)
    dmn.stop()
    dmn_task.cancel()
    try:
        await dmn_task
    except asyncio.CancelledError:
        pass

    assert dmn.reflection_count >= 1
    print(f"7️⃣  DMN : {dmn.reflection_count} cycle(s) de réflexion")

    # ── 9. Deuxième onde — chaînage complet ────────────────────
    final_ctx = child_ctx.next_wave()
    assert final_ctx.chain_step == 2
    assert final_ctx.created == ctx.created  # même timestamp = budget partagé
    print(f"8️⃣  Chaîne complète : {final_ctx.chain_step} étapes, budget partagé ✅")

    # ── Rapport ────────────────────────────────────────────────
    print()
    print("=" * 55)
    print("RÉSULTATS SIMULATION")
    print("=" * 55)
    print(f"  Signal Thalamus    : {signal}")
    print(f"  Concepts résonants : {[r[0] for r in related]}")
    print(f"  Sources parallèles : 3 en {max(0.3, 0.5, 0.4):.1f}s (vs {0.3+0.5+0.4:.1f}s séquentiel)")
    print(f"  Chaîne ContextWave : {final_ctx.chain_step} étapes")
    print(f"  Budget restant     : {ctx.remaining():.1f}s / {ctx.budget}s")
    print(f"  Réflexions DMN     : {dmn.reflection_count}")
    print(f"  Insights DMN       : {dmn.insights_history}")
    print()
    print("✅ SIMULATION CERVEAU COMPLET : SUCCÈS")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(simulate_full_brain())
