"""
IntentClassifier — Classification déterministe par regex + heuristique. 0 LLM.

Quatre modes :
  SMALL_TALK     — salutation, méta-question, légèreté
  IMPRECISE_LEGAL — sujet juridique sans assez de paramètres
  PRECISE_LEGAL  — question juridique avec tous les éléments nécessaires
  EXPLICIT_ORDER — ordre d'action (rédige, analyse, compare, résume, vérifie)
"""

from __future__ import annotations

import logging
import re
import unicodedata
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    SMALL_TALK = "SMALL_TALK"
    IMPRECISE_LEGAL = "IMPRECISE_LEGAL"
    PRECISE_LEGAL = "PRECISE_LEGAL"
    EXPLICIT_ORDER = "EXPLICIT_ORDER"


# ── Patterns SMALL_TALK ───────────────────────────────────────────────────────
_SMALL_TALK_RE = re.compile(
    r'^('
    r'bonjour|bonsoir|salut|hello|hi|hey|coucou|yo'
    r'|bonne journée|bonne soirée|bonne nuit'
    r'|merci|thank|thanks|de rien|avec plaisir'
    r'|au revoir|bye|à bientôt|à plus|à demain'
    r'|ok|okay|d\'accord|parfait|super|nickel|très bien'
    r'|qui es.tu|c\'est quoi ton nom|comment tu t\'appelles'
    r'|tu peux faire quoi|quelles sont tes fonctions|qu\'est.ce que tu fais'
    r'|tu es (un |une |quoi|qui)|tu es capable'
    r'|météo|blague|raconte.moi une blague|dis.moi quelque chose'
    r'|comment ça va|comment vas.tu|ça va'
    r'|aide.moi|help|aide'
    r')[\s!.,?;:]*$',
    re.IGNORECASE | re.UNICODE,
)

# ── Patterns EXPLICIT_ORDER ───────────────────────────────────────────────────
_EXPLICIT_ORDER_RE = re.compile(
    r'\b('
    r'rédige|rédiger|génère|générer|écris|écrire|crée|créer'
    r'|analyse|analyser|évalue|évaluer|examine|examiner'
    r'|compare|comparer|confronte'
    r'|résume|résumer|synthétise|synthétiser|récapitule'
    r'|vérifie|vérifier|contrôle|contrôler|valider'
    r'|calcule|calculer|estime|estimer'
    r'|liste|lister|énumère|énumérer|identifie|identifier'
    r'|explique|expliquer|détaille|détailler'
    r'|traduis|traduire|formate|formater'
    r')\b',
    re.IGNORECASE | re.UNICODE,
)

# ── Indicateurs de précision légale ──────────────────────────────────────────
# Une question juridique est considérée PRECISE_LEGAL si elle contient
# au moins 2 parmi : référence légale, chiffre/date, terme de procédure précis.

_LEGAL_REF_RE = re.compile(
    r'(l\.?\d{4}|r\.?\d{4}|article\s+[lr]\.?|code du travail'
    r'|cass\.?\s*soc|prud\'?hommes|pse|rcc|csp)',
    re.IGNORECASE,
)

_LEGAL_FIGURE_RE = re.compile(
    r'(\d+\s*(ans?|mois|jours?|semaines?|salaires?|euros?|%)'
    r'|\d{1,2}/\d{1,2}/\d{2,4}'
    r'|depuis\s+\d+'
    r'|ancienneté\s+de\s+\d+'
    r'|\d+\s+salariés?)',
    re.IGNORECASE,
)

_LEGAL_PROCEDURE_RE = re.compile(
    r'(licenciement économique|licenciement éco|licenciement collectif|préavis|cse|consultation|'
    r'indemnité légale|indemnité conventionnelle|reclassement|ordre des licenciements|'
    r'critères d\'ordre|plan de sauvegarde|convention collective|salarié protégé|'
    r'sauvegarde de la compétitivité|motif économique|difficultés économiques|'
    r'pse|rcc|csp)',
    re.IGNORECASE,
)

# ── Mots-clés juridiques larges (pour IMPRECISE_LEGAL) ───────────────────────
_LEGAL_KEYWORD_RE = re.compile(
    # No trailing \b — stems like licenci→licencié/licenciement, employ→employeur,
    # salar→salarié, indemnit→indemnité, économ→économique/économiques.
    r'\b(licenci|employ|salar|contrat de travail|droit du travail|'
    r'rupture|indemnit|préavis|prud|tribunal|juridique|légal|'
    r'économ|cse|consultation|reclassement|restructur|réorganis|suppression de poste)',
    re.IGNORECASE | re.UNICODE,
)


def _precision_score(text: str) -> int:
    """Compte les indicateurs de précision dans une requête juridique (0-3)."""
    score = 0
    if _LEGAL_REF_RE.search(text):
        score += 1
    if _LEGAL_FIGURE_RE.search(text):
        score += 1
    if _LEGAL_PROCEDURE_RE.search(text):
        score += 1
    return score


def classify(query: str) -> Intent:
    """
    Classifie une requête en l'un des 4 modes.

    Logique de priorité :
      1. EXPLICIT_ORDER si verbe d'action détecté
      2. SMALL_TALK si correspond aux patterns de salutation/méta
      3. PRECISE_LEGAL si ≥ 2 indicateurs de précision
      4. IMPRECISE_LEGAL si au moins 1 mot-clé juridique
      5. SMALL_TALK par défaut (requête non juridique sans ordre)
    """
    text = query.strip()

    # 1. Ordre explicite — priorité haute (peut se combiner avec du juridique)
    if _EXPLICIT_ORDER_RE.search(text):
        return Intent.EXPLICIT_ORDER

    # 2. Salutation / méta — requête courte, aucun mot-clé juridique
    if _SMALL_TALK_RE.match(text):
        return Intent.SMALL_TALK

    # 3. Juridique précis vs imprécis
    if _LEGAL_KEYWORD_RE.search(text):
        if _precision_score(text) >= 2:
            return Intent.PRECISE_LEGAL
        return Intent.IMPRECISE_LEGAL

    # 4. Par défaut : hors-scope, traité comme small talk (ni juridique ni ordre)
    return Intent.SMALL_TALK


# ── Détection de thème pour le Légifrance Retriever ──────────────────────────
#
# Fonction pure : lit `knowledge_legifrance/theme_mapping.yaml` en lazy,
# normalise la query (lowercase + retire les accents), matche les mots-clés
# déclarés par chaque thème. Non utilisée par `classify()` — c'est un
# helper indépendant appelé par le Retriever dans le pipeline aval.

_THEME_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent
    / "knowledge_legifrance"
    / "theme_mapping.yaml"
)


def _normalize_text(text: str) -> str:
    """Lowercase + strip des diacritiques (NFD)."""
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


@lru_cache(maxsize=1)
def _load_theme_keywords() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """
    Charge `theme_mapping.yaml` → ((theme_id, (keyword_normalized, ...)), ...).

    Tuples pour immutabilité + compat `lru_cache`. Silencieusement vide
    si le fichier est absent (Légifrance pas installé), pour ne pas casser
    le classifier.
    """
    try:
        from lucie_v1_standalone.knowledge_legifrance.indexer import (
            load_theme_mapping,
        )
    except ImportError:
        logger.debug("knowledge_legifrance indisponible — themes désactivés")
        return ()
    if not _THEME_MAPPING_PATH.exists():
        return ()
    try:
        mapping = load_theme_mapping(_THEME_MAPPING_PATH)
    except (OSError, ValueError) as exc:
        logger.warning("theme_mapping.yaml illisible (%s)", exc)
        return ()

    themes_tuple: list[tuple[str, tuple[str, ...]]] = []
    for theme_id, theme_def in mapping.get("themes", {}).items():
        raw_keywords = theme_def.get("mots_cles") or []
        normalized = tuple(
            _normalize_text(str(kw)) for kw in raw_keywords if kw
        )
        if normalized:
            themes_tuple.append((theme_id, normalized))
    return tuple(themes_tuple)


def detect_themes(query: str, max_themes: int = 3) -> list[str]:
    """
    Détecte les thèmes Légifrance pertinents pour `query`.

    - Matching par substring sur la forme normalisée (lowercase, sans accent)
      pour tolérer les fautes de frappe mineures (« salarié » / « salarie »).
    - Retourne au plus `max_themes` identifiants triés par score
      (nombre de mots-clés matchés, décroissant).
    - Liste vide si Légifrance n'est pas installé (le retriever fera un
      fallback sur la base curatée).
    """
    if not query or not query.strip():
        return []
    normalized = _normalize_text(query)
    scores: list[tuple[str, int]] = []
    for theme_id, keywords in _load_theme_keywords():
        hits = sum(1 for kw in keywords if kw and kw in normalized)
        if hits > 0:
            scores.append((theme_id, hits))
    scores.sort(key=lambda t: (-t[1], t[0]))
    return [theme_id for theme_id, _ in scores[:max_themes]]


def clear_theme_cache() -> None:
    """Invalide le cache (utile dans les tests qui modifient le YAML)."""
    _load_theme_keywords.cache_clear()
