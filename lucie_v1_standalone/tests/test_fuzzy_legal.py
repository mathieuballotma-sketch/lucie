"""Tests fuzzy matching sur mots-clés juridiques.

Couvre :
  1. Fautes d'orthographe courantes → boost (« licensiment », « liscenciement »)
  2. Pas de faux positifs sur mots proches (« référent » vs « référé »)
  3. Tokens < 5 chars ignorés (filtre anti-ambiguïté)
  4. Query vide ou sans mot juridique → False
  5. Intégration : classify("licensiment légal ?") → IMPRECISE_LEGAL (pas SMALL_TALK)
  6. Stems exacts matchent bien (ratio=1.0 passe les filtres)
  7. Perf : < 20 ms sur une query normale
"""

from __future__ import annotations

import time

import pytest

from lucie_v1_standalone.dialogue.fuzzy_legal import fuzzy_legal_boost
from lucie_v1_standalone.dialogue.intent_classifier import Intent, classify


def test_licensiment_matches_licenciement():
    """Faute courante : 'licensiment' (un 'i' manquant)."""
    assert fuzzy_legal_boost("Ce licensiment est il legal ?") is True


def test_liscenciement_matches_licenciement():
    """Faute courante : 'liscenciement' (lettres inversées)."""
    assert fuzzy_legal_boost("liscenciement pour motif economique") is True


def test_referent_does_not_match_refere():
    """« référent » (ressources humaines) ne doit PAS matcher « référé » (procédure)."""
    # Le stem dans notre liste est "requete" (pas "refere"), donc "referent"
    # ne devrait rien matcher — mais on vérifie aussi qu'on ne matche pas par
    # erreur un autre stem proche.
    assert fuzzy_legal_boost("Qui est le référent RH ?") is False


def test_short_tokens_ignored():
    """Tokens < 5 chars ne déclenchent pas la comparaison fuzzy."""
    # "licen" (5 chars exactement, passe le filtre) — mais ratio trop bas
    # face à "licenciement" (12 chars, diff=7).
    # En revanche "lic" (3 chars) est ignoré.
    assert fuzzy_legal_boost("lic et emp") is False


def test_empty_or_non_legal_query():
    assert fuzzy_legal_boost("") is False
    assert fuzzy_legal_boost("   ") is False
    assert fuzzy_legal_boost("Quelle heure est-il ?") is False
    assert fuzzy_legal_boost("Je voudrais une tarte aux pommes") is False


def test_exact_stem_also_matches():
    """Un stem exact ('licenciement') doit aussi passer."""
    assert fuzzy_legal_boost("licenciement economique") is True


def test_classify_integration_with_typo():
    """classify('licensiment legal ?') doit désormais être IMPRECISE_LEGAL."""
    result = classify("Ce licensiment est il legal ?")
    assert result in (Intent.IMPRECISE_LEGAL, Intent.PRECISE_LEGAL), (
        f"attendu IMPRECISE/PRECISE_LEGAL, got {result}"
    )


def test_classify_unchanged_for_queries_already_matched():
    """La regex stricte reste prioritaire — pas d'impact sur queries OK."""
    # Query déjà matchée par _LEGAL_KEYWORD_RE → reste IMPRECISE_LEGAL
    assert classify("indemnité de licenciement") == Intent.IMPRECISE_LEGAL
    # Small talk pur ne doit PAS être boosté
    assert classify("Bonjour") == Intent.SMALL_TALK


def test_fuzzy_perf_under_20ms():
    """Le fuzzy doit rester largement sous 20 ms sur une query normale."""
    query = "Ce licensiment pour motif economique est-il valable ?"
    t0 = time.perf_counter()
    for _ in range(100):
        fuzzy_legal_boost(query)
    elapsed_ms = (time.perf_counter() - t0) * 1000 / 100
    assert elapsed_ms < 20, f"fuzzy trop lent : {elapsed_ms:.2f} ms / call"
