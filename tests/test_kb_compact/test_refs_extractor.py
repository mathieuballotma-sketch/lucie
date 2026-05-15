"""Test extract_refs_extended + extract_refs_from_behavior."""

from __future__ import annotations

import pytest

from lucie_v1_standalone.knowledge_legifrance.refs_extractor import (
    extract_refs_extended,
    extract_refs_from_behavior,
)


class TestBasicRefs:
    """Formes déjà couvertes par le parser retriever de base."""

    def test_simple_L_with_suffix(self) -> None:
        assert ("L", "1233-3") in extract_refs_extended("article L.1233-3")

    def test_R_no_dot(self) -> None:
        assert ("R", "4121-1") in extract_refs_extended("R4121-1 du code")

    def test_with_art_abbreviation(self) -> None:
        assert ("L", "1234-5") in extract_refs_extended("art. L1234-5")

    def test_no_prefix_no_suffix_is_noise(self) -> None:
        """Sans préfixe ni suffixe → bruit ignoré."""
        assert extract_refs_extended("paragraphe 1234 du code") == []


class TestContextualForms:
    """Nouvelles formes Sprint K-1."""

    def test_voir(self) -> None:
        refs = extract_refs_extended("Pour les détails, voir L.1234-5 du code.")
        assert ("L", "1234-5") in refs

    def test_voir_egalement(self) -> None:
        refs = extract_refs_extended("voir également L.7-1")
        assert ("L", "7-1") in refs

    def test_selon_article(self) -> None:
        refs = extract_refs_extended("selon l'article L.1233-3 issu de la jurisprudence")
        assert ("L", "1233-3") in refs

    def test_cf(self) -> None:
        refs = extract_refs_extended("cf. R.4121-3 pour le détail")
        assert ("R", "4121-3") in refs

    def test_conformement_a(self) -> None:
        refs = extract_refs_extended("conformément à l'article L.2241-5 du code du travail")
        assert ("L", "2241-5") in refs


class TestDedupAndOrder:
    def test_deduplication(self) -> None:
        text = "Article L.1233-3. Suite. Voir L.1233-3 encore."
        refs = extract_refs_extended(text)
        l_refs = [r for r in refs if r == ("L", "1233-3")]
        assert len(l_refs) == 1

    def test_preserves_first_occurrence_order(self) -> None:
        text = "selon l'article L.5-1, voir R.4121-1, voir L.5-1."
        refs = extract_refs_extended(text)
        assert refs.index(("L", "5-1")) < refs.index(("R", "4121-1"))


class TestEdgeCases:
    def test_empty_returns_empty(self) -> None:
        assert extract_refs_extended("") == []

    def test_non_str_raises(self) -> None:
        with pytest.raises(TypeError):
            extract_refs_extended(None)  # type: ignore[arg-type]

    def test_no_refs_returns_empty(self) -> None:
        assert extract_refs_extended("Texte juridique sans aucune référence numérique.") == []


class TestBenchExtraction:
    def test_extract_from_swiss_watch_behavior(self) -> None:
        behavior = (
            "Liste des 4 motifs (difficultés économiques, mutations technologiques, "
            "réorganisation, cessation), citation L.1233-3 obligatoire."
        )
        refs = extract_refs_from_behavior(behavior)
        assert ("L", "1233-3") in refs

    def test_extract_multiple_refs(self) -> None:
        behavior = "citation L.1233-3 ou L.1233-4"
        refs = extract_refs_from_behavior(behavior)
        assert ("L", "1233-3") in refs
        assert ("L", "1233-4") in refs

    def test_behavior_without_ref_returns_empty(self) -> None:
        behavior = "Refus de répondre car hors-scope du droit social."
        assert extract_refs_from_behavior(behavior) == []
