"""Tests d'intégration des hooks fins (child_event_stage / emit hook_name).

Vérifie qu'avec les hooks posés en Commit 5 dans retriever.py, redacteur.py,
verificateur.py et knowledge_legifrance/retriever.py :

  1. Plusieurs sous-events `lit_article` émis dans un même `event_stage("retriever")`
     partagent le même `parent_id` (= event_id du started retriever).
  2. Un `child_event_stage` émis sans parent actif dans la ContextVar ne lève pas
     et sort avec `parent_id=None`.
  3. Le `stage` du sous-event est hérité du parent courant si non fourni.
  4. Backward compat : un `PipelineEvent` construit minimalement marche toujours.
"""

from __future__ import annotations

import asyncio
from typing import List
from unittest.mock import AsyncMock, patch

import pytest

from lucie_v1_standalone.perf.events import (
    PipelineEvent,
    bind_event_queue,
    child_event_stage,
    drain_nowait,
    event_stage,
)


async def _collect(coro_factory) -> List[PipelineEvent]:
    async with bind_event_queue() as queue:
        await coro_factory()
        return drain_nowait(queue)


@pytest.mark.asyncio
async def test_retriever_curated_child_events_share_parent_id():
    """Trois articles matchés dans `retriever.handle` → 3 sous-events avec le
    même `parent_id` = l'event_id du started retriever."""
    from lucie_v1_standalone import retriever as curated
    import json

    # Index fake : 3 documents avec des refs distinctes.
    fake_index = [
        {
            "id": "L.1233-3",
            "path": "/fake/L.1233-3.md",
            "content": "# Article L.1233-3\nTexte contenant L.1233-3.",
            "tokens": ["article", "l", "1233", "3", "texte"],
            "tokens_set": {"article", "l", "1233", "3", "texte"},
        },
        {
            "id": "L.1233-4",
            "path": "/fake/L.1233-4.md",
            "content": "# Article L.1233-4\nTexte contenant L.1233-4.",
            "tokens": ["article", "l", "1233", "4", "texte"],
            "tokens_set": {"article", "l", "1233", "4", "texte"},
        },
        {
            "id": "L.1233-5",
            "path": "/fake/L.1233-5.md",
            "content": "# Article L.1233-5\nTexte contenant L.1233-5.",
            "tokens": ["article", "l", "1233", "5", "texte"],
            "tokens_set": {"article", "l", "1233", "5", "texte"},
        },
    ]

    faits = json.dumps({"query": "L.1233-3 L.1233-4 L.1233-5"})

    async def body():
        with patch.object(curated, "get_index", return_value=fake_index), \
             patch.object(curated, "_try_legifrance", return_value=None):
            async with event_stage("retriever"):
                await curated.handle(faits)

    evs = await _collect(body)

    # Isole le started retriever et les sous-events lit_article.
    started = [e for e in evs if e.status == "started" and e.hook_name is None]
    assert len(started) == 1
    parent_eid = started[0].event_id

    children = [e for e in evs if e.hook_name == "lit_article"]
    assert len(children) >= 3, f"attendu ≥3 lit_article, got {len(children)}"
    for c in children:
        assert c.parent_id == parent_eid, (
            f"child lit_article sans bon parent_id : {c.parent_id} != {parent_eid}"
        )
        # Le stage hérite du parent retriever.
        assert c.stage == "retriever"
        # Le détail `article` est bien propagé.
        assert "article" in c.details


@pytest.mark.asyncio
async def test_child_event_stage_without_parent_contextvar():
    """child_event_stage hors de tout event_stage → parent_id=None, pas d'erreur."""
    async def body():
        async with child_event_stage("lit_article", stage="retriever", article="L.1"):
            pass

    evs = await _collect(body)
    assert len(evs) == 2
    for e in evs:
        assert e.parent_id is None
        assert e.hook_name == "lit_article"
        assert e.stage == "retriever"


@pytest.mark.asyncio
async def test_child_event_stage_inherits_stage_from_parent():
    """Sans `stage=` explicite, le sous-event hérite du stage parent."""
    async def body():
        async with event_stage("verificateur"):
            async with child_event_stage("verifie_citation", cite="L.1233-3"):
                pass

    evs = await _collect(body)
    children = [e for e in evs if e.hook_name == "verifie_citation"]
    assert len(children) == 2  # started + completed
    for c in children:
        assert c.stage == "verificateur", (
            f"child devrait hériter stage=verificateur, got {c.stage}"
        )


@pytest.mark.asyncio
async def test_pipeline_event_minimal_backward_compat():
    """Un PipelineEvent construit avec seulement (stage, status) reste valide :
    event_id auto-généré, parent_id et hook_name par défaut None."""
    ev = PipelineEvent(stage="retriever", status="started")
    assert ev.event_id  # non-vide
    assert len(ev.event_id) == 12
    assert ev.parent_id is None
    assert ev.hook_name is None
    assert ev.duration_ms == 0.0
    assert ev.details == {}


@pytest.mark.asyncio
async def test_verificateur_emits_per_citation_events():
    """verificateur.handle() émet un sous-event par citation vérifiée."""
    from lucie_v1_standalone import verificateur

    note = "Selon [L.1233-3], le reclassement est obligatoire. Voir aussi [INEXIST-999]."
    sources_json = (
        '{"sources": [{"id": "L.1233-3", "extrait": "..."}], "jurisprudences": []}'
    )

    async def body():
        async with event_stage("verificateur"):
            # Phase A : le Vérificateur est 100 % déterministe (plus d'appel
            # Ollama à mocker). Les patches LLM ont été retirés avec le LLM.
            await verificateur.handle(note, sources_json)

    evs = await _collect(body)
    started = [e for e in evs if e.status == "started" and e.hook_name is None]
    assert len(started) == 1
    parent_eid = started[0].event_id

    per_citation = [e for e in evs if e.hook_name == "verifie_citation"]
    assert len(per_citation) == 2  # L.1233-3 + INEXIST-999
    for ev in per_citation:
        assert ev.parent_id == parent_eid
        assert ev.stage == "verificateur"
        assert "cite" in ev.details
