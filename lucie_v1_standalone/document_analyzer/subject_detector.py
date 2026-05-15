"""Détection déterministe du sujet juridique d'un document.

Consomme `detect_themes_with_scores()` du theme_mapping existant en LECTURE
SEULE. Aucun LLM. Confidence calculée par densité de matches (nb keywords
matchés / longueur normalisée du document).
"""

from __future__ import annotations

import logging
from typing import Optional

from lucie_v1_standalone.dialogue.intent_classifier import detect_themes_with_scores

logger = logging.getLogger(__name__)

# Heuristique confiance — un thème avec ≥ HIT_FULL_CONFIDENCE matches saturé à 1.0.
HIT_FULL_CONFIDENCE = 5
SHORT_DOC_WORD_THRESHOLD = 50
SHORT_DOC_PENALTY = 0.7

# Seuil minimum de keywords matchés pour qu'un thème soit considéré comme
# détecté. POURQUOI : `detect_themes_with_scores` fait du substring matching
# qui produit des faux positifs sur les longues documents — ex : keyword "is"
# de fiscal_comptable substring-match "visa" et "risque" dans un dossier
# pharma. Un seuil ≥ 3 keywords distincts élimine ces faux positifs.
MIN_THEME_HITS = 3


def _confidence_from_hits(hits: int, doc_word_count: int) -> float:
    """Convertit (nb keywords matchés, mots du doc) en confidence [0.0, 1.0].

    Idée : 1 hit = 0.20, 3 hits = 0.60, 5+ hits = 1.0. Document très court
    (< 50 mots) pénalisé (peu de contexte → moins fiable).
    """
    if hits <= 0:
        return 0.0
    base = min(1.0, hits / HIT_FULL_CONFIDENCE)
    if doc_word_count < SHORT_DOC_WORD_THRESHOLD:
        base *= SHORT_DOC_PENALTY
    return round(base, 3)


def detect_subject(text: str) -> tuple[Optional[str], float, list[tuple[str, int]]]:
    """Détecte le thème juridique principal d'un texte.

    Retourne (top_theme, confidence, all_scored_themes).
    - top_theme : id du thème dominant (ex: "droit_social") ou None si rien.
    - confidence : [0.0, 1.0].
    - all_scored_themes : liste complète (theme, hits) du theme_mapping,
      utile au caller pour détecter un domaine secondaire hors-scope.
    """
    if not text or not text.strip():
        return None, 0.0, []

    scored = detect_themes_with_scores(text, max_themes=10)
    if not scored:
        logger.debug("Aucun thème détecté — texte=%r…", text[:80])
        return None, 0.0, []

    top_theme, top_hits = scored[0]
    # Anti-bruit : un thème avec < MIN_THEME_HITS keywords distincts est
    # probablement un faux positif substring (ex : "is" matching "visa").
    if top_hits < MIN_THEME_HITS:
        logger.debug(
            "Thème top=%s hits=%d < MIN_THEME_HITS=%d → considéré bruit",
            top_theme,
            top_hits,
            MIN_THEME_HITS,
        )
        return None, 0.0, scored

    word_count = len(text.split())
    confidence = _confidence_from_hits(top_hits, word_count)
    logger.debug(
        "Subject=%s hits=%d/words=%d → confidence=%.2f",
        top_theme,
        top_hits,
        word_count,
        confidence,
    )
    return top_theme, confidence, scored
