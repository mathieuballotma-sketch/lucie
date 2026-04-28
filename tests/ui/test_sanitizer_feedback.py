"""
Tests UI pour le badge PII (brique N9).

Vérifie que :
- detect_pii() compte correctement par catégorie (input combiné)
- le formatage du badge et de la popover ne fuite **jamais** les valeurs PII
- les libellés français sont corrects au pluriel/singulier
"""

from __future__ import annotations

from app.ui.pii_indicator import (
    format_badge_text,
    format_popover_lines,
    total_pii,
)
from lucie_v1_standalone.memory.sanitizer import detect_pii


# ─── detect_pii (intégration) ────────────────────────────────────────────────

def test_detect_pii_input_combined_2_emails_1_siret() -> None:
    text = "alice@x.fr et bob@y.fr — SIRET 12345678901234"
    counts = detect_pii(text)
    assert counts.get("EMAIL") == 2
    assert counts.get("SIRET", 0) >= 1


def test_detect_pii_no_pii_returns_empty() -> None:
    assert detect_pii("texte parfaitement neutre") == {}


# ─── total_pii ───────────────────────────────────────────────────────────────

def test_total_pii_sums_all_categories() -> None:
    assert total_pii({"EMAIL": 2, "SIRET": 1, "NOM": 3}) == 6


def test_total_pii_zero_on_empty() -> None:
    assert total_pii({}) == 0


# ─── Badge text ──────────────────────────────────────────────────────────────

def test_badge_zero_pii_explicit_message() -> None:
    assert format_badge_text({}) == "🔒 0 PII détectée"


def test_badge_singular_pii() -> None:
    assert format_badge_text({"EMAIL": 1}) == "🔒 1 PII masquée"


def test_badge_plural_pii_aggregates_total() -> None:
    text = format_badge_text({"EMAIL": 2, "SIRET": 1})
    assert text == "🔒 3 PII masquées"


# ─── Popover ─────────────────────────────────────────────────────────────────

def test_popover_lists_categories_not_values() -> None:
    text = "Mme Dupont — alice@cabinet.fr — SIRET 12345678901234"
    counts = detect_pii(text)
    lines = format_popover_lines(counts)
    joined = " ".join(lines)
    # Aucune valeur réelle dans la popover
    assert "Dupont" not in joined
    assert "alice@cabinet.fr" not in joined
    assert "12345678901234" not in joined
    # Mais les catégories oui
    assert any("email" in ln for ln in lines)
    assert any("SIRET" in ln for ln in lines)


def test_popover_empty_when_no_pii_detected() -> None:
    lines = format_popover_lines({})
    assert len(lines) == 1
    assert "Aucune donnée personnelle" in lines[0]


def test_popover_sorted_by_count_descending() -> None:
    lines = format_popover_lines({"EMAIL": 1, "NOM": 3, "SIRET": 2})
    # NOM (3) en premier, puis SIRET (2), puis EMAIL (1)
    assert lines[0].startswith("3 ")
    assert lines[1].startswith("2 ")
    assert lines[2].startswith("1 ")


def test_popover_pluralizes_french_labels() -> None:
    lines = format_popover_lines({"EMAIL": 2})
    assert lines == ["2 emails"]
    lines = format_popover_lines({"EMAIL": 1})
    assert lines == ["1 email"]
