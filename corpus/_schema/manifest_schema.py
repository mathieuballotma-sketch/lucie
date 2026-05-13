"""Schéma Pydantic v2 d'un manifest corpus Beaume.

Convention over Configuration : un corpus = un dossier `corpus/<code>/`
contenant `manifest.yaml`, `articles/`, `themes.yaml`, `refusals.yaml`,
`prompts/`, et optionnellement `strategies/` (overrides Python).

Le schéma est volontairement strict (extra='forbid') pour empêcher tout
hardcoding silencieux : une clé manifest non reconnue échoue en CI.

Usage :
    from corpus._schema.manifest_schema import CorpusManifest
    manifest = CorpusManifest.from_yaml(Path("corpus/fr_droit_travail/manifest.yaml"))
"""
from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0"})


class Juridiction(str, Enum):
    """Juridictions supportées. Chaque ajout doit avoir une batterie de tests."""

    FR = "fr"
    FR_OM = "fr-om"
    UE = "ue"


class SourceType(str, Enum):
    CODE = "code"
    DECRET = "decret"
    ARRETE = "arrete"
    DIRECTIVE_UE = "directive-ue"
    JURISPRUDENCE = "jurisprudence"
    DOCTRINE = "doctrine"
    RECOMMANDATION_AUTORITE = "recommandation-autorite"


class CitationKind(str, Enum):
    """Famille de citation. Le moteur les traite identiquement ;
    cette enum sert au logging et à l'UI."""

    ARTICLE_CODE = "article-code"
    REGLEMENT = "reglement"
    DECRET = "decret"
    AUTRE = "autre"


class CorpusIdentity(BaseModel):
    """Identité métier du corpus, affichée dans l'UI et les refus."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    code: str = Field(
        ...,
        pattern=r"^[a-z]{2}(?:-[a-z]{2})?_[a-z0-9_]+$",
        description="Slug machine, ex: 'fr_droit_travail', 'fr_pharma_ansm'.",
    )
    name: str = Field(..., min_length=3, max_length=120)
    juridiction: Juridiction
    langue: str = Field(default="fr", pattern=r"^[a-z]{2}$")
    autorite: str = Field(
        ...,
        min_length=2,
        description="Autorité émettrice principale (Légifrance, ANSM, AMF, ...).",
    )

    @field_validator("code")
    @classmethod
    def _code_no_double_underscore(cls, v: str) -> str:
        if "__" in v:
            raise ValueError("code ne doit pas contenir '__'")
        return v


class CitationPattern(BaseModel):
    """Une regex de détection de citation juridique.

    Le moteur (verificateur, intent_classifier, retriever) consomme la liste
    `citation_patterns` du manifest pour construire `re.compile(...)` une seule
    fois au démarrage.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    regex: str = Field(..., min_length=3)
    kind: CitationKind
    exemple: str = Field(..., min_length=1)
    case_insensitive: bool = True
    description: str = ""

    @field_validator("regex")
    @classmethod
    def _regex_compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"regex invalide: {e}")
        return v

    @model_validator(mode="after")
    def _exemple_matches_regex(self) -> "CitationPattern":
        flags = re.IGNORECASE if self.case_insensitive else 0
        if not re.search(self.regex, self.exemple, flags):
            raise ValueError(
                f"exemple '{self.exemple}' ne matche pas regex '{self.regex}'"
            )
        return self


class Source(BaseModel):
    """Source primaire (URL canonique + autorité)."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    name: str = Field(..., min_length=2)
    url_template: str = Field(
        ...,
        min_length=10,
        description="Template avec placeholder, ex: "
        "'https://www.legifrance.gouv.fr/codes/article_lc/{cid}'.",
    )
    autorite_emettrice: str = Field(..., min_length=2)
    type: SourceType
    placeholders: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _placeholders_in_template(self) -> "Source":
        for p in self.placeholders:
            if f"{{{p}}}" not in self.url_template:
                raise ValueError(
                    f"placeholder '{p}' absent du url_template '{self.url_template}'"
                )
        return self


class ValidationCriteria(BaseModel):
    """Seuils déterministes consommés par le Verificateur."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    verifier_score_min: float = Field(..., ge=0.0, le=1.0)
    citations_min: int = Field(..., ge=0)
    refuse_si_pas_de_source: bool = True
    max_citations_invalides_pct: float = Field(default=0.0, ge=0.0, le=1.0)


class CorpusPaths(BaseModel):
    """Chemins relatifs au dossier corpus (résolus au load)."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    articles: str = "articles/"
    themes: str = "themes.yaml"
    refusals: str = "refusals.yaml"
    prompts: str = "prompts/"
    strategies: str | None = None


DEFAULT_VALIDATION = ValidationCriteria(
    verifier_score_min=0.5,
    citations_min=0,
    refuse_si_pas_de_source=False,
    max_citations_invalides_pct=1.0,
)


class CorpusManifest(BaseModel):
    """Manifest racine. Chargé une fois au démarrage, immuable.

    Convention sur 5 champs obligatoires : `schema_version`, `identity` (qui
    contient code/name/juridiction/langue/autorite). Tout le reste est
    optionnel et fait l'objet d'une auto-discovery par le `CorpusLoader`
    (citation_patterns inférés depuis filenames articles, sources fallback
    Légifrance, validation seuils par défaut permissifs).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: str = Field(..., pattern=r"^\d+\.\d+$")
    identity: CorpusIdentity
    citation_patterns: list[CitationPattern] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    validation: ValidationCriteria = Field(default=DEFAULT_VALIDATION)
    paths: CorpusPaths = Field(default_factory=CorpusPaths)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _supported_version(cls, v: str) -> str:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"schema_version non supporté: {v} "
                f"(supportés: {sorted(SUPPORTED_SCHEMA_VERSIONS)})"
            )
        return v

    @model_validator(mode="after")
    def _patterns_must_include_article_code_if_provided(self) -> "CorpusManifest":
        if self.citation_patterns and not any(
            p.kind == CitationKind.ARTICLE_CODE for p in self.citation_patterns
        ):
            raise ValueError(
                "si citation_patterns est fourni, il doit contenir au moins un "
                "pattern de kind='article-code'"
            )
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> "CorpusManifest":
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)
