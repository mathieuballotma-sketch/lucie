"""Tests Swiss watch — règle 5 : verifier_score surfacé dans PipelineResponse.

Ces tests valident que le score de fiabilité du Vérificateur (et les counts
citations OK/invalid) est bien propagé jusqu'à la PipelineResponse, pour
que le HUD puisse afficher le badge couleur sous chaque réponse.

Sans ces tests, le score restait calculé backend mais perdu — l'avocat ne
voyait que le disclaimer texte au format markdown, pas un signal visuel
sobre comme demandé par la règle "élégance silencieuse".
"""

from __future__ import annotations

import json

import pytest

from lucie_v1_standalone.pipeline import (
    PipelineResponse,
    _VERIFICATION_META,
    _format_final,
)


# ─── PipelineResponse — nouveaux champs Swiss watch ──────────────────────────


def test_pipeline_response_has_swiss_watch_fields() -> None:
    """PipelineResponse expose verifier_score, citations_ok, citations_invalid, verdict."""
    r = PipelineResponse(answer="test")
    assert r.verifier_score == 0.0
    assert r.citations_ok == 0
    assert r.citations_invalid == 0
    assert r.verdict is None


def test_pipeline_response_swiss_watch_fields_set_explicitly() -> None:
    r = PipelineResponse(
        answer="test",
        verifier_score=0.8,
        citations_ok=2,
        citations_invalid=1,
        verdict="CORRIGÉ",
    )
    assert r.verifier_score == 0.8
    assert r.citations_ok == 2
    assert r.citations_invalid == 1
    assert r.verdict == "CORRIGÉ"


# ─── _format_final — propagation du metadata ─────────────────────────────────


def _make_verification(score: float, ok: int, invalid: int, verdict: str) -> str:
    return json.dumps(
        {
            "citations_verifiees": [{"reference": f"L.{i}"} for i in range(ok)],
            "citations_invalides": [{"reference": f"X.{i}"} for i in range(invalid)],
            "note_corrigee": "Note finale.",
            "score_fiabilite": score,
            "verdict": verdict,
        },
        ensure_ascii=False,
    )


def test_format_final_sets_meta_for_validated_response() -> None:
    _VERIFICATION_META.set(None)
    verification_json = _make_verification(score=1.0, ok=3, invalid=0, verdict="VALIDÉ")
    out = _format_final("Note brute.", verification_json, verbose=False)
    meta = _VERIFICATION_META.get()
    assert meta is not None
    assert meta["score"] == 1.0
    assert meta["citations_ok"] == 3
    assert meta["citations_invalid"] == 0
    assert meta["verdict"] == "VALIDÉ"
    # Le disclaimer mentionne désormais Beaume v1, pas Lucie V1
    assert "Beaume v1" in out
    assert "Lucie V1" not in out


def test_format_final_meta_when_corrige() -> None:
    _VERIFICATION_META.set(None)
    verification_json = _make_verification(score=0.67, ok=2, invalid=1, verdict="CORRIGÉ")
    _format_final("Note brute.", verification_json, verbose=False)
    meta = _VERIFICATION_META.get()
    assert meta is not None
    assert meta["citations_ok"] == 2
    assert meta["citations_invalid"] == 1
    # citations_ok + citations_invalid == n_total extrait par le Vérificateur
    assert meta["citations_ok"] + meta["citations_invalid"] == 3
    assert meta["verdict"] == "CORRIGÉ"


def test_format_final_meta_on_invalid_json() -> None:
    """Si le verificateur renvoie un JSON malformé, on score à 0 et on
    bascule en verdict ERREUR VÉRIFICATION (pas de crash silencieux)."""
    _VERIFICATION_META.set(None)
    _format_final("Note brute.", "{not valid json", verbose=False)
    meta = _VERIFICATION_META.get()
    assert meta is not None
    assert meta["score"] == 0.0
    assert meta["verdict"] == "ERREUR VÉRIFICATION"


def test_format_final_meta_zero_citations_score_one() -> None:
    """KI-003 documenté : 0 citation extraite → score=1.0 vacuously true.
    Le HUD doit cacher le badge dans ce cas (test côté UI)."""
    _VERIFICATION_META.set(None)
    verification_json = _make_verification(score=1.0, ok=0, invalid=0, verdict="VALIDÉ")
    _format_final("Note brute sans citation.", verification_json, verbose=False)
    meta = _VERIFICATION_META.get()
    assert meta is not None
    assert meta["citations_ok"] + meta["citations_invalid"] == 0
    # score=1.0 mais nb_total=0 → la règle UI doit cacher le badge.


# ─── Cohérence : counts ne sont jamais incohérents avec score ───────────────


@pytest.mark.parametrize(
    "score,ok,invalid",
    [
        (1.0, 5, 0),
        (0.5, 1, 1),
        (0.0, 0, 3),
        (0.75, 3, 1),
    ],
)
def test_format_final_counts_consistent(score: float, ok: int, invalid: int) -> None:
    _VERIFICATION_META.set(None)
    verification_json = _make_verification(
        score=score, ok=ok, invalid=invalid, verdict="VALIDÉ"
    )
    _format_final("Note.", verification_json, verbose=False)
    meta = _VERIFICATION_META.get()
    assert meta is not None
    assert meta["citations_ok"] == ok
    assert meta["citations_invalid"] == invalid
