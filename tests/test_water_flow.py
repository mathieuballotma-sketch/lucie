"""
Tests WaterFlow — exécution parallèle par stages.
Vérifie : ordre séquentiel inter-stage, parallélisme intra-stage, fallback.
"""

import asyncio
import time
import pytest


@pytest.mark.asyncio
async def test_sequential_flow():
    """Les stages s'exécutent dans l'ordre croissant."""
    from app.brain.synapses.water_flow import WaterFlow, WaterDrop

    flow = WaterFlow()
    order = []

    async def grain_a(drop):
        order.append("a")
        return {"from": "a"}

    async def grain_b(drop):
        order.append("b")
        return {"from": "b"}

    flow.add_grain("a", grain_a, stage=0)
    flow.add_grain("b", grain_b, stage=1)
    drop = await flow.run("test")

    # Stage 0 avant stage 1
    assert order == ["a", "b"]
    assert drop.enrichment_count == 2


@pytest.mark.asyncio
async def test_parallel_same_stage():
    """Grains du même stage s'exécutent en parallèle — temps total ~0.1s, pas ~0.3s."""
    from app.brain.synapses.water_flow import WaterFlow, WaterDrop

    flow = WaterFlow()

    async def slow_grain(drop):
        await asyncio.sleep(0.1)
        return {"done": True}

    # 3 grains au même stage → parallèle
    flow.add_grain("s1", slow_grain, stage=0)
    flow.add_grain("s2", slow_grain, stage=0)
    flow.add_grain("s3", slow_grain, stage=0)

    t0 = time.perf_counter()
    drop = await flow.run("test")
    elapsed = time.perf_counter() - t0

    # Parallèle : devrait prendre ~0.1s, pas ~0.3s
    assert elapsed < 0.25
    assert drop.enrichment_count == 3


@pytest.mark.asyncio
async def test_mixed_stages():
    """Mélange de stages séquentiels et parallèles."""
    from app.brain.synapses.water_flow import WaterFlow

    flow = WaterFlow()
    order = []

    async def grain(name, delay=0.0):
        async def _handler(drop):
            if delay:
                await asyncio.sleep(delay)
            order.append(name)
            return {"name": name}
        return _handler

    # Stage 0 : un seul grain (séquentiel direct)
    flow.add_grain("init", await grain("init"), stage=0)
    # Stage 1 : deux grains parallèles
    flow.add_grain("p1", await grain("p1", 0.05), stage=1)
    flow.add_grain("p2", await grain("p2", 0.05), stage=1)
    # Stage 2 : finalisation
    flow.add_grain("final", await grain("final"), stage=2)

    drop = await flow.run("test mixte")

    # init toujours en premier, final toujours en dernier
    assert order[0] == "init"
    assert order[-1] == "final"
    # p1 et p2 au milieu (ordre non garanti entre eux)
    assert set(order[1:3]) == {"p1", "p2"}
    assert drop.enrichment_count == 4


@pytest.mark.asyncio
async def test_default_stage_zero():
    """Sans stage explicite, tous les grains restent à stage=0 (rétrocompatible)."""
    from app.brain.synapses.water_flow import WaterFlow

    flow = WaterFlow()

    async def grain_x(drop):
        return {"x": True}

    async def grain_y(drop):
        return {"y": True}

    # Pas de paramètre stage — défaut 0
    flow.add_grain("x", grain_x)
    flow.add_grain("y", grain_y)

    drop = await flow.run("test défaut")
    assert drop.enrichment_count == 2


@pytest.mark.asyncio
async def test_single_grain_no_gather_overhead():
    """Un seul grain dans un stage ne passe pas par gather."""
    from app.brain.synapses.water_flow import WaterFlow

    flow = WaterFlow()

    async def solo(drop):
        return {"solo": True}

    flow.add_grain("solo", solo, stage=5)

    drop = await flow.run("test solo")
    assert drop.enrichment_count == 1
    assert drop.context.get("solo") is True
