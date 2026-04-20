"""
Tests du branchement Bloc I dans le pipeline — IntentClassifier + SmallTalkHandler.

Couverture :
  - SMALL_TALK : bypass pipeline, zéro LLM, verifier_score=1.0
  - PRECISE_LEGAL : fallthrough pipeline standard, mode="analysis"
  - EXPLICIT_ORDER : fallthrough pipeline, mode="action"
  - IMPRECISE_LEGAL : fallthrough pipeline, mode="analysis"
  - Edge cases : vide, caractères spéciaux, langue anglaise

Lancer avec :
    python -m pytest lucie_v1_standalone/tests/test_pipeline_bloc_i_wired.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lucie_v1_standalone.pipeline as pipeline
from lucie_v1_standalone.pipeline import PipelineResponse


# ─── Catégorie A : SMALL_TALK (0 LLM — toujours verts) ───────────────────────

@pytest.mark.asyncio
async def test_small_talk_bypasses_pipeline():
    response = await pipeline.run("Bonjour Lucie")
    assert response.verifier_score == 1.0
    assert ("Bonjour" in response.answer or "Salut" in response.answer
            or "puis-je" in response.answer or "Comment" in response.answer)
    assert response.citations == []
    assert response.disclaimer is None


@pytest.mark.asyncio
async def test_small_talk_identity_query():
    response = await pipeline.run("Qui es-tu ?")
    assert response.verifier_score == 1.0
    assert "Lucie" in response.answer


@pytest.mark.asyncio
async def test_small_talk_farewell():
    response = await pipeline.run("Au revoir")
    assert response.verifier_score == 1.0
    assert response.citations == []


@pytest.mark.asyncio
async def test_small_talk_thanks():
    response = await pipeline.run("Merci")
    assert response.verifier_score == 1.0
    assert response.citations == []


@pytest.mark.asyncio
async def test_small_talk_comment_ca_va():
    response = await pipeline.run("Comment ça va ?")
    assert response.verifier_score == 1.0
    assert response.answer  # non vide


@pytest.mark.asyncio
async def test_small_talk_returns_pipeline_response_type():
    response = await pipeline.run("Bonjour")
    assert isinstance(response, PipelineResponse)


@pytest.mark.asyncio
async def test_small_talk_str_repr_returns_answer():
    """__str__ doit retourner answer — compatibilité print() dans __main__.py."""
    response = await pipeline.run("Salut")
    assert str(response) == response.answer


# ─── Catégorie B : LLM paths (mock _run_pipeline) ────────────────────────────

@pytest.mark.asyncio
async def test_precise_legal_goes_to_pipeline(monkeypatch):
    mock_answer = "# Analyse\n\nPréavis selon L.1234-1 : 2 mois.\n\n---\n_Score: 90%_"
    monkeypatch.setattr(pipeline, "_run_pipeline", AsyncMock(return_value=mock_answer))
    response = await pipeline.run("Quel est le délai de préavis selon L.1234-1 ?")
    assert response.mode == "analysis"
    assert "Préavis" in response.answer or "L.1234" in response.answer


@pytest.mark.asyncio
async def test_precise_legal_pipeline_called_once(monkeypatch):
    mock_fn = AsyncMock(return_value="# Réponse juridique")
    monkeypatch.setattr(pipeline, "_run_pipeline", mock_fn)
    await pipeline.run("Quel est le préavis pour 3 ans d'ancienneté selon L.1234-19 ?")
    mock_fn.assert_called_once()


@pytest.mark.asyncio
async def test_explicit_order_triggers_action_mode(monkeypatch):
    mock_answer = "# Mise en demeure\n\nRédaction complète ici."
    monkeypatch.setattr(pipeline, "_run_pipeline", AsyncMock(return_value=mock_answer))
    response = await pipeline.run("Rédige une mise en demeure pour non-paiement")
    assert response.mode == "action"


@pytest.mark.asyncio
async def test_explicit_order_calls_pipeline_once(monkeypatch):
    mock_fn = AsyncMock(return_value="# Analyse du contrat")
    monkeypatch.setattr(pipeline, "_run_pipeline", mock_fn)
    response = await pipeline.run("Analyse ce contrat de travail pour licenciement éco")
    mock_fn.assert_called_once()
    assert response.mode == "action"


@pytest.mark.asyncio
async def test_imprecise_legal_falls_through(monkeypatch):
    mock_answer = "# Réponse\n\nPour licencier quelqu'un économiquement, il faut..."
    monkeypatch.setattr(pipeline, "_run_pipeline", AsyncMock(return_value=mock_answer))
    response = await pipeline.run("Mon client veut licencier quelqu'un")
    assert response is not None
    assert isinstance(response, PipelineResponse)
    assert response.mode == "analysis"


# ─── Catégorie C : Edge cases (0 LLM) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_query_does_not_crash(monkeypatch):
    monkeypatch.setattr(pipeline, "_run_pipeline", AsyncMock(return_value="# Vide"))
    response = await pipeline.run("")
    assert isinstance(response, PipelineResponse)


@pytest.mark.asyncio
async def test_special_chars_small_talk():
    response = await pipeline.run("Bonjour !")
    assert response.verifier_score == 1.0


@pytest.mark.asyncio
async def test_english_hello_small_talk():
    response = await pipeline.run("Hello")
    assert response.verifier_score == 1.0
    assert response.citations == []


@pytest.mark.asyncio
async def test_pipeline_response_has_all_fields():
    response = await pipeline.run("Bonjour")
    assert hasattr(response, "answer")
    assert hasattr(response, "citations")
    assert hasattr(response, "verifier_score")
    assert hasattr(response, "disclaimer")
    assert hasattr(response, "mode")
