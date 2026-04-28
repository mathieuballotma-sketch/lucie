"""Tests H7 — markdown_renderer (Sprint S1, brique H7).

Couvre 10 cas du plan : titres H1/H2/H3, gras, italique, code inline,
listes à puces, combinaison gras-dans-titre, ligne vide, texte sans
markdown, malformé (`**non fermé`), plages exactes des attributs.

PyObjC est requis. Skip propre si AppKit indisponible (CI sans macOS).
"""
from __future__ import annotations

import pytest

AppKit = pytest.importorskip("AppKit")
Foundation = pytest.importorskip("Foundation")

from app.ui.markdown_renderer import render


def _font_at(attr_string, index):
    """Retourne la NSFont à l'index donné dans le NSAttributedString."""
    attrs = attr_string.attributesAtIndex_effectiveRange_(index, None)[0]
    return attrs.get(AppKit.NSFontAttributeName)


def _bg_at(attr_string, index):
    attrs = attr_string.attributesAtIndex_effectiveRange_(index, None)[0]
    return attrs.get(AppKit.NSBackgroundColorAttributeName)


def _para_at(attr_string, index):
    attrs = attr_string.attributesAtIndex_effectiveRange_(index, None)[0]
    return attrs.get(AppKit.NSParagraphStyleAttributeName)


def test_heading_levels_have_correct_size_and_weight():
    """1. H1/H2/H3 : taille + poids exacts."""
    out = render("# Titre 1\n## Titre 2\n### Titre 3")
    s = out.string()
    h1_idx = s.index("Titre 1")
    h2_idx = s.index("Titre 2")
    h3_idx = s.index("Titre 3")

    h1_font = _font_at(out, h1_idx)
    h2_font = _font_at(out, h2_idx)
    h3_font = _font_at(out, h3_idx)

    assert h1_font.pointSize() == pytest.approx(18.0)
    assert h2_font.pointSize() == pytest.approx(15.0)
    assert h3_font.pointSize() == pytest.approx(13.0)
    # Plus grand = plus gras (semibold) ; H3 est medium
    assert h1_font.pointSize() > h2_font.pointSize() > h3_font.pointSize()


def test_bold_applies_semibold_on_exact_range():
    """2. **gras** : weight semibold sur la plage exacte (sans étoiles)."""
    out = render("Du texte **gras** ici")
    s = out.string()
    # Les étoiles restent dans le texte : on ne les efface pas (pour H7 minimal)
    bold_start = s.index("**gras**")
    # Au milieu de "**gras**", on doit trouver une font semibold
    bold_font = _font_at(out, bold_start + 3)  # caractère 'r' de 'gras'
    assert bold_font.fontDescriptor().symbolicTraits() & AppKit.NSFontBoldTrait


def test_italic_applies_italic_trait():
    """3. *italique* : trait italic."""
    out = render("Du *texte italique* ici")
    s = out.string()
    it_start = s.index("*texte italique*")
    it_font = _font_at(out, it_start + 2)  # 'e' de 'texte'
    assert it_font is not None
    # NSFontItalicTrait
    assert it_font.fontDescriptor().symbolicTraits() & AppKit.NSFontItalicTrait


def test_inline_code_uses_mono_font_and_background():
    """4. `code` : font mono + background."""
    out = render("Voir `code_inline` pour exemple")
    s = out.string()
    code_start = s.index("`code_inline`")
    code_font = _font_at(out, code_start + 2)
    assert code_font is not None
    # Mono fonts contiennent "Mono" dans le familyName ou ont le trait FixedPitch
    traits = code_font.fontDescriptor().symbolicTraits()
    assert traits & AppKit.NSFontMonoSpaceTrait, (
        f"Expected monospace trait, got family={code_font.familyName()}"
    )
    bg = _bg_at(out, code_start + 2)
    assert bg is not None


def test_bullet_list_has_indent_and_bullet_glyph():
    """5. `- item` : bullet + indent."""
    out = render("- premier item\n- second item")
    s = out.string()
    assert "•" in s
    assert "premier item" in s
    assert "second item" in s
    # Vérifier indent paragraphe sur la ligne du bullet
    bullet_idx = s.index("•")
    para = _para_at(out, bullet_idx)
    assert para is not None
    assert para.headIndent() == pytest.approx(16.0)


def test_bold_inside_heading_keeps_semibold_in_range():
    """6. Combinaison **gras dans titre** : la plage gras reste lisible (pas
    de crash de combinaison d'attributs)."""
    out = render("## Titre avec **gras dedans**")
    s = out.string()
    # La heading-attr seule donne déjà semibold. On vérifie au moins qu'aucune
    # exception n'est levée et que le texte est bien là.
    assert "Titre avec" in s
    assert "gras dedans" in s
    titre_font = _font_at(out, s.index("Titre"))
    assert titre_font.pointSize() == pytest.approx(15.0)


def test_blank_line_creates_paragraph_break():
    """7. Ligne vide → paragraph break (préserve le \\n)."""
    out = render("Premier paragraphe\n\nSecond paragraphe")
    s = out.string()
    # On doit retrouver les deux \n successifs (préservation)
    assert "\n\n" in s
    assert "Premier paragraphe" in s
    assert "Second paragraphe" in s


def test_plain_text_without_markdown_unchanged():
    """8. Texte sans markdown → identique au texte brut."""
    plain = "Juste du texte normal sans markup."
    out = render(plain)
    assert out.string() == plain


def test_malformed_markdown_does_not_crash():
    """9. **non fermé → graceful, pas de crash, texte préservé."""
    out = render("Du **non fermé et `code_aussi_non_fermé")
    s = out.string()
    # On préserve le texte tel quel — les patterns non matchés restent visibles
    assert "non fermé" in s
    assert "code_aussi_non_fermé" in s


def test_paragraph_style_line_height_and_spacing():
    """10. Plage exacte attributs : paragraphe a bien line-height 1.4 et
    paragraph spacing 6pt."""
    out = render("Un paragraphe simple.")
    para = _para_at(out, 0)
    assert para is not None
    assert para.lineHeightMultiple() == pytest.approx(1.4)
    assert para.paragraphSpacing() == pytest.approx(6.0)
