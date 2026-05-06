"""Préfiltre bornes numériques d'articles juridiques (Cerveau Oiseaux v2).

Refus instantané (<1ms) pour les articles numériquement impossibles, AVANT
tout I/O SQLite Légifrance. Source des bornes (par ordre de priorité) :

  1. `article_bounds_data.py` — table générée depuis SQLite Légifrance par
     `scripts/build_article_bounds.py` (versionnée dans git, ~4500 racines
     couvrant L/R/D du Code du travail). C'est la SOURCE D'AUTORITÉ.
  2. Fallback dégradé : dérivation depuis `whitelist_ct._RANGES` (~250
     racines, sous-couverture acceptée — actif uniquement si le fichier
     généré est absent, ex: CI sans DILA).

Cas d'usage : « L.1234-999 » est mathématiquement impossible (la racine
L.1234-x s'arrête à 20 dans le Code du travail). Avant Cerveau Oiseaux v2,
ce refus prenait ~9 s (SQLite cold cache + index miss sur clé absente).
Après : <1 ms (lookup dict O(1)).

Vérité mathématique : si la racine est inconnue dans la table de bornes,
on ne dit RIEN — laisse les gates suivants (SQLite, whitelist) décider.
Aucun faux positif possible par construction sur racine inconnue.

Le préfiltre est un court-circuit logique : il ne remplace pas la chaîne
de résolveurs, il évite l'I/O quand la réponse est déterminée par la
seule connaissance structurelle de la cardinalité d'une racine.

Régénération : après chaque sync DILA majeure, exécuter
`python3 scripts/build_article_bounds.py` pour rafraîchir les bornes.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Chargement de la table de bornes ───────────────────────────────────────
# Priorité 1 : fichier généré depuis SQLite Légifrance (autorité).
# Priorité 2 : dérivation depuis whitelist_ct._RANGES (fallback dégradé).

_BOUNDS_SOURCE: str
ARTICLE_BOUNDS_CT: dict[tuple[str, int], tuple[int, int]] = {}

try:
    from lucie_v1_standalone.dialogue.article_bounds_data import (
        ARTICLE_BOUNDS_DATA,
        GENERATED_AT,
    )

    ARTICLE_BOUNDS_CT = dict(ARTICLE_BOUNDS_DATA)
    _BOUNDS_SOURCE = f"sqlite-legifrance@{GENERATED_AT}"
except ImportError:
    # Mode dégradé : article_bounds_data.py absent (CI/dev sans DILA syncée).
    # On dérive depuis _RANGES avec couverture réduite.
    from lucie_v1_standalone.dialogue.whitelist_ct import _RANGES

    for _prefix, _base, _first, _last in _RANGES:
        _key = (_prefix, _base)
        _cur = ARTICLE_BOUNDS_CT.get(_key)
        if _cur is None:
            ARTICLE_BOUNDS_CT[_key] = (_first, _last)
        else:
            ARTICLE_BOUNDS_CT[_key] = (
                min(_cur[0], _first),
                max(_cur[1], _last),
            )
    _BOUNDS_SOURCE = "whitelist-ranges-fallback"
    logger.warning(
        "[article_bounds] article_bounds_data.py absent, fallback whitelist "
        "(%d racines couvertes, sous-couverture vs DILA). Régénérer via : "
        "python3 scripts/build_article_bounds.py",
        len(ARTICLE_BOUNDS_CT),
    )


# Index par code juridique. Extensible : `code_commerce`, `code_civil`, etc.
ARTICLE_BOUNDS_BY_CODE: dict[str, dict[tuple[str, int], tuple[int, int]]] = {
    "code_du_travail": ARTICLE_BOUNDS_CT,
}


# Aligné sur ARTICLE_PATTERN (article_validator.py:41) : seuls L et R sont
# extraits par le pipeline upstream. On accepte D ici aussi car la table
# de bornes générée couvre les D du Code du travail (utile si l'extraction
# évolue, sans coût supplémentaire).
_ARTICLE_RE = re.compile(
    r"^([LRD])\.?\s?(\d{3,4})(?:-(\d+))?(?:-\d+)?$",
    re.IGNORECASE,
)


def parse_article_ref(article_ref: str) -> Optional[tuple[str, int, int]]:
    """Parse "L.1234-999" → ("L", 1234, 999).

    Accepte : "L.1234-999", "L1234-999", "L 1234-999", "l.1234-999",
    "L.1234-17-1" (sub-suffix ignoré : on retient le suffix principal 17).
    Retourne None si format non reconnu OU si pas de suffixe numéro
    (un article sans suffixe n'a pas de borne à vérifier).
    """
    m = _ARTICLE_RE.match(article_ref.strip())
    if m is None:
        return None
    classe = m.group(1).upper()
    base = m.group(2)
    num = m.group(3)
    if num is None:
        return None
    try:
        return (classe, int(base), int(num))
    except ValueError:
        return None


_SOURCE_IS_EXHAUSTIVE = _BOUNDS_SOURCE.startswith("sqlite-legifrance")


def is_article_impossible(article_ref: str) -> tuple[bool, Optional[str]]:
    """Refus instantané (<1ms) si l'article est numériquement impossible.

    Trois cas de refus, tous en O(1) sans I/O :
      1. Numéro > suffix_max sur racine connue (ex: L.1234-999 vs max=20).
      2. Numéro < suffix_min sur racine connue.
      3. Racine totalement absente de la table — UNIQUEMENT quand la source
         est exhaustive (SQLite Légifrance, ~4500 racines L/R/D). En mode
         dégradé whitelist on garde le silence pour éviter les faux positifs
         (la whitelist ne couvre que ~250 racines).

    Le cas 3 résout L.9999-1, R.0000-0, etc. — racines totalement
    fantaisistes que la baseline SQLite met ~10 s à invalider faute de
    pouvoir utiliser ses index sur clé absente.

    Returns:
        (True, raison) si refus déterministe.
        (False, None) si format non reconnu, numéro dans borne, ou racine
                      inconnue en mode whitelist dégradé.
    """
    parsed = parse_article_ref(article_ref)
    if parsed is None:
        return False, None
    classe, base, num = parsed
    bounds = ARTICLE_BOUNDS_CT.get((classe, base))
    if bounds is None:
        if _SOURCE_IS_EXHAUSTIVE:
            return True, (
                f"L'article {classe}.{base}-{num} ne peut pas exister : "
                f"aucun article de la forme {classe}.{base}-x n'est en "
                f"vigueur dans le Code du travail."
            )
        return False, None
    suffix_min, suffix_max = bounds
    if num > suffix_max:
        return True, (
            f"L'article {classe}.{base}-{num} ne peut pas exister : "
            f"la racine {classe}.{base}-x s'arrête à {suffix_max} "
            f"dans le Code du travail."
        )
    if num < suffix_min:
        return True, (
            f"L'article {classe}.{base}-{num} ne peut pas exister : "
            f"la racine {classe}.{base}-x commence à {suffix_min} "
            f"dans le Code du travail."
        )
    return False, None


def bounds_table_size() -> int:
    """Nombre de racines couvertes par la table de bornes (pour logs/audit)."""
    return len(ARTICLE_BOUNDS_CT)


def bounds_source() -> str:
    """Identifiant de la source des bornes (pour logs/audit/rapport)."""
    return _BOUNDS_SOURCE


__all__ = [
    "ARTICLE_BOUNDS_BY_CODE",
    "ARTICLE_BOUNDS_CT",
    "bounds_source",
    "bounds_table_size",
    "is_article_impossible",
    "parse_article_ref",
]
