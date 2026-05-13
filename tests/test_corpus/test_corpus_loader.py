"""Tests de la couche de découverte additive `lucie_v1_standalone.corpus`.

Couvre :
  - chargement du mock-up fr_pharma_ansm (cas nominal)
  - auto-discovery (themes.yaml / refusals.yaml absents)
  - patterns de citation inférés depuis filenames
  - erreurs (corpus manquant, manifest incohérent)
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from lucie_v1_standalone.corpus import (
    CorpusLoader,
    CorpusLoadError,
    CorpusNotFoundError,
    load_corpus,
)


def test_load_corpus_pharma_ansm_nominal():
    corpus = load_corpus("fr_pharma_ansm")
    assert corpus.manifest.identity.code == "fr_pharma_ansm"
    assert "ANSM" in corpus.manifest.identity.autorite
    assert len(corpus.articles) == 5
    article_ids = {a.id for a in corpus.articles}
    assert article_ids == {"L5111-1", "L5121-8", "L5122-1", "L5122-6", "L5122-9"}
    assert "publicite_medicaments" in corpus.themes
    assert corpus.refusals.scope_refusal.strip().startswith("Cette requête sort")
    assert len(corpus.refusals.priority_override_patterns) >= 3


def test_available_codes_lists_only_real_corpora():
    loader = CorpusLoader()
    codes = loader.available_codes()
    assert "fr_pharma_ansm" in codes
    assert all(not c.startswith("_") for c in codes)


def test_load_unknown_corpus_raises_not_found():
    with pytest.raises(CorpusNotFoundError, match="introuvable"):
        load_corpus("zz_inexistant")


def _write_minimal_manifest(corpus_dir: Path, code: str) -> None:
    (corpus_dir / "manifest.yaml").write_text(
        textwrap.dedent(
            f"""
            schema_version: "1.0"
            identity:
              code: {code}
              name: "Corpus minimal de test"
              juridiction: fr
              langue: fr
              autorite: "Test Authority"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def test_auto_discovery_when_themes_and_refusals_absent(tmp_path: Path, monkeypatch):
    """Manifest minimal (5 champs) + articles + ni themes.yaml ni refusals.yaml :
    le loader doit produire un Corpus valide via auto-discovery."""
    fake_root = tmp_path / "corpus"
    (fake_root / "_schema").mkdir(parents=True)
    (fake_root / "_schema" / "__init__.py").write_text("")
    code = "fr_test_auto"
    corpus_dir = fake_root / code
    (corpus_dir / "articles").mkdir(parents=True)
    _write_minimal_manifest(corpus_dir, code)
    (corpus_dir / "articles" / "L5111-1.md").write_text(
        "# Article L.5111-1 — Définition du médicament\n\n## Résumé opérationnel\n\nDéfinit le médicament.\n",
        encoding="utf-8",
    )
    (corpus_dir / "articles" / "L5121-8.md").write_text(
        "# Article L.5121-8 — Autorisation de mise sur le marché\n\n## Résumé opérationnel\n\nAMM obligatoire.\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BEAUME_CORPUS_ROOT", str(fake_root))
    corpus = load_corpus(code)
    assert len(corpus.articles) == 2
    assert corpus.themes  # inférés depuis titres
    assert corpus.refusals.scope_refusal.startswith("Cette requête sort")
    assert corpus.inferred_citation_patterns, "patterns devraient être inférés depuis filenames L5111-1.md"


def test_auto_discovery_corpus_without_articles_does_not_crash(tmp_path: Path, monkeypatch):
    fake_root = tmp_path / "corpus"
    (fake_root / "_schema").mkdir(parents=True)
    code = "fr_empty"
    corpus_dir = fake_root / code
    corpus_dir.mkdir(parents=True)
    _write_minimal_manifest(corpus_dir, code)
    monkeypatch.setenv("BEAUME_CORPUS_ROOT", str(fake_root))
    corpus = load_corpus(code)
    assert corpus.articles == ()
    assert corpus.themes == {}  # inférence impossible


def test_load_rejects_mismatched_code_in_manifest(tmp_path: Path, monkeypatch):
    fake_root = tmp_path / "corpus"
    (fake_root / "_schema").mkdir(parents=True)
    folder_code = "fr_folder_name"
    corpus_dir = fake_root / folder_code
    corpus_dir.mkdir(parents=True)
    _write_minimal_manifest(corpus_dir, code="fr_manifest_says_other")
    monkeypatch.setenv("BEAUME_CORPUS_ROOT", str(fake_root))
    with pytest.raises(CorpusLoadError, match="ne matche pas"):
        load_corpus(folder_code)


def test_minimal_manifest_only_5_required_fields(tmp_path: Path, monkeypatch):
    """Un manifest avec uniquement schema_version + identity (5 champs) doit charger."""
    fake_root = tmp_path / "corpus"
    (fake_root / "_schema").mkdir(parents=True)
    code = "fr_minimal_5"
    corpus_dir = fake_root / code
    (corpus_dir / "articles").mkdir(parents=True)
    _write_minimal_manifest(corpus_dir, code)
    (corpus_dir / "articles" / "L0001-1.md").write_text("# Test\n", encoding="utf-8")
    monkeypatch.setenv("BEAUME_CORPUS_ROOT", str(fake_root))
    corpus = load_corpus(code)
    assert corpus.manifest.citation_patterns == []
    assert corpus.manifest.sources == []
    assert corpus.manifest.validation.refuse_si_pas_de_source is False
