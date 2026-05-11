"""
Tests — IntentClassifier (20 tests, 5 par mode).
"""

from __future__ import annotations

import pytest

from lucie_v1_standalone.dialogue.intent_classifier import Intent, classify, detect_lic_perso


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


# ── IMPRECISE_LEGAL (4 cas — énoncés sans question) ─────────────────────────
# Sprint 6 P1 : les énoncés vagues (sans « ? » ni mot interrogatif) restent
# IMPRECISE_LEGAL. Le filet « pour répondre précisément… » se déclenche
# encore : ces énoncés ne sont pas adressables en l'état par le LLM.
# « Quels sont mes droits de salarié ? » a été retiré : c'est une vraie
# question d'avocat avec un mot-clé fort → PRECISE_LEGAL (cf. test ci-dessous).

@pytest.mark.parametrize("query", [
    "J'ai été licencié.",
    "Mon contrat de travail a été rompu.",
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


# ── Matrice Mathieu — fix routing v0.4.2 + Sprint 6 P1 ──────────────────────
# Avant fix v0.4.2 : questions factuelles classées SMALL_TALK → réponse
#            générique « Je me spécialise en droit du licenciement éco. »
# Après fix v0.4.2 : routées EXPLICIT_ORDER ou IMPRECISE_LEGAL.
# Après Sprint 6 P1 : les vraies questions (« ? » ou mot interrogatif) AVEC
#            un mot-clé juridique sont désormais PRECISE_LEGAL → traitées
#            par le LLM (auparavant rejetées en `imprecise_legal`, cause
#            #1 du score batterie 27/50 Sprint 5).

@pytest.mark.parametrize("query,expected", [
    # Sprint 6 P1 — flip: vraie question + mot-clé fort → PRECISE_LEGAL
    ("Quelle est la durée légale du préavis ?", Intent.PRECISE_LEGAL),
    ("L.1233-3 ?", Intent.IMPRECISE_LEGAL),  # ref article seule sans question
    ("Peux-tu m'expliquer le licenciement économique ?", Intent.EXPLICIT_ORDER),
    ("J'ai besoin d'une note sur le préavis", Intent.IMPRECISE_LEGAL),  # énoncé
    ("Donne-moi les motifs de licenciement économique", Intent.IMPRECISE_LEGAL),  # impératif sans verbe EXPLICIT_ORDER, pas de "?"
    # Sprint 6 P1 — flip: "combien" + "licenciement" → PRECISE_LEGAL
    ("Dans combien de temps peut-on contester un licenciement ?", Intent.PRECISE_LEGAL),
    # Sprint 6 P1 — flip: "Quelle indemnité ?" + figure → PRECISE_LEGAL
    ("Quelle indemnité pour 12 ans d'ancienneté ?", Intent.PRECISE_LEGAL),
    ("Que dit L.1233-3 ?", Intent.IMPRECISE_LEGAL),  # has_legal_ref only, no kw
    ("Recherche l'article L.1234-1", Intent.EXPLICIT_ORDER),
    ("Bonjour", Intent.SMALL_TALK),
])
def test_matrice_questions_avocats(query: str, expected: Intent) -> None:
    got = classify(query)
    assert got == expected, f"{query!r} → {got.value} (attendu {expected.value})"


# ── PRECISE_LEGAL — élargissement Sprint 6 P1 ────────────────────────────────
# Vraies questions d'avocat avec mot-clé juridique fort. Avant Sprint 6 P1
# ces queries étaient rejetées en IMPRECISE_LEGAL (refus canned). C'est la
# régression que Sprint 6 P1 corrige.

@pytest.mark.parametrize("query", [
    "Quelle est la procédure de licenciement économique individuel ?",
    "Comment fonctionne le licenciement éco collectif <10 salariés ?",
    "Un jour férié pendant les congés payés est-il décompté ?",
    "Que sont les RTT et qui en bénéficie ?",
    "Quels sont mes droits de salarié ?",
])
def test_precise_legal_sprint6_p1(query: str) -> None:
    """Questions in-scope avocat qui doivent désormais être routées au LLM."""
    assert classify(query) == Intent.PRECISE_LEGAL, (
        f"Sprint 6 P1 : attendu PRECISE_LEGAL pour : {query!r}"
    )


# ── detect_lic_perso() — Sprint 6 P1 ──────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "Quelle est la différence entre faute simple, faute grave et faute lourde ?",
    "Que faire en cas d'insuffisance professionnelle ?",
    "Quel est le barème Macron applicable ?",
    "Comment se passe l'entretien préalable ?",
    "Mon employeur invoque une mésentente, est-ce un motif valable ?",
    "Quelle est la procédure de licenciement disciplinaire ?",
    "Quel est l'effet d'une nullité du licenciement ?",
    "Quelle indemnité pour un licenciement pour motif personnel hors faute ?",
])
def test_detect_lic_perso_match(query: str) -> None:
    """Questions clairement lic_perso doivent être détectées."""
    assert detect_lic_perso(query), f"Sprint 6 P1 : attendu lic_perso=True pour : {query!r}"


@pytest.mark.parametrize("query", [
    "Quelle est la procédure de licenciement économique individuel ?",
    "Quels sont les motifs économiques selon L.1233-3 ?",
    "Comment se calcule l'indemnité de licenciement économique ?",
    "Le CSP s'applique-t-il en rupture conventionnelle ?",
    "Un jour férié pendant les congés est-il décompté ?",
    "Bonjour",
])
def test_detect_lic_perso_negative(query: str) -> None:
    """Questions lic_eco ou hors-domaine ne doivent PAS être détectées lic_perso."""
    assert not detect_lic_perso(query), (
        f"Sprint 6 P1 : attendu lic_perso=False pour : {query!r}"
    )


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
