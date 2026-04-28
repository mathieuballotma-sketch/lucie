"""Tests H5 + H5b — citations Légifrance cliquables.

H5 (Sprint S1) — 8 cas baseline :
1. `[REF: L.1234-9]` détecté
2. `[L.1235-3]` (raccourci) détecté
3. Multi-citations dans une phrase
4. URL pointe vers legifrance.gouv.fr (forme search depuis H5b)
5. Normalisation des espaces
6. Pas de match sur faux positifs
7. Texte vide → 0
8. apply_links retourne le bon count

H5b (Sprint S1bis) — 5 cas ajoutés pour le parser tolérant :
9.  `[L1233-8]` (sans dot) → détecté + normalisé
10. `[L 1233-8]` (espace) → détecté + normalisé
11. `[l1233-8]` (lowercase) → détecté + normalisé en uppercase
12. `[REF: L1233-8]` (REF + sans dot) → détecté
13. `build_url` génère bien une URL Légifrance contenant l'identifiant

PyObjC requis pour `apply_links` (skip propre si AppKit indisponible).
"""
from __future__ import annotations

import pytest

from app.ui.legifrance_link import build_url, parse_citations


# ─── Tests parser (purs, sans PyObjC) ────────────────────────────────────────


def test_ref_form_extracts_normalized_id_with_correct_range():
    """1. `[REF: L.1234-9]` → ID `L.1234-9` + plage du match complet."""
    text = "Voir [REF: L.1234-9] pour les détails."
    citations = parse_citations(text)
    assert len(citations) == 1
    cite_id, start, end = citations[0]
    assert cite_id == "L.1234-9"
    # Plage = `[REF: L.1234-9]`
    assert text[start:end] == "[REF: L.1234-9]"


def test_short_form_lr_d_detected():
    """2. `[L.1235-3]` (raccourci) détecté."""
    text = "L'article [L.1235-3] fixe le plafond."
    citations = parse_citations(text)
    assert len(citations) == 1
    cite_id, start, end = citations[0]
    assert cite_id == "L.1235-3"
    assert text[start:end] == "[L.1235-3]"


def test_multiple_citations_in_one_sentence():
    """3. Multi-citations dans une phrase → plusieurs hits, plages distinctes."""
    text = "Selon [L.1] et [L.2-3], il faut faire X. Voir aussi [REF: D.5-6-7]."
    citations = parse_citations(text)
    assert len(citations) == 3
    ids = [c[0] for c in citations]
    assert ids == ["L.1", "L.2-3", "D.5-6-7"]
    # Plages distinctes et croissantes
    starts = [c[1] for c in citations]
    assert starts == sorted(starts)
    assert len(set(starts)) == 3


def test_build_url_uses_legifrance_search_form():
    """4. URL pointe vers la recherche Légifrance avec le numéro d'article.

    H5b — bascule depuis `codes/article_lc/{id}` (qui exigeait un LEGIARTI
    opaque) vers `search/code?searchField=NUM_ARTICLE&query=...`. Robuste,
    redirect-stable, et tombe sur une page « 0 résultat » au lieu d'un 404
    pour les articles inexistants.
    """
    url = build_url("L.1234-9")
    assert url.startswith("https://www.legifrance.gouv.fr/search/code")
    assert "searchField=NUM_ARTICLE" in url
    assert "query=L1234-9" in url  # le point est strippé pour la requête


def test_normalization_of_internal_spaces():
    """5. `[REF: L. 1234 - 9 ]` → ID normalisé `L.1234-9`."""
    text = "Article [REF: L. 1234 - 9 ] pertinent."
    citations = parse_citations(text)
    assert len(citations) == 1
    cite_id, _, _ = citations[0]
    assert cite_id == "L.1234-9"


def test_no_match_on_false_positives():
    """6. Pas de match sur `[notes]`, `[1]`, `[a]`, `[L]` seul."""
    text = "Voir [notes] et [1] mais aussi [a] ou [L] tout seul."
    citations = parse_citations(text)
    assert citations == []


def test_empty_text_returns_no_match():
    """7. Texte vide → 0 match."""
    assert parse_citations("") == []
    assert parse_citations("   \n  ") == []


# ─── H5b — Tests parser tolérant (formats émis par redacteur) ───────────────


def test_parses_short_format_no_dot():
    """9. `[L1233-8]` (sans point — émis par redacteur prompt) → détecté
    + normalisé en `L.1233-8`."""
    text = "Voir [L1233-8] pour le détail."
    citations = parse_citations(text)
    assert len(citations) == 1
    cite_id, start, end = citations[0]
    assert cite_id == "L.1233-8"
    assert text[start:end] == "[L1233-8]"


def test_parses_short_format_with_space():
    """10. `[L 1233-8]` (espace après la lettre) → détecté + normalisé."""
    text = "Article [L 1233-8] applicable."
    citations = parse_citations(text)
    assert len(citations) == 1
    assert citations[0][0] == "L.1233-8"


def test_parses_short_format_lowercase():
    """11. `[l1233-8]` / `[r1233-1]` (lowercase — format `[l1233-2]` directement
    cité dans `prompts/redacteur_system.txt:51`) → détectés + uppercase canonique."""
    text = "Cf. [l1233-8] et [r1233-1]."
    citations = parse_citations(text)
    assert len(citations) == 2
    assert citations[0][0] == "L.1233-8"
    assert citations[1][0] == "R.1233-1"


def test_parses_ref_format_short_no_dot():
    """12. `[REF: L1233-8]` (forme REF mais id sans point) → détecté."""
    text = "[REF: L1233-8]"
    citations = parse_citations(text)
    assert len(citations) == 1
    assert citations[0][0] == "L.1233-8"


def test_url_points_to_legifrance_with_article_identifier():
    """13. `build_url("L.1233-8")` pointe vers legifrance.gouv.fr et contient
    l'identifiant de l'article (vérifie l'invariant peu importe la forme exacte
    de l'URL choisie en H5b)."""
    url = build_url("L.1233-8")
    assert "legifrance.gouv.fr" in url
    # L'identifiant doit apparaître sous une forme reconnaissable
    assert "1233-8" in url
    assert "L" in url


# ─── Test apply_links — nécessite PyObjC ─────────────────────────────────────

AppKit = pytest.importorskip("AppKit")
Foundation = pytest.importorskip("Foundation")

from app.ui.legifrance_link import apply_links


def test_apply_links_adds_nslinkattribute_for_each_citation():
    """8. `apply_links(NSMutableAttributedString)` retourne le bon count
    et chaque citation a un NSLinkAttribute ouvrant l'URL Légifrance.

    H5b — l'URL utilise désormais la forme `search/code?...` sans point
    dans la query ; on vérifie l'invariant `legifrance.gouv.fr` + identifiant
    sans imposer la forme exacte.
    """
    text = "Selon [L.1234-9] et [REF: R.5-6], voir aussi [pas-une-cite]."
    attr = AppKit.NSMutableAttributedString.alloc().initWithString_(text)

    count = apply_links(attr)
    assert count == 2  # `[L.1234-9]` et `[REF: R.5-6]`, pas `[pas-une-cite]`

    # Vérifier l'URL sur le premier match
    idx = text.index("[L.1234-9]") + 1  # à l'intérieur du match
    attrs = attr.attributesAtIndex_effectiveRange_(idx, None)[0]
    link = attrs.get(AppKit.NSLinkAttributeName)
    assert link is not None
    url1 = str(link.absoluteString())
    assert "legifrance.gouv.fr" in url1
    assert "1234-9" in url1  # identifiant d'article (forme normalisée sans dot)

    # Vérifier l'URL sur le second match (R.5-6)
    idx2 = text.index("[REF: R.5-6]") + 1
    attrs2 = attr.attributesAtIndex_effectiveRange_(idx2, None)[0]
    link2 = attrs2.get(AppKit.NSLinkAttributeName)
    assert link2 is not None
    url2 = str(link2.absoluteString())
    assert "5-6" in url2
    assert "legifrance.gouv.fr" in url2
