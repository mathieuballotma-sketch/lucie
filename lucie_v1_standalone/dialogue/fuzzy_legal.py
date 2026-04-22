"""Fuzzy matching sur mots-clés juridiques — tolérance fautes d'orthographe.

Rattrape les queries mal orthographiées qui passaient à côté des regex
déterministes de l'IntentClassifier. Exemples :
  - « licensiment » → match « licenciement »
  - « liscenciement » → match « licenciement »
  - « prudhomal » → match « prud'hommes »

Filtres anti-faux-positifs :
  - Tokens < 5 chars ignorés (trop courts pour être discriminants).
  - Même lettre initiale (token[0] == stem[0]) requise.
  - Threshold base 0.80 (calibré : attrape « licensiment » → ratio 0.87,
    « liscenciement » → ratio 0.96, sans générer de faux positifs sur le
    dictionnaire de stems).

Limite connue : « prudhomal » → « prud'hommes » reste à ratio 0.70 (trop
faible pour le threshold). Cas partiel documenté, non résolu dans cette
phase. L'utilisateur qui écrit cette faute passera par la regex stricte
`_LEGAL_KEYWORD_RE` côté intent_classifier (qui matche `prud'?hommes`).

Bibliothèque : `difflib.SequenceMatcher` (stdlib, zéro dépendance).
Volumétrie typique : ~12 stems × ~10 tokens / query = ~120 comparaisons,
< 5 ms en pratique. rapidfuzz serait overkill pour cette échelle.

Signal additif : ne remplace pas les regex existantes, boost seulement
quand la regex stricte ne matche pas (cf. intent_classifier.classify()).
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from lucie_v1_standalone.dialogue.intent_classifier import _normalize_text

logger = logging.getLogger(__name__)

# Stems juridiques normalisés (sans accent, lowercase). Ce sont les racines
# techniques — pas du contenu métier éditable. Hardcodé volontairement pour
# éviter que des modifs YAML cassent la détection.
_LEGAL_STEMS: tuple[str, ...] = (
    "licenciement",
    "employeur",
    "salarie",
    "preavis",
    "indemnite",
    "reclassement",
    "restructuration",
    "prud'hommes",
    "prudhommes",
    "consultation",
    "anciennete",
    "convention",
    "requete",
    "conclusions",
    "procedure",
)

_TOKEN_RE = re.compile(r"\w{5,}", re.UNICODE)


def _token_matches_stem(token: str, stem: str, threshold: float) -> bool:
    """Un token matche un stem si :
    1. même lettre initiale (filtre anti-faux-positif principal),
    2. ratio SequenceMatcher ≥ threshold.
    """
    if not token or not stem:
        return False
    if token[0] != stem[0]:
        return False
    return SequenceMatcher(None, token, stem).ratio() >= threshold


def fuzzy_legal_boost(query: str, threshold: float = 0.80) -> bool:
    """Retourne True si au moins un token de `query` (≥ 5 chars) matche
    un stem juridique de façon approximative (ratio ≥ threshold avec filtres).

    Signal additif destiné à être utilisé dans IntentClassifier.classify()
    comme fallback quand la regex stricte `_LEGAL_KEYWORD_RE` ne matche pas.
    """
    if not query or not query.strip():
        return False

    normalized = _normalize_text(query)
    tokens = _TOKEN_RE.findall(normalized)
    for token in tokens:
        for stem in _LEGAL_STEMS:
            if _token_matches_stem(token, stem, threshold):
                logger.info(
                    "[FuzzyMatch] token=%r → stem=%r (ratio≥%.2f)",
                    token,
                    stem,
                    threshold,
                )
                return True
    return False


__all__ = ["fuzzy_legal_boost"]
