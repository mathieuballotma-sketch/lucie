"""Tests H5 — citations Légifrance cliquables (Sprint S1, brique H5).

Couvre 8 cas du plan :
1. `[REF: L.1234-9]` détecté
2. `[L.1235-3]` (raccourci) détecté
3. Multi-citations dans une phrase
4. URL = legifrance.gouv.fr/codes/article_lc/...
5. Normalisation des espaces
6. Pas de match sur faux positifs
7. Texte vide → 0
8. apply_links retourne le bon count

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


def test_build_url_uses_legifrance_article_lc_pattern():
    """4. URL = `https://www.legifrance.gouv.fr/codes/article_lc/L.1234-9`."""
    url = build_url("L.1234-9")
    assert url == "https://www.legifrance.gouv.fr/codes/article_lc/L.1234-9"


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


# ─── Test apply_links — nécessite PyObjC ─────────────────────────────────────

AppKit = pytest.importorskip("AppKit")
Foundation = pytest.importorskip("Foundation")

from app.ui.legifrance_link import apply_links


def test_apply_links_adds_nslinkattribute_for_each_citation():
    """8. `apply_links(NSMutableAttributedString)` retourne le bon count
    et chaque citation a un NSLinkAttribute ouvrant l'URL Légifrance."""
    text = "Selon [L.1234-9] et [REF: R.5-6], voir aussi [pas-une-cite]."
    attr = AppKit.NSMutableAttributedString.alloc().initWithString_(text)

    count = apply_links(attr)
    assert count == 2  # `[L.1234-9]` et `[REF: R.5-6]`, pas `[pas-une-cite]`

    # Vérifier l'URL sur le premier match
    idx = text.index("[L.1234-9]") + 1  # à l'intérieur du match
    attrs = attr.attributesAtIndex_effectiveRange_(idx, None)[0]
    link = attrs.get(AppKit.NSLinkAttributeName)
    assert link is not None
    assert "legifrance.gouv.fr" in str(link.absoluteString())
    assert "L.1234-9" in str(link.absoluteString())

    # Vérifier l'URL sur le second match (R.5-6)
    idx2 = text.index("[REF: R.5-6]") + 1
    attrs2 = attr.attributesAtIndex_effectiveRange_(idx2, None)[0]
    link2 = attrs2.get(AppKit.NSLinkAttributeName)
    assert link2 is not None
    assert "R.5-6" in str(link2.absoluteString())
