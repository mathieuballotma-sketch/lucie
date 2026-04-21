"""Tests streaming (P1) — sans appel Ollama réel (mocks)."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, List
from unittest.mock import AsyncMock, patch

import pytest

from lucie_v1_standalone import pipeline, redacteur, ollama_client
from lucie_v1_standalone.pipeline import PipelineResponse, run_stream, streaming_enabled


def _as_stream(chunks: List[str]) -> AsyncIterator[str]:
    async def gen():
        for c in chunks:
            yield c
    return gen()


def test_streaming_enabled_default(monkeypatch):
    monkeypatch.delenv("LUCIE_STREAM", raising=False)
    assert streaming_enabled() is True


def test_streaming_disabled_when_flag_off(monkeypatch):
    monkeypatch.setenv("LUCIE_STREAM", "0")
    assert streaming_enabled() is False


def test_redacteur_handle_stream_returns_block_message_when_no_sources():
    """Si 0 sources, handle_stream yield le message de blocage en un coup."""
    async def go():
        chunks = []
        async for c in redacteur.handle_stream(
            faits_json='{"query": "x"}',
            sources_json='{"sources": [], "jurisprudences": []}',
            mode="search",
        ):
            chunks.append(c)
        return "".join(chunks)

    result = asyncio.run(go())
    assert "RÉDACTION IMPOSSIBLE" in result


def test_redacteur_handle_stream_yields_chunks(monkeypatch):
    """Avec des sources, handle_stream délègue à generate_stream."""
    sources_json = (
        '{"sources": [{"id": "L.1234-1", "titre": "Préavis", "extrait": "x", "pertinence": 0.9, "fichier_source": "f"}], '
        '"jurisprudences": [], "non_trouve": []}'
    )

    async def fake_stream(**kwargs):
        for c in ["Hello ", "world"]:
            yield c

    with patch.object(ollama_client, "generate_stream", side_effect=fake_stream):
        async def go():
            chunks = []
            async for c in redacteur.handle_stream(
                faits_json='{"query": "q"}',
                sources_json=sources_json,
                mode="search",
            ):
                chunks.append(c)
            return chunks

        chunks = asyncio.run(go())
    assert chunks == ["Hello ", "world"]


def test_run_stream_small_talk_yields_response_directly():
    """SMALL_TALK doit retourner une PipelineResponse sans passer par un stream Ollama."""
    async def go():
        events = []
        async for evt in run_stream("bonjour"):
            events.append(evt)
        return events

    events = asyncio.run(go())
    # Un seul event (PipelineResponse) — pas de chunks string
    assert len(events) == 1
    assert isinstance(events[0], PipelineResponse)
    assert events[0].answer  # non vide


def test_run_stream_falls_back_to_run_when_disabled(monkeypatch):
    """LUCIE_STREAM=0 → fallback sur run() — on yield 1 seul PipelineResponse."""
    monkeypatch.setenv("LUCIE_STREAM", "0")
    fake = PipelineResponse(answer="final", mode="analysis")

    with patch.object(pipeline, "run", new=AsyncMock(return_value=fake)):
        async def go():
            events = []
            async for evt in run_stream("some query"):
                events.append(evt)
            return events

        events = asyncio.run(go())

    assert events == [fake]


def test_run_stream_n2_streams_chunks_then_final(monkeypatch):
    """Niveau 2 : doit yield des strings (chunks) puis 1 PipelineResponse final."""
    monkeypatch.setenv("LUCIE_STREAM", "1")

    # Mock redacteur.handle_stream pour éviter appel LLM
    async def fake_red_stream(*args, **kwargs):
        for c in ["Réponse ", "juridique ", "[L.1234-1]"]:
            yield c

    # Mock retriever.handle pour éviter lecture base
    sources_out = (
        '{"sources": [{"id": "L.1234-1", "titre": "T", "extrait": "e", '
        '"pertinence": 0.9, "fichier_source": "f"}], "jurisprudences": [], "non_trouve": []}'
    )

    # Mock verificateur pour éviter le LLM-path fallback
    verif_out = '{"note_corrigee": "Réponse juridique [L.1234-1]", "score_fiabilite": 1.0, "verdict": "VALIDE"}'

    with patch.object(redacteur, "handle_stream", side_effect=fake_red_stream), \
         patch("lucie_v1_standalone.pipeline.retriever.handle", new=AsyncMock(return_value=sources_out)), \
         patch("lucie_v1_standalone.pipeline.verificateur.handle", new=AsyncMock(return_value=verif_out)):

        async def go():
            events = []
            async for evt in run_stream("Délai de préavis article L1234-1 ?"):
                events.append(evt)
            return events

        events = asyncio.run(go())

    # Séparer chunks et final
    chunks = [e for e in events if isinstance(e, str)]
    finals = [e for e in events if isinstance(e, PipelineResponse)]
    assert chunks, "Pas de chunks yieldés"
    assert len(finals) == 1
    assert "L.1234-1" in finals[0].answer
