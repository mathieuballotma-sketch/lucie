"""Tests du handler OUT_OF_SCOPE (`dialogue/out_of_scope.py`).

Couvre :
  1. Détection fiscal / immobilier / pénal / famille → refus avec redirection
  2. Priority override : ref article CT → None (pas de refus)
  3. Priority override : mention « code du travail » → None
  4. Query vide ou whitespace → None
  5. Accents et majuscules normalisés
  6. Hot-reload après clear_out_of_scope_cache()
"""

from __future__ import annotations

import pytest

from lucie_v1_standalone.dialogue.out_of_scope import (
    OutOfScopeMatch,
    clear_out_of_scope_cache,
    detect_out_of_scope,
)


def setup_function(func):
    """Invalide les caches avant chaque test pour isolation."""
    clear_out_of_scope_cache()


def test_fiscal_question_is_detected():
    q = "Avis fiscal sur indemnité transactionnelle, impact TVA"
    result = detect_out_of_scope(q)
    assert isinstance(result, OutOfScopeMatch)
    assert result.domain == "fiscal"
    assert "droit fiscal" in result.redirection.lower()


def test_immobilier_question_is_detected():
    q = "Mon client a un litige sur un bail commercial avec son propriétaire"
    result = detect_out_of_scope(q)
    assert result is not None
    assert result.domain == "immobilier"


def test_penal_question_is_detected():
    q = "Comment préparer la comparution immédiate de mon client ?"
    result = detect_out_of_scope(q)
    assert result is not None
    assert result.domain == "penal"


def test_famille_question_is_detected():
    q = "Procédure de divorce pour faute, quels éléments de preuve ?"
    result = detect_out_of_scope(q)
    assert result is not None
    assert result.domain == "famille"


def test_priority_override_article_ct_beats_fiscal():
    """« L.1234-5 impact fiscal » doit passer (priorité CT)."""
    q = "Quel est l'impact fiscal de l'article L.1234-5 du Code du travail ?"
    result = detect_out_of_scope(q)
    assert result is None, f"attendu None mais got {result}"


def test_priority_override_code_du_travail_mention():
    q = "Licenciement économique, référence au code du travail et à la fiscalité"
    result = detect_out_of_scope(q)
    assert result is None


def test_priority_override_licenciement_keyword():
    q = "Licenciement d'un salarié avec indemnité, aspect fiscal à considérer"
    result = detect_out_of_scope(q)
    assert result is None


def test_empty_query_returns_none():
    assert detect_out_of_scope("") is None
    assert detect_out_of_scope("   ") is None


def test_accents_and_case_normalized():
    """FISCALITÉ majuscules + accents → doit matcher comme fiscal."""
    q = "Question sur la FISCALITÉ des indemnités"
    result = detect_out_of_scope(q)
    assert result is not None
    assert result.domain == "fiscal"


def test_legitimate_droit_social_question_is_not_rejected():
    q = "Quelle est la durée de préavis légale après 5 ans d'ancienneté ?"
    result = detect_out_of_scope(q)
    assert result is None


def test_clear_cache_allows_reload():
    """clear_out_of_scope_cache() invalide les caches."""
    # Premier appel remplit les caches
    detect_out_of_scope("question neutre")
    clear_out_of_scope_cache()
    # Deuxième appel doit re-charger (on vérifie juste qu'il ne lève pas)
    result = detect_out_of_scope("autre question neutre")
    assert result is None
