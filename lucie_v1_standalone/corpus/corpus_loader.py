"""CorpusLoader — découverte et chargement additif d'un corpus Beaume.

Convention over Configuration : `corpus/<code>/` contient le manifest et les
fichiers data. Le loader applique une auto-discovery quand les fichiers
optionnels (`themes.yaml`, `refusals.yaml`) sont absents.

5 champs strictement obligatoires dans le manifest : schema_version, identity
(qui regroupe code/name/juridiction/langue/autorite). Tout le reste est
inférable :
  - citation_patterns absent → inférés depuis filenames articles (préfixe L/R/D + numéro)
  - themes absent → cluster simple par titre d'article
  - refusals absent → fallback générique mentionnant l'autorité du corpus

Aucune dépendance vers le moteur droit social (`router`, `verificateur`, etc.).
Le loader peut être appelé en mode standalone, hors pipeline.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from corpus._schema.manifest_schema import (
    CitationKind,
    CitationPattern,
    CorpusManifest,
)

logger = logging.getLogger(__name__)


CORPUS_ROOT_ENV_VAR = "BEAUME_CORPUS_ROOT"
DEFAULT_CORPUS_ROOT_NAMES = ("corpus",)
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_FILENAME_CITATION_RE = re.compile(r"^([LRD])(\d{3,5})(?:-(\d+))?", re.IGNORECASE)


class CorpusLoadError(Exception):
    """Erreur de chargement du corpus (manifest invalide, articles manquants, etc.)."""


class CorpusNotFoundError(CorpusLoadError):
    """Le dossier corpus/<code>/ n'existe pas."""


@dataclass(frozen=True)
class Article:
    """Un article markdown du corpus (chargé en mémoire)."""

    id: str
    path: Path
    title: str
    content: str
    tokens: tuple[str, ...]

    @property
    def tokens_set(self) -> frozenset[str]:
        return frozenset(self.tokens)


@dataclass(frozen=True)
class ThemeInfo:
    """Un thème : libellé + mots-clés (déclarés ou inférés)."""

    code: str
    libelle: str
    mots_cles: tuple[str, ...]


@dataclass(frozen=True)
class RefusalsConfig:
    """Refus + redirections par domaine + priority_override patterns compilés."""

    scope_refusal: str
    domains: dict[str, tuple[tuple[str, ...], str]]
    priority_override_patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class Corpus:
    """Un corpus chargé en mémoire — entrée principale de la couche additive."""

    manifest: CorpusManifest
    root: Path
    articles: tuple[Article, ...]
    themes: dict[str, ThemeInfo]
    refusals: RefusalsConfig
    inferred_citation_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)


def _find_corpus_root(start: Path | None = None) -> Path:
    """Localise le répertoire `corpus/` racine en remontant depuis `start` (ou cwd).

    Permet override par `BEAUME_CORPUS_ROOT` (utile pour les tests qui veulent
    pointer vers une arborescence fixture).
    """
    import os

    override = os.environ.get(CORPUS_ROOT_ENV_VAR)
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_dir():
            raise CorpusLoadError(
                f"{CORPUS_ROOT_ENV_VAR}={override} ne pointe pas vers un répertoire"
            )
        return path

    cursor = (start or Path.cwd()).resolve()
    for candidate in (cursor, *cursor.parents):
        for name in DEFAULT_CORPUS_ROOT_NAMES:
            corpus_dir = candidate / name
            if corpus_dir.is_dir() and (corpus_dir / "_schema").is_dir():
                return corpus_dir
    raise CorpusLoadError(
        "Répertoire `corpus/` introuvable. Lance depuis la racine du repo "
        f"ou positionne {CORPUS_ROOT_ENV_VAR}=/chemin/vers/corpus."
    )


class CorpusLoader:
    """Charge un corpus depuis disque avec auto-discovery des fichiers optionnels."""

    def __init__(self, corpus_root: Path | None = None) -> None:
        self._corpus_root = corpus_root or _find_corpus_root()

    @property
    def corpus_root(self) -> Path:
        return self._corpus_root

    def available_codes(self) -> list[str]:
        """Liste les codes corpus disponibles (sous-dossiers hors `_schema/`)."""
        return sorted(
            p.name
            for p in self._corpus_root.iterdir()
            if p.is_dir() and not p.name.startswith("_") and (p / "manifest.yaml").is_file()
        )

    def load(self, code: str) -> Corpus:
        corpus_dir = self._corpus_root / code
        if not corpus_dir.is_dir():
            available = self.available_codes()
            raise CorpusNotFoundError(
                f"Corpus '{code}' introuvable dans {self._corpus_root}. "
                f"Disponibles : {available}"
            )
        manifest_path = corpus_dir / "manifest.yaml"
        if not manifest_path.is_file():
            raise CorpusLoadError(f"manifest.yaml absent dans {corpus_dir}")

        manifest = CorpusManifest.from_yaml(manifest_path)
        if manifest.identity.code != code:
            raise CorpusLoadError(
                f"manifest.identity.code='{manifest.identity.code}' ne matche pas "
                f"le nom du dossier '{code}'"
            )

        articles = self._load_articles(corpus_dir, manifest.paths.articles)
        themes = self._load_or_infer_themes(corpus_dir, manifest.paths.themes, articles)
        refusals = self._load_or_fallback_refusals(
            corpus_dir, manifest.paths.refusals, manifest
        )
        inferred = self._inferred_citation_patterns(manifest, articles)

        logger.info(
            "corpus.loaded code=%s articles=%d themes=%d inferred_patterns=%d",
            code,
            len(articles),
            len(themes),
            len(inferred),
        )
        return Corpus(
            manifest=manifest,
            root=corpus_dir,
            articles=articles,
            themes=themes,
            refusals=refusals,
            inferred_citation_patterns=inferred,
        )

    @staticmethod
    def _load_articles(corpus_dir: Path, articles_subdir: str) -> tuple[Article, ...]:
        articles_dir = corpus_dir / articles_subdir
        if not articles_dir.is_dir():
            logger.warning("articles dir absent: %s — corpus sans articles", articles_dir)
            return tuple()
        out: list[Article] = []
        for md_path in sorted(articles_dir.rglob("*.md")):
            try:
                content = md_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:
                logger.warning("article illisible: %s (%s)", md_path, exc)
                continue
            title_match = _TITLE_RE.search(content)
            title = title_match.group(1).strip() if title_match else md_path.stem
            tokens = tuple(_TOKEN_RE.findall(content.lower()))
            out.append(
                Article(
                    id=md_path.stem,
                    path=md_path,
                    title=title,
                    content=content,
                    tokens=tokens,
                )
            )
        return tuple(out)

    @staticmethod
    def _load_or_infer_themes(
        corpus_dir: Path,
        themes_path_rel: str,
        articles: Iterable[Article],
    ) -> dict[str, ThemeInfo]:
        themes_path = corpus_dir / themes_path_rel
        if themes_path.is_file():
            with themes_path.open(encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            return _parse_themes_yaml(raw)

        logger.info("themes.yaml absent dans %s — auto-discovery par titre", corpus_dir)
        return _infer_themes_from_articles(articles)

    @staticmethod
    def _load_or_fallback_refusals(
        corpus_dir: Path,
        refusals_path_rel: str,
        manifest: CorpusManifest,
    ) -> RefusalsConfig:
        refusals_path = corpus_dir / refusals_path_rel
        if refusals_path.is_file():
            with refusals_path.open(encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            return _parse_refusals_yaml(raw, manifest)

        logger.info(
            "refusals.yaml absent dans %s — fallback générique", corpus_dir
        )
        generic = (
            f"Cette requête sort du périmètre du corpus « {manifest.identity.name} » "
            f"(autorité : {manifest.identity.autorite}). Reformulez ou consultez "
            f"un corpus mieux adapté."
        )
        return RefusalsConfig(
            scope_refusal=generic,
            domains={},
            priority_override_patterns=tuple(),
        )

    @staticmethod
    def _inferred_citation_patterns(
        manifest: CorpusManifest,
        articles: Iterable[Article],
    ) -> tuple[re.Pattern[str], ...]:
        """Compile les patterns du manifest. Si aucun pattern, infère depuis filenames."""
        compiled: list[re.Pattern[str]] = []
        for cp in manifest.citation_patterns:
            flags = re.IGNORECASE if cp.case_insensitive else 0
            compiled.append(re.compile(cp.regex, flags))
        if compiled:
            return tuple(compiled)

        prefixes_seen: set[str] = set()
        for article in articles:
            m = _FILENAME_CITATION_RE.match(article.id)
            if not m:
                continue
            prefix = m.group(1).upper()
            num = m.group(2)
            base_digits = num[:1] if len(num) >= 4 else ""
            prefixes_seen.add(f"{prefix}{base_digits}")
        if not prefixes_seen:
            return tuple()
        # Pattern unique générique [LRD]\.?\s*<digit>NNN-N — borné au premier chiffre du base
        digit_class = "".join(sorted({k[1] for k in prefixes_seen if len(k) > 1})) or "0-9"
        regex = rf"\b([LRD])\.?\s*[{digit_class}]\d{{2,4}}(?:-\d+)?\b"
        logger.info(
            "auto-discovery citation_patterns: inféré '%s' depuis %d filenames",
            regex,
            len(articles) if not isinstance(articles, tuple) else len(articles),
        )
        return (re.compile(regex, re.IGNORECASE),)


def _parse_themes_yaml(raw: dict[str, Any]) -> dict[str, ThemeInfo]:
    themes_dict = raw.get("themes") or {}
    out: dict[str, ThemeInfo] = {}
    for code, payload in themes_dict.items():
        if not isinstance(payload, dict):
            continue
        out[code] = ThemeInfo(
            code=code,
            libelle=str(payload.get("libelle") or code),
            mots_cles=tuple(payload.get("mots_cles") or ()),
        )
    return out


def _infer_themes_from_articles(articles: Iterable[Article]) -> dict[str, ThemeInfo]:
    """Auto-discovery thèmes : 1 thème par mot-clé répété dans les titres.

    Heuristique volontairement simple : on extrait les noms communs > 5 chars
    des titres et on en fait un thème "fourre-tout". L'objectif n'est pas la
    pertinence métier mais que le pipeline tourne. Le manifest réel doit
    fournir un `themes.yaml` curé.
    """
    word_counter: dict[str, int] = {}
    for article in articles:
        for tok in _TOKEN_RE.findall(article.title.lower()):
            if len(tok) >= 5:
                word_counter[tok] = word_counter.get(tok, 0) + 1
    top = sorted(word_counter.items(), key=lambda kv: -kv[1])[:5]
    return {
        f"theme_{i}": ThemeInfo(
            code=f"theme_{i}",
            libelle=f"Thème inféré : {word}",
            mots_cles=(word,),
        )
        for i, (word, _) in enumerate(top)
    }


def _parse_refusals_yaml(raw: dict[str, Any], manifest: CorpusManifest) -> RefusalsConfig:
    scope_refusal = str(raw.get("scope_refusal") or "").strip()
    if not scope_refusal:
        scope_refusal = (
            f"Cette requête sort du périmètre du corpus « {manifest.identity.name} »."
        )
    domains_dict: dict[str, tuple[tuple[str, ...], str]] = {}
    for code, payload in (raw.get("domains") or {}).items():
        if not isinstance(payload, dict):
            continue
        kws = tuple(str(k).lower() for k in (payload.get("keywords") or ()))
        redirection = str(payload.get("redirection") or "").strip()
        domains_dict[str(code)] = (kws, redirection)
    patterns: list[re.Pattern[str]] = []
    for raw_pat in ((raw.get("priority_override") or {}).get("patterns") or ()):
        try:
            patterns.append(re.compile(str(raw_pat), re.IGNORECASE))
        except re.error as exc:
            logger.warning("priority_override pattern invalide ignoré: %r (%s)", raw_pat, exc)
    return RefusalsConfig(
        scope_refusal=scope_refusal,
        domains=domains_dict,
        priority_override_patterns=tuple(patterns),
    )


def load_corpus(code: str, *, corpus_root: Path | None = None) -> Corpus:
    """Raccourci fonctionnel pour `CorpusLoader(corpus_root).load(code)`."""
    return CorpusLoader(corpus_root=corpus_root).load(code)
