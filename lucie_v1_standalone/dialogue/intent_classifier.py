"""
IntentClassifier — Classification déterministe par regex + heuristique. 0 LLM.

Quatre modes :
  SMALL_TALK     — salutation, méta-question, légèreté
  IMPRECISE_LEGAL — sujet juridique sans assez de paramètres
  PRECISE_LEGAL  — question juridique avec tous les éléments nécessaires
  EXPLICIT_ORDER — ordre d'action (rédige, analyse, compare, résume, vérifie)
"""

from __future__ import annotations

import re
from enum import Enum


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
