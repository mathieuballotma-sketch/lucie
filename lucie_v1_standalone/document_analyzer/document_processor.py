"""Orchestrateur principal du document_analyzer.

Pipeline déterministe (aucun LLM) :
    parse PDF/docx → out-of-scope head gate → theme detection
        → retriever (curaté KB + Légifrance) → out-of-scope tail (partiel)
        → DocumentAnalysisResult

Truth rule : tout refus est explicite et localisé. Aucune invention d'article.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from lucie_v1_standalone.dialogue.out_of_scope import detect_out_of_scope
from lucie_v1_standalone.retriever import handle as retriever_handle

from .docx_parser import parse_docx
from .exceptions import UnsupportedFormatError
from .pdf_parser import parse_pdf
from .subject_detector import detect_subject
from .types import Article, DocumentAnalysisResult

logger = logging.getLogger(__name__)

# Périmètre IN-SCOPE Beaume v1 — voir theme_mapping.yaml.
INSCOPE_THEMES: frozenset[str] = frozenset({"droit_social", "prudhommes"})

MIN_CONFIDENCE = 0.20            # Sous ce seuil : refus pour sujet incertain.
MAX_RETRIEVER_INPUT = 8000       # Truncate texte → retriever (perf BM25).
OOS_SCAN_HEAD_CHARS = 5000       # Fenêtre de détection oos initiale.

# Seuils détection d'un thème SECONDAIRE hors-scope (fixture mixte) :
# - absolu : ≥ 3 keywords distincts (élimine les bruits "SAS" en passing)
# - relatif : ≥ 30 % des hits du thème principal (sinon trop marginal)
PARTIAL_OOS_MIN_HITS = 3
PARTIAL_OOS_RELATIVE_THRESHOLD = 0.30
LEGIFRANCE_SEARCH_URL = (
    "https://www.legifrance.gouv.fr/search/code?tab_selection=code"
    "&searchField=ALL&query={query}"
)

REFUSAL_OOS_THEME = (
    "Sujet principal détecté ({theme}) hors périmètre Droit Social. "
    "Beaume v1 traite licenciement, contrat de travail et prud'hommes — "
    "pour ce domaine, un autre corpus est nécessaire."
)
REFUSAL_NO_THEME = (
    "Sujet juridique non identifié dans le périmètre Droit Social. "
    "Si ce dossier relève d'un autre domaine (par exemple santé ou pharma), "
    "un corpus Beaume Engine dédié est nécessaire (cf. corpus pharma ANSM)."
)
REFUSAL_LOW_CONFIDENCE = (
    "Sujet probablement Droit Social mais confiance trop faible ({conf:.0%}) "
    "pour identifier des articles applicables avec certitude."
)
PARTIAL_OOS_SECONDARY = (
    "Partie secondaire hors-scope détectée ({domain}). {redirection}"
)
PARTIAL_OOS_THEME = (
    "Partie secondaire détectée dans un autre domaine ({theme}). "
    "Le traitement principal porte sur le droit social uniquement."
)


def _build_url(source: dict) -> str:
    """Construit une URL Légifrance cliquable pour un article retourné.

    Si `fichier_source` est déjà une URL Légifrance (cas KB Légifrance via
    LegifranceRetriever), on l'utilise directement. Sinon (KB curatée locale,
    `fichier_source` = chemin .md), on construit une URL de recherche
    Légifrance par num d'article.
    """
    fichier_source = source.get("fichier_source", "")
    if isinstance(fichier_source, str) and fichier_source.startswith(
        "https://www.legifrance.gouv.fr/"
    ):
        return fichier_source
    article_id = source.get("id", "").strip()
    if not article_id:
        return "https://www.legifrance.gouv.fr/"
    return LEGIFRANCE_SEARCH_URL.format(query=article_id)


def _map_sources_to_articles(sources: list[dict]) -> tuple[Article, ...]:
    """Convertit le format retriever en `tuple[Article, ...]`."""
    out: list[Article] = []
    for s in sources:
        article_id = str(s.get("id", "")).strip()
        if not article_id:
            continue
        out.append(
            Article(
                id=article_id,
                title=str(s.get("titre", article_id)).strip(),
                url=_build_url(s),
                relevance=float(s.get("pertinence", 0.0)),
            )
        )
    return tuple(out)


def _detect_partial_oos(
    text: str, scored_themes: list[tuple[str, int]]
) -> Optional[str]:
    """Cherche un domaine HORS-SCOPE secondaire dans le document.

    Deux signaux indépendants — premier qui déclenche gagne :
      1. `detect_out_of_scope` sur la queue (au-delà de OOS_SCAN_HEAD_CHARS) :
         signal fort, déclenche dès le moindre match.
      2. Un thème secondaire qui n'est pas in-scope ET satisfait à la fois :
            - hits ≥ PARTIAL_OOS_MIN_HITS (absolu)
            - hits / top_hits ≥ PARTIAL_OOS_RELATIVE_THRESHOLD (relatif)
         Évite de signaler des mentions parasites (ex : "SAS" en passing dans
         un dossier purement lic_eco).

    Retourne un message de refus partiel, ou None si rien.
    """
    if len(text) > OOS_SCAN_HEAD_CHARS:
        tail = text[OOS_SCAN_HEAD_CHARS:]
        oos_tail = detect_out_of_scope(tail)
        if oos_tail is not None:
            return PARTIAL_OOS_SECONDARY.format(
                domain=oos_tail.domain,
                redirection=oos_tail.redirection.strip().replace("\n", " "),
            )
    if not scored_themes:
        return None
    top_hits = scored_themes[0][1]
    for theme_id, hits in scored_themes[1:]:
        if theme_id in INSCOPE_THEMES:
            continue
        if hits < PARTIAL_OOS_MIN_HITS:
            continue
        if hits / max(1, top_hits) < PARTIAL_OOS_RELATIVE_THRESHOLD:
            continue
        return PARTIAL_OOS_THEME.format(theme=theme_id)
    return None


def _detect_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    raise UnsupportedFormatError(
        f"Format non supporté en v1 : `{suffix}` "
        f"(uniquement .pdf et .docx)."
    )


async def analyze_document(file_path: str) -> DocumentAnalysisResult:
    """Analyse un PDF/docx client et retourne articles applicables + sujet.

    100% déterministe, 100% local (aucun LLM, aucun appel réseau).
    Toutes les étapes sont vérifiables et reproductibles.

    Args:
        file_path: chemin absolu ou relatif vers le fichier client.

    Returns:
        `DocumentAnalysisResult` avec `refusal_reason=None` si analyse
        complète, ou populée si refus total / partiel.

    Raises:
        UnsupportedFormatError : extension hors .pdf/.docx.
        EmptyDocumentError : document vide.
        ScannedPDFError : PDF scan-image (texte < 50 chars).
        CorruptedFileError : fichier illisible.
    """
    start = time.perf_counter()
    path = Path(file_path)
    fmt = _detect_format(path)

    if fmt == "pdf":
        text, pages = parse_pdf(path)
    else:
        text, pages = parse_docx(path)

    elapsed_ms = lambda: int((time.perf_counter() - start) * 1000)

    # Gate hors-scope explicite sur l'en-tête du document.
    oos_head = detect_out_of_scope(text[:OOS_SCAN_HEAD_CHARS])
    if oos_head is not None:
        logger.info(
            "[document_analyzer] refus oos head domain=%s file=%s",
            oos_head.domain,
            path.name,
        )
        return DocumentAnalysisResult(
            pages=pages,
            format=fmt,
            subject_detected=None,
            confidence=0.0,
            articles_applicables=(),
            refusal_reason=(
                f"Hors-scope ({oos_head.domain}). "
                + oos_head.redirection.strip().replace("\n", " ")
            ),
            processing_time_ms=elapsed_ms(),
        )

    top_theme, confidence, scored = detect_subject(text)

    # Pas de thème reconnu (pharma, médical, etc. non couverts).
    if top_theme is None:
        logger.info(
            "[document_analyzer] refus aucun thème détecté file=%s", path.name
        )
        return DocumentAnalysisResult(
            pages=pages,
            format=fmt,
            subject_detected=None,
            confidence=0.0,
            articles_applicables=(),
            refusal_reason=REFUSAL_NO_THEME,
            processing_time_ms=elapsed_ms(),
        )

    # Thème principal hors-scope.
    if top_theme not in INSCOPE_THEMES:
        logger.info(
            "[document_analyzer] refus thème hors-scope=%s file=%s",
            top_theme,
            path.name,
        )
        return DocumentAnalysisResult(
            pages=pages,
            format=fmt,
            subject_detected=top_theme,
            confidence=confidence,
            articles_applicables=(),
            refusal_reason=REFUSAL_OOS_THEME.format(theme=top_theme),
            processing_time_ms=elapsed_ms(),
        )

    # Sujet droit_social confirmé mais confiance trop faible.
    if confidence < MIN_CONFIDENCE:
        return DocumentAnalysisResult(
            pages=pages,
            format=fmt,
            subject_detected=top_theme,
            confidence=confidence,
            articles_applicables=(),
            refusal_reason=REFUSAL_LOW_CONFIDENCE.format(conf=confidence),
            processing_time_ms=elapsed_ms(),
        )

    # In-scope : appel retriever pour récupérer les articles applicables.
    faits_json = json.dumps(
        {"query": text[:MAX_RETRIEVER_INPUT]},
        ensure_ascii=False,
    )
    raw_sources = await retriever_handle(faits_json)
    try:
        parsed = json.loads(raw_sources)
    except json.JSONDecodeError as exc:
        # Le retriever a un contrat de sortie JSON stable — un crash ici est
        # un bug, pas un cas métier. On log et on retourne un refus explicite.
        logger.error(
            "Retriever a retourné un JSON invalide : %s — payload=%r",
            exc,
            raw_sources[:200],
        )
        return DocumentAnalysisResult(
            pages=pages,
            format=fmt,
            subject_detected=top_theme,
            confidence=confidence,
            articles_applicables=(),
            refusal_reason="Erreur interne de la base d'articles (JSON invalide).",
            processing_time_ms=elapsed_ms(),
        )

    sources = parsed.get("sources", []) or []
    articles = _map_sources_to_articles(sources)

    # Détection partielle hors-scope (fixture 5 mixte lic_eco + fiscal).
    partial_refusal = _detect_partial_oos(text, scored)

    return DocumentAnalysisResult(
        pages=pages,
        format=fmt,
        subject_detected=top_theme,
        confidence=confidence,
        articles_applicables=articles,
        refusal_reason=partial_refusal,
        processing_time_ms=elapsed_ms(),
    )
