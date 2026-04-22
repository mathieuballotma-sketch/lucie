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


# ── Matrice Mathieu 2026-04-22 — fix routing v0.4.2 ──────────────────────────
# Avant fix : questions factuelles classées SMALL_TALK → réponse générique
#            « Je me spécialise en droit du licenciement économique. »
# Après fix : les 9 questions juridiques doivent router vers le pipeline
#            (EXPLICIT_ORDER ou IMPRECISE_LEGAL), seul "Bonjour" → SMALL_TALK.

@pytest.mark.parametrize("query,expected", [
    ("Quelle est la durée légale du préavis ?", Intent.IMPRECISE_LEGAL),
    ("L.1233-3 ?", Intent.IMPRECISE_LEGAL),
    ("Peux-tu m'expliquer le licenciement économique ?", Intent.EXPLICIT_ORDER),
    ("J'ai besoin d'une note sur le préavis", Intent.IMPRECISE_LEGAL),
    ("Donne-moi les motifs de licenciement économique", Intent.IMPRECISE_LEGAL),
    ("Dans combien de temps peut-on contester un licenciement ?", Intent.IMPRECISE_LEGAL),
    ("Quelle indemnité pour 12 ans d'ancienneté ?", Intent.IMPRECISE_LEGAL),
    ("Que dit L.1233-3 ?", Intent.IMPRECISE_LEGAL),
    ("Recherche l'article L.1234-1", Intent.EXPLICIT_ORDER),
    ("Bonjour", Intent.SMALL_TALK),
])
def test_matrice_questions_avocats(query: str, expected: Intent) -> None:
    got = classify(query)
    assert got == expected, f"{query!r} → {got.value} (attendu {expected.value})"


# ── Cas limites ───────────────────────────────────────────────────────────────

def test_article_seul_sans_ponctuation() -> None:
    """Référence article nue doit déclencher le pipeline, pas un fallback small talk."""
    assert classify("L.1233-3") == Intent.IMPRECISE_LEGAL


def test_code_du_travail_seul() -> None:
    """'Code du travail' est un signal juridique, même isolé."""
    assert classify("Code du travail") == Intent.IMPRECISE_LEGAL


def test_phrase_longue_sans_mot_juridique() -> None:
    """Phrase longue hors-sujet doit rester SMALL_TALK pour laisser le handler répondre."""
    assert classify("Je me demande si demain il fera beau à Paris") == Intent.SMALL_TALK


def test_peux_tu_me_dire_bonjour_reste_small_talk() -> None:
    """Forme polie sans mot-clé juridique → SMALL_TALK (non, on n'attrape pas peux-tu)."""
    assert classify("Peux-tu me dire bonjour ?") == Intent.SMALL_TALK
