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
import os
import re
import unicodedata
from difflib import SequenceMatcher
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
    r'|recherche|rechercher|cherche|chercher'
    r'|trouve|trouver|cite|citer'
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
    # Sprint 6 P1bis (live test 2026-05-11) — variantes plurielles ajoutées
    # pour matcher « motifs économiques » (utilisé par Mathieu), « indemnités
    # légales », « licenciements économiques », etc. Sans ces variantes, le
    # _precision_score restait à 0 sur des questions pourtant claires.
    r'(licenciements? économiques?|licenciement éco|licenciements? collectifs?|préavis|cse|consultations?|'
    r'indemnités? légales?|indemnités? conventionnelles?|reclassement|ordre des licenciements|'
    r'critères d\'ordre|plan de sauvegarde|convention collective|salariés? protégés?|'
    r'sauvegarde de la compétitivité|motifs? économiques?|difficultés économiques|'
    r'pse|rcc|csp)',
    re.IGNORECASE,
)

# ── Mots-clés juridiques larges (pour IMPRECISE_LEGAL) ───────────────────────
_LEGAL_KEYWORD_RE = re.compile(
    # No trailing \b — stems like licenci→licencié/licenciement, employ→employeur,
    # salar→salarié, indemnit→indemnité, économ→économique/économiques.
    # Sprint 6 P1 — extension : congés/RTT/jours fériés + termes de droit social
    # courants ("faute simple" inclus, repos compensateur, durée du travail, etc.)
    # pour éviter le fall-through `SMALL_TALK` sur questions in-scope.
    r'\b(licenci|employ|salar|contrat de travail|droit du travail|'
    r'code du travail|'
    r'rupture|indemnit|préavis|prud|tribunal|juridique|légal|'
    r'économ|cse|consultation|reclassement|restructur|réorganis|suppression de poste|'
    r'ancienneté|motif|faute (simple|grave|lourde)|conseil de prud|délai|contester|'
    r'congé|congés|rtt|jour férié|jours fériés|repos compensateur|'
    r'fractionnement|décompte des congés|temps de travail|durée du travail|'
    r'rupture conventionnelle|démission|abandon de poste|résiliation judiciaire|'
    r'prise d\'acte|barème macron|insuffisance professionnelle|nullité du licenciement|'
    r'entretien préalable|lettre de licenciement|sauvegarde de la compétitivité)',
    re.IGNORECASE | re.UNICODE,
)

# ── Sprint 6 P1 — Détecteur licenciement personnel (hors-périmètre v1) ────────
# Beaume v1 couvre uniquement le licenciement économique. Les questions de
# licenciement personnel (disciplinaire, faute, insuffisance) doivent être
# refusées AVEC contexte (explication + redirection), pas avec un canned
# générique "imprecise_legal".
#
# Match → on déclenche un refus contextuel dans pipeline.py qui informe
# l'avocat du périmètre v1 et liste les sujets que Beaume sait traiter
# (motifs économiques, indemnité légale L.1234-9, PSE, CSP…).
_LIC_PERSO_RE = re.compile(
    r'\b('
    r'faute (simple|grave|lourde)'
    r'|insuffisance professionnelle'
    r'|insubordination|mésentente|abandon de poste'
    r'|barème macron'
    r'|licenciement (disciplinaire|pour motif personnel|pour faute)'
    r'|nullité du licenciement'
    r'|entretien préalable'
    r'|sanction disciplinaire'
    r')\b',
    re.IGNORECASE | re.UNICODE,
)


def detect_lic_perso(query: str) -> bool:
    """Retourne True si la query semble porter sur du licenciement personnel
    (hors périmètre Beaume v1 — qui ne couvre que le licenciement économique).

    Détection pure regex, déterministe, <1ms. Utilisée par le pipeline pour
    court-circuiter avec un message contextuel au lieu du canned générique
    `_IMPRECISE_LEGAL_REFUSAL`.

    NB : sauf indication contraire (mot-clé "économique"/"lic éco"), un match
    sur "faute grave"/"entretien préalable" est considéré lic_perso. Si la
    query contient AUSSI "licenciement économique", on laisse passer (la
    requête est mixte → traiter comme lic_eco standard).
    """
    if not query or not query.strip():
        return False
    # Court-circuit : si la query parle explicitement de "économique" ou
    # "L.1233-X" (articles lic éco), on considère que c'est une question
    # lic_eco même si elle mentionne "faute grave" en contexte.
    text = query.lower()
    if "économique" in text or "economique" in text:
        return False
    if re.search(r'\bl\.?\s?1233\b', text):
        return False
    return bool(_LIC_PERSO_RE.search(query))


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


# ── Sprint 6 P1 — détection question vs énoncé ───────────────────────────────
# Une question (« Quelle est la procédure… ? ») peut être adressée par le LLM
# même sans tous les paramètres chiffrés. Un énoncé (« Mon employeur veut me
# licencier. ») reste IMPRECISE_LEGAL : l'avocat doit préciser sa demande.
_QUESTION_OPENER_RE = re.compile(
    r"^(quel(le|s|les)?|comment|pourquoi|où|quand|combien|est-ce|"
    r"qui|que|qu'|peut-on|peut on|y a-t-il|y a t il|dans quel)\b",
    re.IGNORECASE | re.UNICODE,
)


def _looks_like_question(text: str) -> bool:
    """True si la query ressemble à une question explicite (vs un énoncé)."""
    if not text:
        return False
    if "?" in text:
        return True
    return bool(_QUESTION_OPENER_RE.match(text.strip()))


# ── Sprint 6 P1 — filet de sécurité : références d'articles fictives ─────────
# Le validator d'article (`dialogue/article_validator.py`) n'extrait que
# L./R. + 3-4 chiffres. Les formats fantaisistes type `D.1234-99999`,
# `L.99-99`, `N.1234-1` ne sont pas extraits → ne déclenchent pas le refus
# `article_invalid`. Avant Sprint 6 P1, ces queries tombaient en
# IMPRECISE_LEGAL (filet de sécurité). Avec l'assouplissement Sprint 6 P1,
# elles risquent de passer au LLM (test_A1 adversarial).
# → On garde la classification IMPRECISE_LEGAL quand on voit un pattern
#   « article X.YYY-ZZZ » qui ne correspond pas au format valide L/R + 3-4
#   chiffres. Cela préserve la non-régression de `test_A1_article_inexistant`.
_FAKE_ARTICLE_RE = re.compile(
    # « article » + un code qui ressemble à une ref mais n'est pas valide :
    # - lettre ≠ L/R (D, A, B, C, N, T, etc.) suivie de chiffres
    #   → character class [A-KM-QS-Z] exclut L (12e) et R (18e)
    # - L/R avec 1-2 chiffres seulement (« L.99-99 »)
    # - L/R avec 5+ chiffres en base (« L.99999-1 »)
    r"\barticle\s+"
    r"("
    r"[A-KM-QS-Z]\.?\s?\d+(?:-\d+)?"
    r"|[LRlr]\.?\s?\d{1,2}(?!\d)(?:-\d+)?"
    r"|[LRlr]\.?\s?\d{5,}(?:-\d+)?"
    r")\b",
    re.IGNORECASE,
)


def _has_fake_article_ref(text: str) -> bool:
    """True si la query cite un code d'article qui ne sera pas validé par
    l'article_validator (préfixe ≠ L/R, ou nombre de chiffres incorrect).

    Sert de filet de sécurité : on garde la classification IMPRECISE_LEGAL
    sur ces queries pour ne pas laisser le LLM halluciner sur des articles
    fictifs hors-format. Le validator article (`dialogue/article_validator`)
    couvre déjà L/R + 3-4 chiffres ; ce filet couvre tout le reste.
    """
    if not text:
        return False
    return bool(_FAKE_ARTICLE_RE.search(text))


def classify(query: str) -> Intent:
    """
    Classifie une requête en l'un des 4 modes.

    Logique de priorité :
      1. EXPLICIT_ORDER si verbe d'action détecté
      2. SMALL_TALK si correspond aux patterns de salutation/méta
      3. Référence légale explicite (L.XXXX, article L., code du travail…)
         → PRECISE_LEGAL si score ≥ 2, sinon IMPRECISE_LEGAL
      4. Mot-clé juridique large → PRECISE_LEGAL si score ≥ 2, sinon IMPRECISE_LEGAL
      5. SMALL_TALK par défaut (préserve le routage hors-scope du SmallTalkHandler)
    """
    text = query.strip()
    preview = text[:50]

    if _EXPLICIT_ORDER_RE.search(text):
        logger.info("IntentClassifier: %r → EXPLICIT_ORDER (verbe d'action)", preview)
        return Intent.EXPLICIT_ORDER

    if _SMALL_TALK_RE.match(text):
        logger.info("IntentClassifier: %r → SMALL_TALK (pattern salutation)", preview)
        return Intent.SMALL_TALK

    has_legal_ref = bool(_LEGAL_REF_RE.search(text))
    has_legal_kw_regex = bool(_LEGAL_KEYWORD_RE.search(text))
    has_legal_kw_fuzzy = False
    if not has_legal_kw_regex and not has_legal_ref:
        # Fallback fuzzy uniquement si la regex stricte ne matche pas — évite
        # le coût sur les queries déjà correctement classées.
        # Import retardé pour éviter l'import circulaire avec fuzzy_legal.
        from lucie_v1_standalone.dialogue.fuzzy_legal import fuzzy_legal_boost

        has_legal_kw_fuzzy = fuzzy_legal_boost(text)
        if has_legal_kw_fuzzy:
            logger.info(
                "IntentClassifier: %r → boost fuzzy (mot-clé juridique approximatif)",
                preview,
            )
    has_legal_kw = has_legal_kw_regex or has_legal_kw_fuzzy

    if has_legal_ref or has_legal_kw:
        score = _precision_score(text)
        # Sprint 6 P1 — filet de sécurité prioritaire : si la query cite un
        # code d'article fictif/mal-formé (D.XX, L.99-99, N.1234…) que le
        # validator article n'extrait pas, on FORCE IMPRECISE_LEGAL pour ne
        # pas laisser le LLM inventer un contenu sur un article qui n'existe
        # pas. Cf. test_A1_article_inexistant adversarial.
        if _has_fake_article_ref(text):
            logger.info(
                "IntentClassifier: %r → IMPRECISE_LEGAL "
                "(filet sécurité : article ref fictive)", preview,
            )
            return Intent.IMPRECISE_LEGAL
        # Sprint 6 P1 — assouplissement : si la query est une vraie question
        # (« Quelle… ? », « Comment… ? » ou se termine par « ? ») ET contient
        # un mot-clé juridique métier, on la considère PRECISE_LEGAL : un
        # avocat pose ce type de question naturellement, et la KB + le LLM +
        # le vérificateur déterministe sauront répondre (ou refuser
        # honnêtement « pas dans mes sources »). Sans cet assouplissement,
        # 22/50 questions in-scope étaient rejetées en `imprecise_legal`
        # (Sprint 5 baseline, cause #1 du score 27/50).
        if has_legal_kw and _looks_like_question(text):
            logger.info(
                "IntentClassifier: %r → PRECISE_LEGAL (question + kw, score=%d)",
                preview, score,
            )
            return Intent.PRECISE_LEGAL
        # Sprint 6 P1bis — assouplissement #2 (live test 2026-05-11) :
        # Énoncé court mais précis avec mot-clé juridique fort + indicateur
        # PROCEDURE ou FIGURE matché (exclut le ref-only « Code du travail »
        # seul, qui reste IMPRECISE_LEGAL car trop vague). Couvre les inputs
        # type « procédure CSE pour licenciement éco » que l'avocat tape
        # rapidement sans ponctuation interrogative.
        if has_legal_kw and (
            _LEGAL_PROCEDURE_RE.search(text) or _LEGAL_FIGURE_RE.search(text)
        ):
            logger.info(
                "IntentClassifier: %r → PRECISE_LEGAL (kw + procedure/figure, score=%d)",
                preview, score,
            )
            return Intent.PRECISE_LEGAL
        if score >= 2:
            logger.info(
                "IntentClassifier: %r → PRECISE_LEGAL (score=%d)", preview, score
            )
            return Intent.PRECISE_LEGAL
        motif = "ref article" if has_legal_ref else f"mot-clé juridique (score={score})"
        logger.info("IntentClassifier: %r → IMPRECISE_LEGAL (%s)", preview, motif)
        return Intent.IMPRECISE_LEGAL

    logger.info("IntentClassifier: %r → SMALL_TALK (défaut)", preview)
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


_FUZZY_THEME_TOKEN_RE = re.compile(r"\w{5,}", re.UNICODE)
_FUZZY_THEME_THRESHOLD = 0.85


def _fuzzy_theme_fallback(normalized: str) -> list[tuple[str, int]]:
    """Sprint 6 P2b (B-2 sol 2) — fallback fuzzy quand le matching substring
    exact retourne 0 thème. Rattrape les variantes lexicales / fautes du type
    « csp » → « csp » (déjà OK avec B-5), « psp » → « pse »,
    « lcenciement » → « licenciement ».

    Pour chaque token ≥5 chars de la query normalisée, compare à chaque
    keyword ≥5 chars du theme_mapping via SequenceMatcher.ratio() ≥ 0.85
    (même seuil/filtre que fuzzy_legal.py). Filtre anti-faux-positif :
    même lettre initiale. Un hit max par token (évite la sur-pondération).
    """
    tokens = _FUZZY_THEME_TOKEN_RE.findall(normalized)
    scores: list[tuple[str, int]] = []
    for theme_id, keywords in _load_theme_keywords():
        hits = 0
        for token in tokens:
            for kw in keywords:
                if not kw or len(kw) < 5:
                    continue
                if token[0] != kw[0]:
                    continue
                if SequenceMatcher(None, token, kw).ratio() >= _FUZZY_THEME_THRESHOLD:
                    hits += 1
                    break  # un hit max par token
        if hits > 0:
            scores.append((theme_id, hits))
    scores.sort(key=lambda t: (-t[1], t[0]))
    return scores


def detect_themes_with_scores(
    query: str, max_themes: int = 3
) -> list[tuple[str, int]]:
    """Variante de `detect_themes` qui expose le nombre de keywords matchés
    par thème, requise par Sprint 6 P2a (B-5 sol 1) : le caller débride le
    Retriever Légifrance quand le score max est ≤ 1 (signal "détection
    incertaine"). Liste de tuples `(theme_id, hits)` triée par hits décroissant.

    Sprint 6 P2b (B-2 sol 2) : si le matching substring exact retourne 0
    thème, fallback fuzzy `_fuzzy_theme_fallback()` activable via
    `BEAUME_FUZZY_LEGAL_BOOST=1` (défaut=1). Permet de rattraper des
    keywords mal orthographiés ou des variantes lexicales non couvertes
    par les `mots_cles` du YAML."""
    if not query or not query.strip():
        return []
    normalized = _normalize_text(query)
    scores: list[tuple[str, int]] = []
    for theme_id, keywords in _load_theme_keywords():
        hits = sum(1 for kw in keywords if kw and kw in normalized)
        if hits > 0:
            scores.append((theme_id, hits))
    if scores:
        scores.sort(key=lambda t: (-t[1], t[0]))
        return scores[:max_themes]
    if os.environ.get("BEAUME_FUZZY_LEGAL_BOOST", "1") == "1":
        fuzzy_scores = _fuzzy_theme_fallback(normalized)
        if fuzzy_scores:
            logger.info(
                "[FuzzyTheme] fallback déclenché — query=%r → themes=%s",
                query[:60],
                [t for t, _ in fuzzy_scores[:max_themes]],
            )
            return fuzzy_scores[:max_themes]
    return []


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
    return [theme_id for theme_id, _ in detect_themes_with_scores(query, max_themes)]


def clear_theme_cache() -> None:
    """Invalide le cache (utile dans les tests qui modifient le YAML)."""
    _load_theme_keywords.cache_clear()
