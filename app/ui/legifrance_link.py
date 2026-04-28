"""Citations [REF:] / [L.xxx] / [L1234-9] cliquables → Légifrance (H5 + H5b).

Détecte dans un texte les références d'articles juridiques, normalise leur
identifiant et construit l'URL Légifrance correspondante. Permet
l'application en place sur un NSMutableAttributedString : pour chaque
citation détectée, ajout d'un NSLinkAttributeName pointant vers Légifrance.

Le style visuel (underline + couleur accent) est hérité du
`setLinkTextAttributes_()` global du NSTextView (cf. hud_native.py:1537).
Le delegate `textView_clickedOnLink_atIndex_` ouvre l'URL dans Safari via
`NSWorkspace.openURL_`.

Patterns reconnus (H5b — parser tolérant) :
- `[REF: xxx]` → forme normée (prompt rédacteur)
- `[L.1234-9]`, `[L.1234-9-1]` (Code du travail / civil abrégé canonique)
- `[L1234-9]` (sans dot — émis par le redacteur via `[l1233-2]` cf.
  `prompts/redacteur_system.txt:51`)
- `[L 1234-9]`, `[L. 1234 - 9]` (espaces internes tolérés)
- `[l1234-9]` (lowercase — normalisé en majuscules)
- `[R.1234-5]` / `[R1234-5]` (réglementaire), `[D...]` (décret), `[A...]` (arrêté)
- Toutes les variantes sont normalisées vers la forme canonique `L.1234-9`
  (uppercase + point inséré + sans espaces).
"""
from __future__ import annotations

import re
from typing import Any, List, Tuple


# Pattern unifié :
# - Forme `[REF: <id libre>]` : groupe 1 capture l'id (texte libre, on
#   normalise ensuite ; doit ressembler à un article LRDA pour qu'on linke)
# - Forme directe `[L.xxx]`/`[L xxx]`/`[Lxxx]` : groupe 2 — dot et espaces
#   optionnels, lowercase accepté (cf. format émis par redacteur prompt)
_CITATION_RE = re.compile(
    r"\["
    r"(?:"
    r"REF:\s*([^\]]+?)"
    r"|"
    r"([LRDAlrda]\.?\s*\d+(?:\s*-\s*\d+){0,2})"
    r")"
    r"\]"
)

# Validation post-normalisation : un identifiant cliquable doit ressembler à
# `L.1234-9` (lettre + point + digits + tirets). Sinon on linke pas (ex. un
# `[REF: voir aussi le doc]` ne devient pas un lien Légifrance).
# Le point est imposé en sortie de `_normalize_id`, donc ce regex strict est OK.
_VALID_ARTICLE_RE = re.compile(r"^[LRDA]\.\d+(?:-\d+){0,2}$")


def _normalize_id(raw: str) -> str:
    """Normalise un identifiant vers la forme canonique `L.NNNN-N`.

    - Suppression des espaces internes
    - Uppercase
    - Insertion du point manquant entre la lettre et les chiffres

    Exemples :
    - `L. 1234-9 `   → `L.1234-9`
    - `L.1234 - 9`   → `L.1234-9`
    - `L1234-9`      → `L.1234-9`
    - `l1234-9`      → `L.1234-9`
    - `L 1234-9`     → `L.1234-9`
    """
    cleaned = re.sub(r"\s+", "", raw.strip()).upper()
    cleaned = re.sub(r"^([LRDA])(\d)", r"\1.\2", cleaned)
    return cleaned


def parse_citations(text: str) -> List[Tuple[str, int, int]]:
    """Détecte les citations dans `text` et retourne les triplets (id_normalisé, start, end).

    `start`/`end` sont les positions inclusives/exclusives du match complet
    `[REF:...]` ou `[L.xxx]` dans le texte d'entrée — pas le contenu seul.
    """
    results: List[Tuple[str, int, int]] = []
    for m in _CITATION_RE.finditer(text):
        ref_form = m.group(1)
        direct_form = m.group(2)
        raw = ref_form if ref_form is not None else direct_form
        if raw is None:
            continue
        normalized = _normalize_id(raw)
        if not _VALID_ARTICLE_RE.match(normalized):
            continue
        results.append((normalized, m.start(), m.end()))
    return results


# H5b — l'endpoint canonique `codes/article_lc/{id}` exige un identifiant
# LEGIARTI<14_digits>, pas un numéro d'article comme `L.1233-8`. La recherche
# par NUM_ARTICLE est plus robuste : Légifrance résout le numéro vers la bonne
# fiche, et en cas d'article inexistant l'utilisateur arrive sur une page
# « 0 résultat » au lieu d'un 404 sec. Vérifié 2026-04-28 (HTTP 301 vers
# `search?fonds=CODE&...` confirme l'endpoint).
_LEGIFRANCE_SEARCH_URL = (
    "https://www.legifrance.gouv.fr/search/code"
    "?searchField=NUM_ARTICLE&query={article}&searchType=ALL"
)


def build_url(article_id: str) -> str:
    """Construit l'URL Légifrance de recherche pour un identifiant d'article.

    `article_id` doit être normalisé (`L.1234-9`). On strip le point pour la
    requête (Légifrance accepte indifféremment `L1234-9` et `L.1234-9`, mais
    la forme sans point évite les surprises d'encodage URL).
    """
    query = article_id.replace(".", "")
    return _LEGIFRANCE_SEARCH_URL.format(article=query)


def apply_links(attr_string: Any) -> int:
    """Applique des NSLinkAttribute sur les citations détectées dans
    `attr_string` (NSMutableAttributedString).

    Retourne le nombre de citations effectivement linkées.

    Le style (underline, couleur accent) est défini globalement par
    `NSTextView.setLinkTextAttributes_()` ; on ajoute uniquement
    l'attribut NSLinkAttributeName + l'URL.
    """
    import AppKit
    import Foundation

    raw_text = attr_string.string()
    citations = parse_citations(raw_text)
    if not citations:
        return 0

    count = 0
    for article_id, start, end in citations:
        url = AppKit.NSURL.URLWithString_(build_url(article_id))
        if url is None:
            continue
        attr_string.addAttribute_value_range_(
            AppKit.NSLinkAttributeName,
            url,
            Foundation.NSMakeRange(start, end - start),
        )
        # Tooltip discret : explicite la cible de manière non intrusive.
        attr_string.addAttribute_value_range_(
            AppKit.NSToolTipAttributeName,
            f"Ouvrir {article_id} sur Légifrance",
            Foundation.NSMakeRange(start, end - start),
        )
        count += 1
    return count


__all__ = ["parse_citations", "build_url", "apply_links"]
