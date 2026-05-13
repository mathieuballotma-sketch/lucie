"""Tests du schéma Pydantic CorpusManifest (corpus/_schema/manifest_schema.py).

Couverture minimale 8 tests (validation positive + validations négatives par
contrainte). Le manifest mock-up `corpus/fr_pharma_ansm/manifest.yaml` sert
de cas positif réel — si ce test passe, le mock-up pharma est conforme et
prouve que le pattern Manifest-Driven Engine est instanciable hors droit social.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from corpus._schema.manifest_schema import (
    CitationKind,
    CitationPattern,
    CorpusIdentity,
    CorpusManifest,
    Source,
    SourceType,
    ValidationCriteria,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PHARMA_MANIFEST = REPO_ROOT / "corpus" / "fr_pharma_ansm" / "manifest.yaml"


def _valid_manifest_dict() -> dict:
    """Manifest minimal valide — base de tests négatifs (on mute une clé)."""
    return {
        "schema_version": "1.0",
        "identity": {
            "code": "fr_test_minimal",
            "name": "Corpus de test minimal",
            "juridiction": "fr",
            "langue": "fr",
            "autorite": "Test Authority",
        },
        "citation_patterns": [
            {
                "regex": r"\bL\.?\d+-\d+\b",
                "kind": "article-code",
                "exemple": "L.1233-3",
                "case_insensitive": True,
                "description": "Articles L. du Code du travail.",
            }
        ],
        "sources": [
            {
                "name": "legifrance",
                "url_template": "https://www.legifrance.gouv.fr/codes/article_lc/{cid}",
                "autorite_emettrice": "Légifrance / DILA",
                "type": "code",
                "placeholders": ["cid"],
            }
        ],
        "validation": {
            "verifier_score_min": 0.75,
            "citations_min": 1,
            "refuse_si_pas_de_source": True,
            "max_citations_invalides_pct": 0.0,
        },
    }


def test_manifest_valide_pharma_ansm_charge_correctement():
    """Le mock-up pharma ANSM doit charger sans erreur et exposer son identité."""
    manifest = CorpusManifest.from_yaml(PHARMA_MANIFEST)
    assert manifest.identity.code == "fr_pharma_ansm"
    assert manifest.identity.juridiction.value == "fr"
    assert "ANSM" in manifest.identity.autorite
    assert any(
        p.kind == CitationKind.ARTICLE_CODE for p in manifest.citation_patterns
    ), "manifest pharma doit contenir au moins un pattern article-code"
    assert len(manifest.sources) >= 1
    assert manifest.validation.refuse_si_pas_de_source is True


def test_manifest_rejette_cle_inconnue_extra_forbid():
    """`extra='forbid'` doit rattraper les typos de clé (truth-rule CI)."""
    raw = _valid_manifest_dict()
    raw["identity"]["email_owner"] = "x@example.com"  # clé non déclarée
    with pytest.raises(ValidationError, match="email_owner"):
        CorpusManifest.model_validate(raw)


def test_manifest_rejette_code_invalide_double_underscore():
    """Validator custom : le code ne doit pas contenir '__'."""
    raw = _valid_manifest_dict()
    raw["identity"]["code"] = "fr__pharma"
    with pytest.raises(ValidationError, match="double underscore|__"):
        CorpusManifest.model_validate(raw)


def test_citation_pattern_rejette_regex_invalide():
    """Validator `_regex_compiles` doit rattraper les regex malformées."""
    with pytest.raises(ValidationError, match="regex invalide"):
        CitationPattern(
            regex="[invalid(",
            kind=CitationKind.ARTICLE_CODE,
            exemple="L.1233-3",
        )


def test_citation_pattern_exemple_doit_matcher_regex():
    """Model validator : l'exemple canonique doit matcher la regex (cohérence)."""
    with pytest.raises(ValidationError, match="ne matche pas"):
        CitationPattern(
            regex=r"^L\.\d+$",
            kind=CitationKind.ARTICLE_CODE,
            exemple="ZZZ-no-match",
        )


def test_source_url_template_placeholders_coherents():
    """Tout placeholder déclaré doit apparaître dans le template URL."""
    with pytest.raises(ValidationError, match="placeholder 'cid' absent"):
        Source(
            name="bad_source",
            url_template="https://example.com/no-placeholder",
            autorite_emettrice="Test",
            type=SourceType.CODE,
            placeholders=["cid"],
        )


def test_manifest_exige_au_moins_un_pattern_article_code():
    """Model validator racine : ≥1 citation_pattern de kind='article-code'."""
    raw = _valid_manifest_dict()
    raw["citation_patterns"][0]["kind"] = "autre"
    raw["citation_patterns"][0]["regex"] = r"\bautre\b"
    raw["citation_patterns"][0]["exemple"] = "autre"
    with pytest.raises(ValidationError, match="article-code"):
        CorpusManifest.model_validate(raw)


def test_manifest_frozen_immutable():
    """`frozen=True` doit empêcher toute mutation post-load."""
    manifest = CorpusManifest.from_yaml(PHARMA_MANIFEST)
    with pytest.raises(ValidationError):
        manifest.identity = CorpusIdentity(  # type: ignore[misc]
            code="fr_other",
            name="Other",
            juridiction="fr",
            langue="fr",
            autorite="Other",
        )


def test_manifest_rejette_schema_version_non_supporte():
    """Bonus : un schema_version inconnu doit être rejeté explicitement."""
    raw = _valid_manifest_dict()
    raw["schema_version"] = "9.9"
    with pytest.raises(ValidationError, match="schema_version non supporté|9.9"):
        CorpusManifest.model_validate(raw)


def test_validation_criteria_score_min_bounds():
    """Bonus : verifier_score_min doit être dans [0, 1]."""
    with pytest.raises(ValidationError):
        ValidationCriteria(
            verifier_score_min=1.5,
            citations_min=1,
        )
    with pytest.raises(ValidationError):
        ValidationCriteria(
            verifier_score_min=-0.1,
            citations_min=1,
        )


def test_manifest_pharma_themes_yaml_loadable():
    """Bonus : themes.yaml du corpus pharma doit être YAML valide et structuré."""
    themes_path = REPO_ROOT / "corpus" / "fr_pharma_ansm" / "themes.yaml"
    with themes_path.open(encoding="utf-8") as f:
        themes = yaml.safe_load(f)
    assert themes["version"] == "1.0"
    assert "publicite_medicaments" in themes["themes"]
    assert "amm_autorisation" in themes["themes"]
    assert isinstance(themes["themes"]["publicite_medicaments"]["mots_cles"], list)
