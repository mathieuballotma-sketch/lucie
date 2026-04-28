"""
Tests UI pour le badge MemoryStore (brique N11).

Vérifie :
- extract_total_and_types tolère snapshots vides / partiels / complets
- badge formate correctement les pluriels (zéro, singulier, pluriel)
- popover liste les 5 types dans l'ordre fixe sans valeurs brutes
"""

from __future__ import annotations

from app.ui.memory_indicator import (
    extract_total_and_types,
    format_badge_text,
    format_popover_lines,
)


# ─── extract_total_and_types ─────────────────────────────────────────────────

def test_extract_from_empty_snapshot_returns_zero() -> None:
    total, types = extract_total_and_types({})
    assert total == 0
    assert types == {
        "preference": 0,
        "skill": 0,
        "goal": 0,
        "relation": 0,
        "pattern": 0,
    }


def test_extract_from_real_snapshot_structure() -> None:
    snapshot = {
        "personal": {
            "preference": [{"content": "X"}, {"content": "Y"}],
            "skill": [],
            "goal": [{"content": "Z"}],
            "relation": [],
            "pattern": [{"content": "P1"}, {"content": "P2"}],
            "_stats": {"total_nodes": 5, "generated_at": "2026-04-28T10:00:00"},
        },
        "domain_signals": {"licenciement": 0.7},
    }
    total, types = extract_total_and_types(snapshot)
    assert total == 5
    assert types["preference"] == 2
    assert types["skill"] == 0
    assert types["goal"] == 1
    assert types["pattern"] == 2


def test_extract_handles_missing_stats() -> None:
    # snapshot sans _stats : total = 0 (fallback)
    snap = {"personal": {"preference": [{"content": "x"}]}}
    total, _ = extract_total_and_types(snap)
    assert total == 0


# ─── Badge text ──────────────────────────────────────────────────────────────

def test_badge_zero_explicit_message() -> None:
    assert format_badge_text(0) == "🧠 Aucun souvenir"


def test_badge_singular() -> None:
    assert format_badge_text(1) == "🧠 1 souvenir"


def test_badge_plural() -> None:
    assert format_badge_text(8) == "🧠 8 souvenirs"


def test_badge_negative_treated_as_zero() -> None:
    # robustesse : pas de plantage si total < 0
    assert format_badge_text(-1) == "🧠 Aucun souvenir"


# ─── Popover ─────────────────────────────────────────────────────────────────

def test_popover_lists_all_5_types_in_fixed_order() -> None:
    lines = format_popover_lines({
        "preference": 3, "skill": 0, "goal": 2, "relation": 1, "pattern": 5,
    })
    # 5 types + ligne vide + note globale
    assert len(lines) == 7
    assert lines[0].endswith("préférences")
    assert lines[1].endswith("compétences")
    assert lines[2].endswith("objectifs")
    assert lines[3].endswith("relation")  # singulier (1 item)
    assert lines[4].endswith("schémas")
    assert lines[5] == ""
    assert "global" in lines[6]


def test_popover_singular_for_count_one() -> None:
    lines = format_popover_lines({"preference": 1, "skill": 0, "goal": 0, "relation": 0, "pattern": 0})
    assert lines[0] == "1 préférence"


def test_popover_does_not_leak_values() -> None:
    # Les types sont fournis comme dict counts — aucun "content" ne peut fuiter.
    lines = format_popover_lines({
        "preference": 3, "skill": 1, "goal": 0, "relation": 0, "pattern": 0,
    })
    joined = " ".join(lines)
    # Les libellés FR oui, valeurs (qui n'existent pas en counts) non
    assert "préférences" in joined
    assert "compétences" in joined or "compétence" in joined
    # Aucun chiffre suspect (genre un timestamp)
    assert "2026" not in joined
    assert "@" not in joined
