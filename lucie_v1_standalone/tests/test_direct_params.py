"""Tests R1 — DIRECT_PARAMS calé sur le sweep `predict_200` (sprint S1).

Le sweep 2026-04-25 (Phase 2, 18 prompts sur gemma4:e4b) a classé
`predict_200` n°1 avec un TTFT moyen de 1478 ms. Ce module verrouille
les valeurs gagnantes pour éviter une régression silencieuse, et
vérifie que le pipeline N1 (level=direct) les transmet bien à Ollama.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from lucie_v1_standalone.config import DIRECT_PARAMS, SPEED_MODEL
from lucie_v1_standalone.dialogue.intent_classifier import Intent


def test_direct_params_sentinel():
    """Sentinel anti-régression silencieuse sur les valeurs sweep `predict_200`."""
    assert DIRECT_PARAMS["model"] == SPEED_MODEL
    assert DIRECT_PARAMS["num_predict"] == 200
    assert DIRECT_PARAMS["num_ctx"] == 4096
    assert DIRECT_PARAMS["top_k"] == 20
    assert DIRECT_PARAMS["repeat_penalty"] == 1.1
    assert DIRECT_PARAMS["temperature"] == 0.3
    assert DIRECT_PARAMS["top_p"] == 0.9
    assert DIRECT_PARAMS["num_batch"] == 512
    assert DIRECT_PARAMS["num_gpu"] == 99


def test_direct_params_passes_sweep_options_to_ollama_in_n1_path(monkeypatch):
    """Le chemin N1 (level=direct) doit transmettre top_k / repeat_penalty /
    num_predict / num_ctx à ollama_client.generate_stream — sinon le sweep
    n'a aucun effet runtime."""
    monkeypatch.setenv("BEAUME_STREAM", "1")
    captured: dict = {}

    async def fake_stream(**kwargs):
        captured.update(kwargs)
        for c in ["Bonjour ", "Maître."]:
            yield c

    fake_route = {"level": "direct", "intent": "question_generale", "document": None}
    fake_validate = {"valid": True, "refusal_reason": None}

    from lucie_v1_standalone import ollama_client, pipeline

    with patch.object(ollama_client, "generate_stream", side_effect=fake_stream), \
         patch("lucie_v1_standalone.pipeline.router_route", return_value=fake_route), \
         patch("lucie_v1_standalone.pipeline.router_validate", return_value=fake_validate), \
         patch("lucie_v1_standalone.pipeline.classify_intent",
               return_value=Intent.PRECISE_LEGAL):

        async def go():
            events = []
            async for ev in pipeline.run_stream("c'est quoi ce truc"):
                events.append(ev)
            return events

        events = asyncio.run(go())

    assert captured.get("model") == SPEED_MODEL
    options = captured.get("options", {})
    assert options.get("top_k") == 20, "top_k=20 manquant — sweep non appliqué"
    assert options.get("repeat_penalty") == 1.1
    assert options.get("num_predict") == 200
    assert options.get("num_ctx") == 4096
    # `model` doit être retiré du dict options (pipeline.py:789).
    assert "model" not in options


def test_direct_params_n1_smoke_returns_full_streamed_text(monkeypatch):
    """Smoke : un stream de 250 chars sur N1 ne doit pas être tronqué côté
    pipeline. Vérifie qu'on n'a pas cassé le flow de chunks suite au
    changement num_predict 512 → 200 (cap appliqué côté Ollama uniquement)."""
    monkeypatch.setenv("BEAUME_STREAM", "1")
    sample = "x" * 250

    async def fake_stream(**kwargs):
        # Un seul chunk qui simule une réponse "longue" — le pipeline
        # ne doit appliquer aucun cap supplémentaire au-dessus d'Ollama.
        yield sample

    fake_route = {"level": "direct", "intent": "question_generale", "document": None}
    fake_validate = {"valid": True, "refusal_reason": None}

    from lucie_v1_standalone import ollama_client, pipeline
    from lucie_v1_standalone.pipeline import PipelineResponse

    with patch.object(ollama_client, "generate_stream", side_effect=fake_stream), \
         patch("lucie_v1_standalone.pipeline.router_route", return_value=fake_route), \
         patch("lucie_v1_standalone.pipeline.router_validate", return_value=fake_validate), \
         patch("lucie_v1_standalone.pipeline.classify_intent",
               return_value=Intent.PRECISE_LEGAL):

        async def go():
            events = []
            async for ev in pipeline.run_stream("question quelconque"):
                events.append(ev)
            return events

        events = asyncio.run(go())

    chunks = [e for e in events if isinstance(e, str)]
    finals = [e for e in events if isinstance(e, PipelineResponse)]
    assert "".join(chunks) == sample
    assert len(finals) == 1
    assert finals[0].answer == sample
