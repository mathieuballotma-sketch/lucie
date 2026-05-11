"""Tests streaming (P1) — sans appel Ollama réel (mocks)."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, List
from unittest.mock import AsyncMock, patch

import pytest

from lucie_v1_standalone import pipeline, redacteur, ollama_client
from lucie_v1_standalone.ollama_client import ChatChunk
from lucie_v1_standalone.pipeline import PipelineResponse, run_stream, streaming_enabled


def _as_stream(chunks: List[str]) -> AsyncIterator[str]:
    async def gen():
        for c in chunks:
            yield c
    return gen()


def test_streaming_enabled_default(monkeypatch):
    monkeypatch.delenv("BEAUME_STREAM", raising=False)
    monkeypatch.delenv("LUCIE_STREAM", raising=False)
    assert streaming_enabled() is True


def test_streaming_disabled_when_flag_off(monkeypatch):
    monkeypatch.delenv("LUCIE_STREAM", raising=False)
    monkeypatch.setenv("BEAUME_STREAM", "0")
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
    """BEAUME_STREAM=0 → fallback sur run() — on yield 1 seul PipelineResponse."""
    monkeypatch.delenv("LUCIE_STREAM", raising=False)
    monkeypatch.setenv("BEAUME_STREAM", "0")
    fake = PipelineResponse(answer="final", mode="analysis")

    with patch.object(pipeline, "run", new=AsyncMock(return_value=fake)):
        async def go():
            events = []
            async for evt in run_stream("some query"):
                events.append(evt)
            return events

        events = asyncio.run(go())

    assert events == [fake]


class _FakeStreamResponse:
    """Minimal fake d'`httpx.Response` pour mode stream — fournit `aiter_lines`
    et `raise_for_status`, sans contact réseau."""

    def __init__(self, lines: list[str]):
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCtx:
    """Context manager async retourné par `client.stream(...)`."""

    def __init__(self, lines: list[str]):
        self._lines = lines

    async def __aenter__(self) -> _FakeStreamResponse:
        return _FakeStreamResponse(self._lines)

    async def __aexit__(self, *_a) -> None:
        return None


def test_generate_stream_chat_yields_thinking_then_content():
    """`/api/chat` renvoie des chunks {message:{thinking,content}}.
    `generate_stream_chat` doit les exposer taggés via `ChatChunk`."""
    lines = [
        json.dumps({"message": {"role": "assistant", "thinking": "Je réfléchis", "content": ""}, "done": False}),
        json.dumps({"message": {"role": "assistant", "thinking": " encore", "content": ""}, "done": False}),
        json.dumps({"message": {"role": "assistant", "thinking": "", "content": "La réponse"}, "done": False}),
        json.dumps({"message": {"role": "assistant", "thinking": "", "content": " finale."}, "done": False}),
        json.dumps({
            "message": {"role": "assistant", "thinking": "", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 10, "prompt_eval_duration": 50_000_000,
            "eval_count": 4, "eval_duration": 200_000_000,
            "total_duration": 250_000_000,
        }),
    ]

    def fake_stream(method, url, **kwargs):
        assert method == "POST"
        assert url.endswith("/api/chat")
        assert kwargs["json"]["stream"] is True
        return _FakeStreamCtx(lines)

    async def go():
        chunks: list[ChatChunk] = []
        with patch("httpx.AsyncClient.stream", side_effect=fake_stream):
            async for c in ollama_client.generate_stream_chat(model="m", prompt="q"):
                chunks.append(c)
        return chunks

    chunks = asyncio.run(go())
    kinds = [c.kind for c in chunks]
    texts = [c.text for c in chunks]
    assert kinds == ["thinking", "thinking", "content", "content"]
    assert texts == ["Je réfléchis", " encore", "La réponse", " finale."]


def test_generate_stream_chat_passes_system_as_message():
    """Le système est injecté comme message role=system, pas dans options."""
    captured = {}

    def fake_stream(method, url, **kwargs):
        captured["payload"] = kwargs["json"]
        return _FakeStreamCtx([json.dumps({"message": {"content": ""}, "done": True})])

    async def go():
        with patch("httpx.AsyncClient.stream", side_effect=fake_stream):
            async for _ in ollama_client.generate_stream_chat(
                model="m", prompt="q", system="tu es Lucie"
            ):
                pass

    asyncio.run(go())
    msgs = captured["payload"]["messages"]
    assert msgs[0] == {"role": "system", "content": "tu es Lucie"}
    assert msgs[1] == {"role": "user", "content": "q"}


def test_run_stream_n2_streams_chunks_then_final(monkeypatch):
    """Niveau 2 : doit yield des strings (chunks) puis 1 PipelineResponse final."""
    monkeypatch.setenv("BEAUME_STREAM", "1")

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


# ── Cerveau Oiseau short-circuit en streaming (régression v0.5.5) ───────────
# Ces tests verrouillent la parité run() / run_stream() : un article fictif ou
# une query hors-scope doit court-circuiter avant LLM, pas faire 26s comme
# observé en v0.5.5 dans le HUD.

def test_run_stream_article_inexistant_short_circuit():
    """L.1234-999 (article fictif) → refus immédiat, refused=True, <500ms,
    aucun chunk yieldé (court-circuit avant tout LLM)."""
    import time

    async def go():
        t0 = time.perf_counter()
        events = []
        async for evt in run_stream("Que dit l'article L.1234-999 du code du travail ?"):
            events.append(evt)
        return events, (time.perf_counter() - t0) * 1000

    events, dt_ms = asyncio.run(go())

    # Aucun chunk de texte (pas de LLM appelé)
    chunks = [e for e in events if isinstance(e, str)]
    finals = [e for e in events if isinstance(e, PipelineResponse)]
    assert not chunks, f"Aucun chunk attendu, reçu: {chunks!r}"
    assert len(finals) == 1
    assert finals[0].refused is True
    assert finals[0].early_validation_triggered == "article_invalid"
    assert dt_ms < 500, f"Trop lent: {dt_ms:.0f}ms (cible <500ms, idéal <100ms)"


def test_run_stream_out_of_scope_short_circuit():
    """Query hors-scope (fiscal, immobilier, etc.) → refus poli avant LLM."""
    import time

    async def go():
        t0 = time.perf_counter()
        events = []
        async for evt in run_stream("Comment calculer mon impôt sur le revenu ?"):
            events.append(evt)
        return events, (time.perf_counter() - t0) * 1000

    events, dt_ms = asyncio.run(go())

    chunks = [e for e in events if isinstance(e, str)]
    finals = [e for e in events if isinstance(e, PipelineResponse)]
    assert not chunks, f"Aucun chunk attendu, reçu: {chunks!r}"
    assert len(finals) == 1
    assert finals[0].refused is True
    assert finals[0].early_validation_triggered == "out_of_scope"
    assert dt_ms < 500, f"Trop lent: {dt_ms:.0f}ms"


def test_run_stream_imprecise_legal_polite_refusal():
    """Énoncé vague juridique (sans question explicite) → refus court avec
    demande de précision, refused=True, <500ms. Filet de sécurité conservé
    par Sprint 6 P1 pour les énoncés (« Mon contrat… »), tandis que les
    vraies questions in-scope sont désormais routées au LLM."""
    import time

    async def go():
        t0 = time.perf_counter()
        events = []
        # Énoncé sans « ? » et sans mot interrogatif → toujours IMPRECISE_LEGAL.
        # Le filet « pour répondre précisément… » se déclenche encore ici.
        async for evt in run_stream("Mon contrat de travail a été rompu."):
            events.append(evt)
        return events, (time.perf_counter() - t0) * 1000

    events, dt_ms = asyncio.run(go())

    chunks = [e for e in events if isinstance(e, str)]
    finals = [e for e in events if isinstance(e, PipelineResponse)]
    assert not chunks
    assert len(finals) == 1
    assert finals[0].refused is True
    assert finals[0].early_validation_triggered == "imprecise_legal"
    # Le message contient une demande de précision exploitable
    assert "précis" in finals[0].answer.lower() or "contexte" in finals[0].answer.lower()
    assert dt_ms < 500, f"Trop lent: {dt_ms:.0f}ms"


def test_run_stream_lic_perso_contextual_refusal():
    """Sprint 6 P1 — Question lic_perso (hors-périmètre v1) → refus EXPLICATIF
    avec subcategory='lic_perso', reason, redirect_to, < 500ms.
    Cf. Rapport Sprint 5 (22 questions in-scope rejetées canned). Cette
    branche transforme les 10 SW-LPER en réponses contextuelles utiles à
    l'avocat (au lieu du canned générique 'Pour répondre précisément...')."""
    import time

    async def go():
        t0 = time.perf_counter()
        events = []
        async for evt in run_stream(
            "Quelle est la différence entre faute simple, faute grave et faute lourde ?"
        ):
            events.append(evt)
        return events, (time.perf_counter() - t0) * 1000

    events, dt_ms = asyncio.run(go())

    chunks = [e for e in events if isinstance(e, str)]
    finals = [e for e in events if isinstance(e, PipelineResponse)]
    assert not chunks, f"Aucun chunk attendu, reçu: {chunks!r}"
    assert len(finals) == 1
    resp = finals[0]
    assert resp.refused is True
    assert resp.early_validation_triggered == "lic_perso_v1"
    assert resp.subcategory == "lic_perso"
    assert resp.reason and "économique" in resp.reason.lower()
    assert resp.redirect_to and len(resp.redirect_to) >= 3
    # La réponse doit citer le périmètre v1 et lister des sujets traités
    assert "lic" in resp.answer.lower()
    assert "L.1233-3" in resp.answer or "L.1234-9" in resp.answer
    assert dt_ms < 500, f"Trop lent: {dt_ms:.0f}ms"
