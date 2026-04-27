"""Tests R3 — instrumentation TTFT (sprint S1 Speed-Optimizer).

Couvre :
  - ollama_client.generate_stream enregistre `ollama.<model>.ttft` dans
    le bucket courant au 1er chunk de réponse.
  - pipeline.run_stream enregistre `pipeline.ttft` au 1er chunk émis.
  - pipeline.ttft n'est enregistré qu'une seule fois par run.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from lucie_v1_standalone import ollama_client, pipeline
from lucie_v1_standalone.dialogue.intent_classifier import Intent
from lucie_v1_standalone.perf import profile_bucket


# ─── Mock httpx pour tester ollama_client.generate_stream sans serveur ─────


class _FakeStreamResp:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCtx:
    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return _FakeStreamResp(self._lines)

    async def __aexit__(self, *a):
        return False


class _FakeAsyncClient:
    LINES: list = []  # configurée par le test

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, **kw):
        return _FakeStreamCtx(self.LINES)


# ─── R3a — TTFT ollama_client ───────────────────────────────────────────────


def test_ollama_ttft_recorded_in_bucket(monkeypatch):
    """generate_stream doit pousser une step `ollama.<model>.ttft` dans
    le bucket courant dès le 1er chunk non vide."""
    monkeypatch.setenv("LUCIE_PROFILE", "1")
    _FakeAsyncClient.LINES = [
        json.dumps({"response": "Hello"}),
        json.dumps({"response": " world"}),
        json.dumps({"done": True, "eval_count": 2, "eval_duration": 1000000}),
    ]
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", _FakeAsyncClient)

    async def go():
        async with profile_bucket() as bucket:
            chunks = []
            async for c in ollama_client.generate_stream(
                model="gemma4:e4b",
                prompt="hi",
                options={"temperature": 0.3},
            ):
                chunks.append(c)
            return chunks, bucket

    chunks, bucket = asyncio.run(go())
    assert chunks == ["Hello", " world"]
    assert bucket is not None
    ttft_steps = [s for s in bucket.steps if s.name == "ollama.gemma4:e4b.ttft"]
    assert len(ttft_steps) == 1, f"attendu 1 step ttft, vu {len(ttft_steps)}"
    assert ttft_steps[0].duration_ms >= 0


def test_ollama_ttft_only_recorded_once(monkeypatch):
    """Avec plusieurs chunks, la step ttft doit n'être enregistrée qu'une fois."""
    monkeypatch.setenv("LUCIE_PROFILE", "1")
    _FakeAsyncClient.LINES = [
        json.dumps({"response": c}) for c in ["a", "b", "c", "d"]
    ] + [json.dumps({"done": True})]
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", _FakeAsyncClient)

    async def go():
        async with profile_bucket() as bucket:
            async for _ in ollama_client.generate_stream(
                model="gemma4:e4b", prompt="hi"
            ):
                pass
            return bucket

    bucket = asyncio.run(go())
    ttft_steps = [s for s in bucket.steps if s.name.endswith(".ttft")]
    assert len(ttft_steps) == 1


def test_ollama_ttft_not_recorded_when_profiling_off(monkeypatch):
    """Sans LUCIE_PROFILE=1 : aucun bucket actif → no-op silencieux."""
    monkeypatch.delenv("LUCIE_PROFILE", raising=False)
    _FakeAsyncClient.LINES = [
        json.dumps({"response": "x"}),
        json.dumps({"done": True}),
    ]
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", _FakeAsyncClient)

    async def go():
        async with profile_bucket() as bucket:
            async for _ in ollama_client.generate_stream(
                model="gemma4:e4b", prompt="hi"
            ):
                pass
            return bucket

    bucket = asyncio.run(go())
    # bucket est None quand profilage désactivé.
    assert bucket is None


# ─── R3b — TTFT pipeline ────────────────────────────────────────────────────


def test_pipeline_ttft_recorded_n1(monkeypatch):
    """run_stream sur un chemin N1 (level=direct) doit enregistrer
    `pipeline.ttft` au 1er chunk émis."""
    monkeypatch.setenv("LUCIE_STREAM", "1")
    monkeypatch.setenv("LUCIE_PROFILE", "1")

    async def fake_stream(**kwargs):
        for c in ["Bon", "jour."]:
            yield c

    fake_route = {"level": "direct", "intent": "question_generale", "document": None}
    fake_validate = {"valid": True, "refusal_reason": None}

    with patch.object(ollama_client, "generate_stream", side_effect=fake_stream), \
         patch("lucie_v1_standalone.pipeline.router_route", return_value=fake_route), \
         patch("lucie_v1_standalone.pipeline.router_validate", return_value=fake_validate), \
         patch("lucie_v1_standalone.pipeline.classify_intent",
               return_value=Intent.IMPRECISE_LEGAL):

        async def go():
            async with profile_bucket() as bucket:
                async for _ in pipeline.run_stream("anything"):
                    pass
                return bucket

        bucket = asyncio.run(go())

    assert bucket is not None
    pipeline_steps = [s for s in bucket.steps if s.name == "pipeline.ttft"]
    assert len(pipeline_steps) == 1, f"attendu 1 step pipeline.ttft, vu {len(pipeline_steps)}"
    assert pipeline_steps[0].duration_ms >= 0


def test_pipeline_ttft_only_recorded_once_with_many_chunks(monkeypatch):
    """Plusieurs chunks → 1 seule entrée pipeline.ttft."""
    monkeypatch.setenv("LUCIE_STREAM", "1")
    monkeypatch.setenv("LUCIE_PROFILE", "1")

    async def fake_stream(**kwargs):
        for c in ["a", "b", "c", "d", "e"]:
            yield c

    fake_route = {"level": "direct", "intent": "question_generale", "document": None}
    fake_validate = {"valid": True, "refusal_reason": None}

    with patch.object(ollama_client, "generate_stream", side_effect=fake_stream), \
         patch("lucie_v1_standalone.pipeline.router_route", return_value=fake_route), \
         patch("lucie_v1_standalone.pipeline.router_validate", return_value=fake_validate), \
         patch("lucie_v1_standalone.pipeline.classify_intent",
               return_value=Intent.IMPRECISE_LEGAL):

        async def go():
            async with profile_bucket() as bucket:
                async for _ in pipeline.run_stream("anything"):
                    pass
                return bucket

        bucket = asyncio.run(go())

    pipeline_steps = [s for s in bucket.steps if s.name == "pipeline.ttft"]
    assert len(pipeline_steps) == 1


def test_pipeline_ttft_not_recorded_for_small_talk(monkeypatch):
    """SMALL_TALK ne stream pas (early return PipelineResponse) → pas de
    pipeline.ttft puisque pas de chunk yieldé."""
    monkeypatch.setenv("LUCIE_STREAM", "1")
    monkeypatch.setenv("LUCIE_PROFILE", "1")

    async def go():
        async with profile_bucket() as bucket:
            async for _ in pipeline.run_stream("bonjour"):
                pass
            return bucket

    bucket = asyncio.run(go())
    assert bucket is not None
    pipeline_steps = [s for s in bucket.steps if s.name == "pipeline.ttft"]
    assert pipeline_steps == [], "SMALL_TALK ne doit pas émettre pipeline.ttft"
