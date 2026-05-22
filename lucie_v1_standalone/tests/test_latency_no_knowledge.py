"""Tests Sprint Latence 0.5.1 — Short-circuit "no-knowledge".

Couvre :
  - Quand le Retriever ramène des sources de faible pertinence (top_pertinence
    < seuil), le pipeline DOIT court-circuiter le Rédacteur et renvoyer un
    refus poli en <200ms (avec Ollama mocké).
  - Quand le Retriever ramène 0 sources, idem (court-circuit immédiat).
  - Quand le Retriever ramène des sources pertinentes (top >= seuil), le
    Rédacteur DOIT être appelé normalement (pas de régression sur les bonnes
    questions).
  - La configuration du seuil via env `BEAUME_NO_KNOWLEDGE_MIN_PERTINENCE`.

Contexte : bug 2026-05-22 — la query « Quel est le délai de préavis légal
d'un liscensime » prenait 51s pour finir en « refus poli — couverture KB
insuffisante ». Le LLM Rédacteur était appelé inutilement pendant ~48s avant
que le Vérificateur ne détecte 0 citation valide. Le short-circuit avant
LLM (basé sur la pertinence du Retriever) résout le problème.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, List
from unittest.mock import AsyncMock, patch

import pytest

from lucie_v1_standalone import pipeline
from lucie_v1_standalone.dialogue.intent_classifier import Intent
from lucie_v1_standalone.pipeline import PipelineResponse


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _sources_json(sources: List[dict]) -> str:
    """Construit le JSON renvoyé par retriever.handle()."""
    return json.dumps(
        {"sources": sources, "jurisprudences": [], "non_trouve": []},
        ensure_ascii=False,
    )


def _run_stream_collect(query: str) -> tuple[List[Any], float]:
    """Lance pipeline.run_stream et collecte tous les events. Retourne aussi la latence."""
    t0 = time.perf_counter()

    async def go():
        evts: List[Any] = []
        async for evt in pipeline.run_stream(query):
            evts.append(evt)
        return evts

    evts = asyncio.run(go())
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return evts, elapsed_ms


# ─── A4.1 : short-circuit déclenche quand pertinence faible ──────────────────


def test_short_circuit_on_low_pertinence(monkeypatch):
    """top_pertinence=0.10 < seuil 0.35 → pas d'appel Rédacteur, refus en <200ms."""
    monkeypatch.setenv("BEAUME_STREAM", "1")
    monkeypatch.setenv("BEAUME_NO_KNOWLEDGE_MIN_PERTINENCE", "0.35")
    monkeypatch.delenv("BEAUME_CACHE", raising=False)
    monkeypatch.setenv("BEAUME_CACHE", "0")  # force pas de cache pour reproductibilité

    fake_sources = [
        {"id": "L.9999-1", "titre": "Article marginal", "extrait": "...", "pertinence": 0.10},
    ]
    fake_route = {"level": "search", "intent": "question_juridique", "document": None}
    fake_validate = {"valid": True, "refusal_reason": None}

    redacteur_calls: list = []

    async def fake_redacteur_stream(*args, **kwargs):
        redacteur_calls.append((args, kwargs))
        yield "ne_devrait_pas_etre_appele"

    with patch("lucie_v1_standalone.pipeline.retriever.handle",
               new=AsyncMock(return_value=_sources_json(fake_sources))), \
         patch("lucie_v1_standalone.pipeline.redacteur.handle_stream",
               side_effect=fake_redacteur_stream), \
         patch("lucie_v1_standalone.pipeline.router_route", return_value=fake_route), \
         patch("lucie_v1_standalone.pipeline.router_validate", return_value=fake_validate), \
         patch("lucie_v1_standalone.pipeline.classify_intent",
               return_value=Intent.PRECISE_LEGAL):

        evts, elapsed_ms = _run_stream_collect(
            "Quel est le délai de préavis légal d'un liscensime"
        )

    # Le Rédacteur ne doit PAS avoir été appelé
    assert redacteur_calls == [], (
        f"Le Rédacteur a été appelé alors que le short-circuit aurait dû déclencher "
        f"({len(redacteur_calls)} appels)"
    )

    # La latence doit être très faible (mock ollama → quasi-zéro overhead)
    assert elapsed_ms < 500, f"Latence trop élevée : {elapsed_ms:.1f}ms"

    # La réponse doit contenir le marqueur de refus
    text_chunks = [e for e in evts if isinstance(e, str)]
    full_text = "".join(text_chunks)
    assert "Couverture insuffisante" in full_text, (
        f"Le texte de refus attendu manque dans la réponse :\n{full_text[:300]}"
    )

    # La PipelineResponse finale doit marquer refused=True
    final = [e for e in evts if isinstance(e, PipelineResponse)]
    assert final, "Pas de PipelineResponse finale dans le stream"
    assert final[-1].refused is True
    assert final[-1].early_validation_triggered == "kb_insufficient"


# ─── A4.2 : short-circuit déclenche quand 0 sources ──────────────────────────


def test_short_circuit_on_zero_sources(monkeypatch):
    """0 sources retournées → court-circuit immédiat, pas de LLM."""
    monkeypatch.setenv("BEAUME_STREAM", "1")
    monkeypatch.setenv("BEAUME_CACHE", "0")

    fake_route = {"level": "search", "intent": "question_juridique", "document": None}
    fake_validate = {"valid": True, "refusal_reason": None}

    redacteur_calls: list = []

    async def fake_redacteur_stream(*args, **kwargs):
        redacteur_calls.append((args, kwargs))
        yield "x"

    with patch("lucie_v1_standalone.pipeline.retriever.handle",
               new=AsyncMock(return_value=_sources_json([]))), \
         patch("lucie_v1_standalone.pipeline.redacteur.handle_stream",
               side_effect=fake_redacteur_stream), \
         patch("lucie_v1_standalone.pipeline.router_route", return_value=fake_route), \
         patch("lucie_v1_standalone.pipeline.router_validate", return_value=fake_validate), \
         patch("lucie_v1_standalone.pipeline.classify_intent",
               return_value=Intent.PRECISE_LEGAL):

        evts, elapsed_ms = _run_stream_collect("question_sans_sources_dans_la_kb")

    assert redacteur_calls == []
    assert elapsed_ms < 500
    full_text = "".join(e for e in evts if isinstance(e, str))
    assert "Couverture insuffisante" in full_text


# ─── A4.3 : pas de short-circuit quand pertinence suffisante ─────────────────


def test_no_short_circuit_on_strong_pertinence(monkeypatch):
    """top_pertinence=0.85 >= seuil 0.35 → Rédacteur appelé normalement."""
    monkeypatch.setenv("BEAUME_STREAM", "1")
    monkeypatch.setenv("BEAUME_NO_KNOWLEDGE_MIN_PERTINENCE", "0.35")
    monkeypatch.setenv("BEAUME_CACHE", "0")

    strong_sources = [
        {"id": "L.1233-3", "titre": "Motif éco", "extrait": "...", "pertinence": 0.85},
        {"id": "L.1233-4", "titre": "Recherche reclassement", "extrait": "...", "pertinence": 0.72},
    ]
    fake_route = {"level": "search", "intent": "question_juridique", "document": None}
    fake_validate = {"valid": True, "refusal_reason": None}

    redacteur_calls: list = []

    async def fake_redacteur_stream(*args, **kwargs):
        redacteur_calls.append((args, kwargs))
        yield "Voici la réponse [L.1233-3]"

    async def fake_verif_handle(*args, **kwargs):
        return json.dumps({
            "verdict": "VALIDÉ",
            "citations_ok": 1,
            "citations_invalid": 0,
            "score": 1.0,
        })

    with patch("lucie_v1_standalone.pipeline.retriever.handle",
               new=AsyncMock(return_value=_sources_json(strong_sources))), \
         patch("lucie_v1_standalone.pipeline.redacteur.handle_stream",
               side_effect=fake_redacteur_stream), \
         patch("lucie_v1_standalone.pipeline.verificateur.handle",
               new=AsyncMock(side_effect=fake_verif_handle)), \
         patch("lucie_v1_standalone.pipeline.router_route", return_value=fake_route), \
         patch("lucie_v1_standalone.pipeline.router_validate", return_value=fake_validate), \
         patch("lucie_v1_standalone.pipeline.classify_intent",
               return_value=Intent.PRECISE_LEGAL):

        evts, _ = _run_stream_collect("Quelles conditions licenciement éco ?")

    assert len(redacteur_calls) == 1, (
        f"Rédacteur aurait dû être appelé 1 fois, vu {len(redacteur_calls)}"
    )

    final = [e for e in evts if isinstance(e, PipelineResponse)]
    assert final, "Pas de PipelineResponse finale"
    # Si pas de short-circuit, refused doit être False
    assert final[-1].refused is False


# ─── A4.4 : seuil ajustable via env var ──────────────────────────────────────


def test_threshold_configurable_via_env(monkeypatch):
    """BEAUME_NO_KNOWLEDGE_MIN_PERTINENCE=0.05 → laisse passer pertinence 0.10."""
    monkeypatch.setenv("BEAUME_STREAM", "1")
    monkeypatch.setenv("BEAUME_NO_KNOWLEDGE_MIN_PERTINENCE", "0.05")
    monkeypatch.setenv("BEAUME_CACHE", "0")

    weak_sources = [
        {"id": "L.9999-1", "titre": "marginal", "extrait": "...", "pertinence": 0.10},
    ]
    fake_route = {"level": "search", "intent": "question_juridique", "document": None}
    fake_validate = {"valid": True, "refusal_reason": None}

    redacteur_calls: list = []

    async def fake_redacteur_stream(*args, **kwargs):
        redacteur_calls.append(True)
        yield "OK"

    async def fake_verif_handle(*args, **kwargs):
        return json.dumps({
            "verdict": "VALIDÉ", "citations_ok": 0, "citations_invalid": 0, "score": 0.5,
        })

    with patch("lucie_v1_standalone.pipeline.retriever.handle",
               new=AsyncMock(return_value=_sources_json(weak_sources))), \
         patch("lucie_v1_standalone.pipeline.redacteur.handle_stream",
               side_effect=fake_redacteur_stream), \
         patch("lucie_v1_standalone.pipeline.verificateur.handle",
               new=AsyncMock(side_effect=fake_verif_handle)), \
         patch("lucie_v1_standalone.pipeline.router_route", return_value=fake_route), \
         patch("lucie_v1_standalone.pipeline.router_validate", return_value=fake_validate), \
         patch("lucie_v1_standalone.pipeline.classify_intent",
               return_value=Intent.PRECISE_LEGAL):

        _run_stream_collect("question_avec_source_marginale")

    # Avec un seuil bas à 0.05, la pertinence 0.10 passe → Rédacteur appelé
    assert len(redacteur_calls) == 1, (
        "Avec un seuil bas 0.05, pertinence 0.10 devait passer le short-circuit"
    )


# ─── A4.5 : helper _evaluate_sources_quality (unitaire) ──────────────────────


def test_evaluate_sources_quality_with_sources():
    js = _sources_json([
        {"id": "L.1233-3", "pertinence": 0.85},
        {"id": "L.1233-4", "pertinence": 0.72},
        {"id": "L.1233-5", "pertinence": 0.10},
    ])
    q = pipeline._evaluate_sources_quality(js)
    assert q["nb_sources"] == 3
    assert q["top_pertinence"] == pytest.approx(0.85)
    assert q["top_refs"] == ["L.1233-3", "L.1233-4", "L.1233-5"]


def test_evaluate_sources_quality_empty():
    q = pipeline._evaluate_sources_quality(_sources_json([]))
    assert q["nb_sources"] == 0
    assert q["top_pertinence"] == 0.0
    assert q["top_refs"] == []


def test_evaluate_sources_quality_malformed():
    q = pipeline._evaluate_sources_quality("not-json")
    assert q["nb_sources"] == 0
    assert q["top_pertinence"] == 0.0


def test_evaluate_sources_quality_missing_pertinence_key():
    """Source Légifrance sans champ pertinence → traité comme 0.0 (conservateur)."""
    js = _sources_json([{"id": "L.1233-3", "titre": "X"}])
    q = pipeline._evaluate_sources_quality(js)
    assert q["nb_sources"] == 1
    assert q["top_pertinence"] == 0.0
