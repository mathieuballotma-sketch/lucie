"""
Tests — DialogueManager skeleton (3 tests de structure).
"""

from __future__ import annotations

from lucie_v1_standalone.dialogue.dialogue_manager import DialogueManager


def test_initial_state() -> None:
    """Le manager est initialisé avec le bon domaine et un état vide."""
    mgr = DialogueManager("licenciement_economique")
    assert mgr.state.domain == "licenciement_economique"
    assert mgr.state.info_collected == {}
    assert mgr.state.info_missing == []
    assert mgr.state.turn_count == 0
    assert mgr.is_complete  # rien de manquant → complet


def test_needs_clarification_and_next_question() -> None:
    """Avec des infos manquantes, needs_clarification() et next_question() fonctionnent."""
    mgr = DialogueManager("licenciement_economique")
    mgr.state.info_missing = ["effectif de l'entreprise", "ancienneté"]

    assert mgr.needs_clarification("j'ai été licencié")
    q = mgr.next_question()
    assert q is not None
    assert "effectif" in q or "ancienneté" in q


def test_mark_answered_removes_from_missing() -> None:
    """mark_answered() met à jour info_collected et retire l'item de info_missing."""
    mgr = DialogueManager("licenciement_economique")
    mgr.state.info_missing = ["ancienneté", "effectif"]

    mgr.mark_answered("ancienneté", "5 ans")
    assert "ancienneté" in mgr.state.info_collected
    assert mgr.state.info_collected["ancienneté"] == "5 ans"
    assert "ancienneté" not in mgr.state.info_missing
    assert mgr.state.turn_count == 1
    assert not mgr.is_complete  # "effectif" encore manquant

    mgr.mark_answered("effectif", 80)
    assert mgr.is_complete
    assert mgr.state.turn_count == 2
