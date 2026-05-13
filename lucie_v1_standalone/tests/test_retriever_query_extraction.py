"""Tests unitaires pour ``retriever._extract_query_or_raw`` — Sprint 6 P2d-B.

POURQUOI : ``pipeline.py:692-695`` emballe la query utilisateur dans un JSON
wrapper ``{"type_document": "requete", "query": "..."}`` avant de la passer
au retriever. Si on tokenise le JSON brut pour BM25/FTS5, les tokens
parasites ``type_document``, ``requete``, ``query`` écrasent la pertinence
des vrais termes (mesuré : SW-LECO-006 ramène L.1233-24-4/R.1233-18 AVEC
wrapper, mais L.1233-61/L.1233-63 SANS wrapper, alors que ces derniers sont
les articles cibles attendus par le benchmark).

``_extract_query_or_raw`` doit :
1. Extraire ``query`` du dict si présent et non vide.
2. Renvoyer l'entrée inchangée sinon (fallback non régressif sur texte brut,
   dict sans clé ``query``, JSON invalide, etc.).
"""

from __future__ import annotations

import json

from lucie_v1_standalone.retriever import _extract_query_or_raw


def test_extract_query_from_pipeline_wrapper_dict() -> None:
    """Le wrapper niveau 2 (search) → extraction de ``query``."""
    wrapper = json.dumps(
        {
            "type_document": "requete",
            "query": "Comment fonctionne le PSE ?",
        },
        ensure_ascii=False,
    )
    assert _extract_query_or_raw(wrapper) == "Comment fonctionne le PSE ?"


def test_extract_query_preserves_accents_and_unicode() -> None:
    """Pas de re-encodage cassant : la query revient identique."""
    q = "Quels critères d'ordre pour les licenciements économiques ?"
    wrapper = json.dumps({"type_document": "requete", "query": q}, ensure_ascii=False)
    assert _extract_query_or_raw(wrapper) == q


def test_extract_fallback_on_non_json_string() -> None:
    """Texte brut (lecteur direct, tests, etc.) → renvoyé inchangé."""
    raw = "Quels sont les délais de préavis ?"
    assert _extract_query_or_raw(raw) == raw


def test_extract_fallback_on_dict_without_query_key() -> None:
    """JSON dict sans clé ``query`` (faits_json du Lecteur) → renvoyé inchangé."""
    faits = json.dumps(
        {"motifs": ["difficultés économiques"], "salariés": 12},
        ensure_ascii=False,
    )
    # Le caller doit voir le JSON original — pas de magie cachée.
    assert _extract_query_or_raw(faits) == faits


def test_extract_fallback_on_empty_query_string() -> None:
    """``query`` vide ou whitespace → renvoie le JSON original (pas de query utile)."""
    wrapper_empty = json.dumps({"type_document": "requete", "query": ""})
    wrapper_ws = json.dumps({"type_document": "requete", "query": "   "})
    assert _extract_query_or_raw(wrapper_empty) == wrapper_empty
    assert _extract_query_or_raw(wrapper_ws) == wrapper_ws


def test_extract_fallback_on_query_field_not_str() -> None:
    """``query`` non-string (typage incorrect) → renvoie le JSON original."""
    wrapper = json.dumps({"type_document": "requete", "query": 42})
    assert _extract_query_or_raw(wrapper) == wrapper


def test_extract_fallback_on_malformed_json() -> None:
    """JSON malformé → renvoyé inchangé (le BM25 fera son boulot quand même)."""
    malformed = '{"type_document": "requete", "query": "unclosed'
    assert _extract_query_or_raw(malformed) == malformed


def test_extract_fallback_on_json_array() -> None:
    """JSON tableau (pas un dict) → renvoyé inchangé."""
    arr = json.dumps(["query", "is", "here"])
    assert _extract_query_or_raw(arr) == arr


def test_extract_fallback_on_empty_string() -> None:
    """Chaîne vide → renvoyée telle quelle (pas de crash)."""
    assert _extract_query_or_raw("") == ""
