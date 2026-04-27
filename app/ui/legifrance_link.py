"""Citations [REF:] / [L.xxx] cliquables → Légifrance (H5 Sprint S1).

Détecte dans un texte les références d'articles juridiques, normalise leur
identifiant et construit l'URL Légifrance correspondante. Permet
l'application en place sur un NSMutableAttributedString : pour chaque
citation détectée, ajout d'un NSLinkAttributeName pointant vers Légifrance.

Le style visuel (underline + couleur accent) est hérité du
`setLinkTextAttributes_()` global du NSTextView (cf. hud_native.py:1537).
Le delegate `textView_clickedOnLink_atIndex_` ouvre l'URL dans Safari via
`NSWorkspace.openURL_`.

Patterns reconnus :
- `[REF: xxx]` → forme normée (prompt rédacteur)
- `[L.1234-9]`, `[L.1234-9-1]` (Code du travail / civil abrégé)
- `[R.1234-5]` (réglementaire)
- `[D.1234-5]` (décret)
- Tolère espaces internes : `[L. 1234 - 9]` → `L.1234-9`
"""
from __future__ import annotations

import re
from typing import Any, List, Tuple

from lucie_v1_standalone.knowledge_legifrance.parser import (
    LEGIFRANCE_ARTICLE_URL,
)


# Pattern unifié :
# - Forme `[REF: <id libre>]` : groupe 1 capture l'id (texte libre, on
#   normalise ensuite ; doit ressembler à un article LRDA pour qu'on linke)
# - Forme directe `[L.xxx]`, `[R.xxx]`, `[D.xxx]`, `[A.xxx]` : groupe 2
_CITATION_RE = re.compile(
    r"\["
    r"(?:"
    r"REF:\s*([^\]]+?)"
    r"|"
    r"([LRDA]\.\s*\d+(?:\s*-\s*\d+){0,2})"
    r")"
    r"\]"
)

# Validation post-normalisation : un identifiant cliquable doit ressembler à
# `L.1234-9` (lettre + point + digits + tirets). Sinon on linke pas (ex. un
# `[REF: voir aussi le doc]` ne devient pas un lien Légifrance).
_VALID_ARTICLE_RE = re.compile(r"^[LRDA]\.\d+(?:-\d+){0,2}$")


def _normalize_id(raw: str) -> str:
    """Normalise un identifiant : suppression des espaces internes.

    `L. 1234-9 ` → `L.1234-9`
    `L.1234 - 9` → `L.1234-9`
    """
    cleaned = re.sub(r"\s+", "", raw.strip())
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


def build_url(article_id: str) -> str:
    """Construit l'URL Légifrance à partir d'un identifiant d'article normalisé.

    Réutilise `LEGIFRANCE_ARTICLE_URL` du parser DILA.
    """
    return LEGIFRANCE_ARTICLE_URL.format(id=article_id)


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
