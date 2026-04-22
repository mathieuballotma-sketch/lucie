"""Tests du module d'événements temps-réel (`perf/events.py`).

Couvrent :
  1. Level 2 émet retriever → redacteur → verificateur dans cet ordre.
  2. Level 3 (document) émet les 4 étapes (lecteur + 3 autres) via la task drain.
  3. Level 1 (small-talk) n'émet aucun event de stage pipeline.
  4. Cache hit (non-dry-run) émet PipelineEvent(stage="cache", status="cached").
  5. Une exception dans une étape émet PipelineEvent(status="error").
  6. Les events ont des timestamps monotones et des duration_ms >= 0.

Les tests utilisent des mocks légers plutôt qu'Ollama réel — on veut
vérifier la mécanique d'émission et l'ordre, pas la qualité des réponses.
"""

from __future__ import annotations

import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lucie_v1_standalone.perf.events import (
    PipelineEvent,
    bind_event_queue,
    child_event_stage,
    drain_nowait,
    emit,
    event_stage,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _collect_events(coro_factory):
    """Exécute une coroutine dans un contexte event_queue lié et retourne
    la liste des events émis (ordre d'arrivée)."""
    async with bind_event_queue() as queue:
        await coro_factory()
        return drain_nowait(queue)


# ─── Tests bas niveau events.py ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_stage_emits_started_then_completed():
    """event_stage émet started à l'entrée et completed à la sortie."""
    async def body():
        async with event_stage("retriever"):
            await asyncio.sleep(0.005)

    evs = await _collect_events(body)
    assert len(evs) == 2
    assert evs[0].stage == "retriever" and evs[0].status == "started"
    assert evs[1].stage == "retriever" and evs[1].status == "completed"
    assert evs[1].duration_ms >= 4.5


@pytest.mark.asyncio
async def test_event_stage_emits_error_on_exception():
    """event_stage émet error + re-raise si la coro lève."""
    async def body():
        async with event_stage("retriever"):
            raise RuntimeError("boom")

    async with bind_event_queue() as queue:
        with pytest.raises(RuntimeError):
            await body()
        evs = drain_nowait(queue)

    assert len(evs) == 2
    assert evs[0].status == "started"
    assert evs[1].status == "error"
    assert "boom" in evs[1].message
    assert evs[1].duration_ms >= 0


@pytest.mark.asyncio
async def test_timestamps_monotonic_and_duration_nonnegative():
    """Les timestamps sont croissants et les durées toujours positives."""
    async def body():
        async with event_stage("retriever"):
            await asyncio.sleep(0.002)
        async with event_stage("redacteur"):
            await asyncio.sleep(0.002)
        async with event_stage("verificateur"):
            await asyncio.sleep(0.002)

    evs = await _collect_events(body)
    assert len(evs) == 6  # 3 stages × 2 events
    ts = [e.timestamp for e in evs]
    assert ts == sorted(ts), "timestamps should be monotonic"
    for e in evs:
        assert e.duration_ms >= 0


@pytest.mark.asyncio
async def test_emit_noop_without_bound_queue():
    """emit() sans queue liée est un no-op silencieux (ne lève pas)."""
    emit("retriever", "started")  # pas de queue → aucun effet


# ─── Tests pipeline intégration (Level 1 / 2 / 3 / cache) ────────────────────


@pytest.mark.asyncio
async def test_level1_smalltalk_emits_no_stage_events(monkeypatch):
    """Small-talk direct → aucun event de stage pipeline (retriever, redacteur…)."""
    from lucie_v1_standalone import pipeline as pl

    # On force small_talk_reply pour être déterministe
    monkeypatch.setattr(pl, "small_talk_reply", lambda q: "Bonjour !")
    monkeypatch.setattr(pl, "classify_intent", lambda q: pl.Intent.SMALL_TALK)

    evs: List[PipelineEvent] = []
    async for item in pl.run_stream("Bonjour"):
        if isinstance(item, PipelineEvent):
            evs.append(item)

    stage_events = [e for e in evs if e.stage in ("retriever", "redacteur", "verificateur", "lecteur")]
    assert stage_events == []


@pytest.mark.asyncio
async def test_cache_hit_emits_cached_event():
    """Un hit sur le QueryCache émet PipelineEvent(stage='cache', status='cached')."""
    from lucie_v1_standalone.cache.query_cache import QueryCache

    cache = QueryCache(maxsize=16, ttl_seconds=60)
    key = cache.make_key("test query", index_version=1)

    # Premier appel : miss → stocke
    async def _factory():
        return "cached_value"

    # On entre dans un bind_event_queue pour capturer les events
    async with bind_event_queue() as q:
        v1 = await cache.get_or_compute(key, _factory, dry_run=False)
        assert v1 == "cached_value"
        # Premier appel : pas d'event cache (miss)
        evs_miss = drain_nowait(q)
        assert not any(e.stage == "cache" and e.status == "cached" for e in evs_miss)

        # Deuxième appel : hit → doit émettre cache.cached
        v2 = await cache.get_or_compute(key, _factory, dry_run=False)
        assert v2 == "cached_value"
        evs_hit = drain_nowait(q)
        cache_events = [e for e in evs_hit if e.stage == "cache" and e.status == "cached"]
        assert len(cache_events) == 1


@pytest.mark.asyncio
async def test_level2_emits_retriever_redacteur_verificateur_in_order(monkeypatch):
    """Level 2 (search) émet dans l'ordre : retriever → redacteur → verificateur."""
    from lucie_v1_standalone import pipeline as pl

    # Intent = analyse/search classique
    monkeypatch.setattr(pl, "classify_intent", lambda q: pl.Intent.PRECISE_LEGAL)
    monkeypatch.setattr(pl, "router_validate", lambda q, d: {"valid": True})
    monkeypatch.setattr(
        pl, "router_route", lambda q, d, force=False: {"level": "search", "intent": "legal"}
    )

    # Mock des agents : renvoient du JSON/texte minimal, rapidement.
    retriever_mock = AsyncMock(return_value='{"sources":[]}')
    monkeypatch.setattr(pl.retriever, "handle", retriever_mock)

    async def _redacteur_stream(*args, **kwargs):
        yield "Voici "
        yield "la réponse."

    monkeypatch.setattr(pl.redacteur, "handle_stream", _redacteur_stream)

    verificateur_mock = AsyncMock(return_value='{"citations_ok":true,"score":1.0}')
    monkeypatch.setattr(pl.verificateur, "handle", verificateur_mock)

    # Formatter le résultat final
    monkeypatch.setattr(pl, "_format_final", lambda note, vj, verbose: note)
    monkeypatch.setattr(pl, "_attach_suggested_replies", lambda r: r)

    stages_order: List[str] = []
    async for item in pl.run_stream("Article L.1234-1"):
        if isinstance(item, PipelineEvent) and item.status == "started":
            stages_order.append(item.stage)

    # Ordre attendu : retriever, redacteur, verificateur
    assert stages_order == ["retriever", "redacteur", "verificateur"], (
        f"ordre inattendu : {stages_order}"
    )


@pytest.mark.asyncio
async def test_retriever_error_emits_error_event(monkeypatch):
    """Une exception du Retriever émet PipelineEvent(stage='retriever', status='error')."""
    from lucie_v1_standalone import pipeline as pl

    monkeypatch.setattr(pl, "classify_intent", lambda q: pl.Intent.PRECISE_LEGAL)
    monkeypatch.setattr(pl, "router_validate", lambda q, d: {"valid": True})
    monkeypatch.setattr(
        pl, "router_route", lambda q, d, force=False: {"level": "search", "intent": "legal"}
    )

    async def _boom(*a, **kw):
        raise RuntimeError("retriever crash")

    monkeypatch.setattr(pl.retriever, "handle", _boom)

    error_events: List[PipelineEvent] = []
    async for item in pl.run_stream("Article L.1234-1"):
        if isinstance(item, PipelineEvent) and item.status == "error":
            error_events.append(item)

    assert any(e.stage == "retriever" for e in error_events), (
        "pas d'event error pour retriever"
    )
    assert any("retriever crash" in (e.message or "") for e in error_events)


# ─── Phase 1ter — parent_id / event_id / hook_name ──────────────────────────


@pytest.mark.asyncio
async def test_event_id_is_unique_across_emits():
    """Chaque event a un event_id unique (uuid4[:12])."""
    async def body():
        for _ in range(5):
            emit("retriever", "started", "stub")

    evs = await _collect_events(body)
    ids = [e.event_id for e in evs]
    assert len(ids) == 5
    assert len(set(ids)) == 5, f"event_ids should be unique, got {ids}"
    for eid in ids:
        assert isinstance(eid, str) and len(eid) == 12


@pytest.mark.asyncio
async def test_parent_id_propagated_via_contextvar():
    """Les enfants émis dans un event_stage héritent de son event_id."""
    async def body():
        async with event_stage("retriever"):
            async with child_event_stage("lit_article", article="L.1233-3"):
                pass
            async with child_event_stage("lit_article", article="L.1233-4"):
                pass

    evs = await _collect_events(body)
    # retriever.started + 2×(child.started + child.completed) + retriever.completed = 6
    assert len(evs) == 6
    # L'event racine (retriever.started) n'a pas de parent
    root_started = evs[0]
    assert root_started.stage == "retriever"
    assert root_started.status == "started"
    assert root_started.parent_id is None
    assert root_started.hook_name is None

    # Les 4 events enfants (2 started + 2 completed) partagent le même parent_id
    child_events = [e for e in evs if e.hook_name == "lit_article"]
    assert len(child_events) == 4
    for ev in child_events:
        assert ev.parent_id == root_started.event_id, (
            f"enfant {ev.hook_name}.{ev.status} devrait hériter de {root_started.event_id}, "
            f"a {ev.parent_id}"
        )
        # Stage hérité du parent puisque non fourni
        assert ev.stage == "retriever"


@pytest.mark.asyncio
async def test_child_event_stage_without_parent_is_not_an_error():
    """child_event_stage hors d'un event_stage parent ne lève pas — parent_id=None."""
    async def body():
        async with child_event_stage("lit_article", stage="retriever", article="L.1"):
            pass

    evs = await _collect_events(body)
    assert len(evs) == 2
    assert all(e.parent_id is None for e in evs)
    assert all(e.hook_name == "lit_article" for e in evs)
    assert all(e.stage == "retriever" for e in evs)


@pytest.mark.asyncio
async def test_pipeline_event_backward_compat():
    """PipelineEvent peut toujours être construit avec les champs historiques seuls."""
    ev = PipelineEvent(stage="retriever", status="started")
    # Les nouveaux champs ont des defaults sensés
    assert ev.parent_id is None
    assert ev.hook_name is None
    assert isinstance(ev.event_id, str) and len(ev.event_id) == 12
    assert ev.duration_ms == 0.0
    assert ev.details == {}
