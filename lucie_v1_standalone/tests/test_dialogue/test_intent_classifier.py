"""
Tests — IntentClassifier (20 tests, 5 par mode).
"""

from __future__ import annotations

import pytest

from lucie_v1_standalone.dialogue.intent_classifier import Intent, classify


# ── SMALL_TALK (5 cas) ────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "Bonjour",
    "Salut !",
    "Merci",
    "Au revoir",
    "Qui es-tu ?",
])
def test_small_talk(query: str) -> None:
    assert classify(query) == Intent.SMALL_TALK, f"Attendu SMALL_TALK pour : {query!r}"


# ── IMPRECISE_LEGAL (5 cas) ───────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "J'ai été licencié.",
    "Mon contrat de travail a été rompu.",
    "Quels sont mes droits de salarié ?",
    "Mon employeur veut me licencier.",
    "J'ai reçu une lettre de mon employeur.",
])
def test_imprecise_legal(query: str) -> None:
    assert classify(query) == Intent.IMPRECISE_LEGAL, f"Attendu IMPRECISE_LEGAL pour : {query!r}"


# ── PRECISE_LEGAL (5 cas) ────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "Mon préavis de licenciement dure 3 mois avec 5 ans d'ancienneté ?",
    "L.1233-30 impose quels délais de consultation CSE pour un licenciement collectif ?",
    "Mon indemnité légale de licenciement avec 8 ans d'ancienneté et 3200 € brut ?",
    "Le CSE a-t-il été consulté conformément à L.1233-30 pour ce PSE ?",
    "Cass. soc. 2021 sur la sauvegarde de la compétitivité comme motif économique valide ?",
])
def test_precise_legal(query: str) -> None:
    assert classify(query) == Intent.PRECISE_LEGAL, f"Attendu PRECISE_LEGAL pour : {query!r}"


# ── EXPLICIT_ORDER (5 cas) ────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "Rédige une lettre de contestation de mon licenciement.",
    "Analyse ce plan de sauvegarde de l'emploi.",
    "Compare les indemnités légales et conventionnelles pour mon cas.",
    "Résume les étapes de la procédure de licenciement collectif.",
    "Vérifie si mon employeur a respecté l'article L.1233-30.",
])
def test_explicit_order(query: str) -> None:
    assert classify(query) == Intent.EXPLICIT_ORDER, f"Attendu EXPLICIT_ORDER pour : {query!r}"
