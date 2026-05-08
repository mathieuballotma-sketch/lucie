"""Tests du module ``app.ui.copy_format`` — formatage Markdown → texte pro."""

from __future__ import annotations

from app.ui.copy_format import (
    _code_for_article,
    _normalize_article,
    format_response_for_copy,
)


# ── Citations ────────────────────────────────────────────────────────────────


def test_replace_ref_with_prefix() -> None:
    txt = "Selon [REF: L.1232-1], le licenciement..."
    out = format_response_for_copy(txt)
    assert out == "Selon (L.1232-1 du Code du travail), le licenciement..."


def test_replace_ref_without_prefix() -> None:
    txt = "Voir [L.1234-9] pour le préavis."
    out = format_response_for_copy(txt)
    assert out == "Voir (L.1234-9 du Code du travail) pour le préavis."


def test_replace_ref_compact_form() -> None:
    """`[L1232-1]` (sans point) doit être normalisé à `L.1232-1`."""
    out = format_response_for_copy("Article [L1232-1] applicable.")
    assert out == "Article (L.1232-1 du Code du travail) applicable."


def test_replace_ref_lowercase() -> None:
    out = format_response_for_copy("[l.1232-1] applicable.")
    assert out == "(L.1232-1 du Code du travail) applicable."


def test_multiple_refs_in_paragraph() -> None:
    txt = "Selon [REF: L.1232-1] et [L.1233-3], la procédure..."
    out = format_response_for_copy(txt)
    assert "(L.1232-1 du Code du travail)" in out
    assert "(L.1233-3 du Code du travail)" in out


# ── Markdown stripping ───────────────────────────────────────────────────────


def test_strip_bold() -> None:
    out = format_response_for_copy("Le **CDI** est la règle.")
    assert out == "Le CDI est la règle."


def test_strip_italic() -> None:
    out = format_response_for_copy("Le *préavis* est obligatoire.")
    assert out == "Le préavis est obligatoire."


def test_strip_heading() -> None:
    out = format_response_for_copy("## Réponse\nLe préavis est de 2 mois.")
    assert out == "Réponse\nLe préavis est de 2 mois."


def test_strip_code_inline() -> None:
    out = format_response_for_copy("Voir le `keep_alive=24h`.")
    assert out == "Voir le keep_alive=24h."


def test_list_items_to_bullets() -> None:
    out = format_response_for_copy("- premier\n- second")
    assert out == "• premier\n• second"


# ── Empty / edge cases ───────────────────────────────────────────────────────


def test_empty_string() -> None:
    assert format_response_for_copy("") == ""


def test_no_markdown_no_citation() -> None:
    txt = "Une simple phrase sans rien."
    assert format_response_for_copy(txt) == "Une simple phrase sans rien."


def test_realistic_response() -> None:
    """Réponse type juridique avec gras + 2 citations + liste."""
    src = (
        "## Réponse\n"
        "Pour un salarié avec **3 ans d'ancienneté**, le préavis est de "
        "2 mois [REF: L.1234-1].\n\n"
        "## Points clés\n"
        "- Préavis : 2 mois [L.1234-1]\n"
        "- Indemnité légale : 1/4 mois par année [REF: L.1234-9]"
    )
    out = format_response_for_copy(src)
    assert "**" not in out
    assert "[REF:" not in out
    assert "## " not in out
    assert "(L.1234-1 du Code du travail)" in out
    assert "(L.1234-9 du Code du travail)" in out
    assert "• Préavis" in out


# ── Internals ────────────────────────────────────────────────────────────────


def test_normalize_article_variants() -> None:
    assert _normalize_article("L.1232-1") == "L.1232-1"
    assert _normalize_article("L1232-1") == "L.1232-1"
    assert _normalize_article("L 1232 1") == "L.1232-1"
    assert _normalize_article("l.1232-1") == "L.1232-1"
    assert _normalize_article("L1232") == "L.1232"


def test_code_for_article_droit_social() -> None:
    assert _code_for_article("L.1232-1") == "Code du travail"
    assert _code_for_article("L.1234-9") == "Code du travail"
