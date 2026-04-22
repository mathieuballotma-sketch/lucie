"""Tests Phase A — Cerveau Oiseaux.

Trois surfaces testées :

1. Early validation article (pipeline.run) — refus déterministe <1s quand
   un article cité n'est reconnu par aucun résolveur de la chaîne.
2. Early out-of-scope (pipeline.run) — refus poli + redirection quand la
   query évoque un domaine hors Droit Social.
3. Vérificateur 100 % déterministe — aucun appel LLM, suppression
   regex des citations hallucinées, verdict VALIDÉ/CORRIGÉ.

Tous les tests qui invoquent le pipeline complet monkeypatch `_run_pipeline`
pour ne jamais toucher Ollama réel. Les tests Vérificateur monkeypatch
`ollama_client.generate` défensivement pour prouver que cette voie est morte.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

import lucie_v1_standalone.pipeline as pipeline
import lucie_v1_standalone.verificateur as verificateur
from lucie_v1_standalone import ollama_client
from lucie_v1_standalone.dialogue.article_validator import (
    WhitelistCtResolver,
    validate_article_refs,
)
from lucie_v1_standalone.perf.events import bind_event_queue, drain_nowait


# ─── 1. Early validation article ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_article_inexistant_L1234_999_refus_rapide(monkeypatch):
    """Article L.1234-999 non whitelisté → refus déterministe <1s, aucun LLM."""
    mock_fn = AsyncMock(return_value="# Ne devrait PAS être appelé")
    monkeypatch.setattr(pipeline, "_run_pipeline", mock_fn)

    t0 = time.perf_counter()
    response = await pipeline.run("Que dit l'article L.1234-999 ?")
    elapsed = time.perf_counter() - t0

    assert elapsed < 1.0, f"refus trop lent : {elapsed*1000:.0f}ms"
    assert response.refused is True
    assert response.early_validation_triggered == "article_invalid"
    assert "L.1234-999" in response.answer
    assert response.validation_details.get("codes") == ["L.1234-999"]
    assert "whitelist-ct" in response.validation_details.get("resolvers", [])
    mock_fn.assert_not_called()


@pytest.mark.asyncio
async def test_article_whitelist_L1233_3_pipeline_continue(monkeypatch):
    """L.1233-3 est whitelisté → pipeline continue (pas de refus early)."""
    mock_fn = AsyncMock(return_value="# Analyse L.1233-3\n\nReclassement…")
    monkeypatch.setattr(pipeline, "_run_pipeline", mock_fn)

    response = await pipeline.run("Que dit L.1233-3 sur le reclassement ?")

    assert response.refused is False
    assert response.early_validation_triggered is None
    mock_fn.assert_called_once()


def test_article_inconnu_sans_db_retourne_refus_whitelist():
    """Via `WhitelistCtResolver` seul : L.9999-9 doit être refusé."""
    chain = [WhitelistCtResolver()]
    refus = validate_article_refs("Article L.9999-9 ?", resolver_chain=chain)
    assert refus is not None
    assert "L.9999-9" in refus
    # Sanity : un whitelisté passe
    assert validate_article_refs("Article L.1233-3 ?", resolver_chain=chain) is None


# ─── 2. Early out-of-scope ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_question_fiscale_refus_rapide(monkeypatch):
    """Question fiscale → refus poli <1s, domain=fiscal, 0 LLM."""
    mock_fn = AsyncMock(return_value="# Ne devrait PAS être appelé")
    monkeypatch.setattr(pipeline, "_run_pipeline", mock_fn)

    t0 = time.perf_counter()
    response = await pipeline.run("Quelles sont les niches fiscales pour une SARL ?")
    elapsed = time.perf_counter() - t0

    assert elapsed < 1.0, f"refus trop lent : {elapsed*1000:.0f}ms"
    assert response.refused is True
    assert response.early_validation_triggered == "out_of_scope"
    assert response.validation_details.get("domain") == "fiscal"
    mock_fn.assert_not_called()


@pytest.mark.asyncio
async def test_question_dans_scope_continue(monkeypatch):
    """Question Droit Social standard → pipeline appelé, pas de refus."""
    mock_fn = AsyncMock(return_value="# Préavis standard")
    monkeypatch.setattr(pipeline, "_run_pipeline", mock_fn)

    response = await pipeline.run(
        "Quel est le préavis de licenciement pour 3 ans d'ancienneté ?"
    )

    assert response.refused is False
    assert response.early_validation_triggered is None
    mock_fn.assert_called_once()


@pytest.mark.asyncio
async def test_melange_valide_invalide_refus(monkeypatch):
    """Une ref valide (L.1233-3) + une invalide (L.9999-888) → refus sur
    la première invalide rencontrée, 0 LLM."""
    mock_fn = AsyncMock(return_value="# Ne devrait PAS être appelé")
    monkeypatch.setattr(pipeline, "_run_pipeline", mock_fn)

    response = await pipeline.run("Comparer L.1233-3 et L.9999-888")

    assert response.refused is True
    assert response.early_validation_triggered == "article_invalid"
    assert "L.9999-888" in response.answer
    mock_fn.assert_not_called()


# ─── 3. Émission des events cerveau_oiseau vers le HUD ──────────────────────


@pytest.mark.asyncio
async def test_event_cerveau_oiseau_emis(monkeypatch):
    """Pipeline early refus → event cerveau_oiseau avec hook_name publié
    dans la queue (consommable par le HUD)."""
    monkeypatch.setattr(pipeline, "_run_pipeline", AsyncMock(return_value=""))

    async with bind_event_queue() as queue:
        await pipeline.run("Impôts fonciers sur locations meublées ?")
        events = drain_nowait(queue)

    cerveau = [
        ev for ev in events
        if ev.stage == "cerveau_oiseau" and ev.hook_name == "early_out_of_scope"
    ]
    assert cerveau, f"aucun event cerveau_oiseau/early_out_of_scope ({events!r})"
    ev = cerveau[0]
    assert ev.status == "completed"
    assert ev.details.get("domain") == "fiscal"
    assert ev.duration_ms >= 0


# ─── 4. Vérificateur déterministe ───────────────────────────────────────────


_SOURCES_JSON = json.dumps(
    {
        "sources": [
            {"id": "L1233-3", "extrait": "Reclassement…"},
            {"id": "L1234-1", "extrait": "Préavis…"},
            {"id": "L1232-2", "extrait": "Lettre de licenciement…"},
        ],
        "jurisprudences": [],
    }
)


@pytest.mark.asyncio
async def test_verificateur_3_citations_valides_deterministe():
    """3 citations toutes présentes dans les sources → VALIDÉ, <100 ms."""
    note = (
        "# Analyse\n\n"
        "Le reclassement [REF: L1233-3] s'impose avant tout licenciement "
        "économique, conformément à [REF: L1232-2]. "
        "Le préavis est fixé par [REF: L1234-1]."
    )

    t0 = time.perf_counter()
    raw = await verificateur.handle(note, _SOURCES_JSON)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    payload = json.loads(raw)
    assert payload["verdict"] == "VALIDÉ"
    assert payload["score_fiabilite"] == 1.0
    assert len(payload["citations_verifiees"]) == 3
    assert payload["citations_invalides"] == []
    assert elapsed_ms < 100, f"trop lent : {elapsed_ms:.1f}ms"


@pytest.mark.asyncio
async def test_verificateur_1_hallucinee_retiree():
    """1 citation hallucinée → verdict CORRIGÉ, [REF: L9999-X] supprimé de
    la note corrigée, les deux formats ([REF: xxx] et [xxx]) sont couverts."""
    note = (
        "# Analyse\n\n"
        "Le reclassement [REF: L1233-3] s'impose. "
        "L'article [L9999-X] précise toutefois... "
        "Voir aussi [REF: L1234-1]."
    )

    raw = await verificateur.handle(note, _SOURCES_JSON)
    payload = json.loads(raw)

    assert payload["verdict"] == "CORRIGÉ"
    assert 0.5 <= payload["score_fiabilite"] < 1.0
    refs_invalides = [c["reference"] for c in payload["citations_invalides"]]
    assert "L9999-X" in refs_invalides

    corrigee = payload["note_corrigee"]
    assert "[L9999-X]" not in corrigee
    assert "[REF: L9999-X]" not in corrigee
    # Les citations valides demeurent.
    assert "[REF: L1233-3]" in corrigee
    assert "[REF: L1234-1]" in corrigee


@pytest.mark.asyncio
async def test_verificateur_aucun_appel_llm(monkeypatch):
    """Preuve que le Vérificateur n'appelle JAMAIS ollama_client.generate,
    même sur des citations hallucinées (ancien chemin LLM supprimé)."""
    call_count = {"n": 0}

    async def _fail_if_called(*_args, **_kwargs):
        call_count["n"] += 1
        raise AssertionError("ollama_client.generate appelé — LLM non supprimé !")

    monkeypatch.setattr(ollama_client, "generate", _fail_if_called)

    note_avec_hallucination = (
        "Analyse [REF: L1233-3] et [REF: L9999-999]."
    )
    raw = await verificateur.handle(note_avec_hallucination, _SOURCES_JSON)
    payload = json.loads(raw)

    assert call_count["n"] == 0
    assert payload["verdict"] == "CORRIGÉ"
    assert any(
        c["reference"] == "L9999-999" for c in payload["citations_invalides"]
    )
