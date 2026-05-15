"""Parsing docx déterministe pour Beaume document_analyzer.

100% local : python-docx lit le ZIP sur le disque, aucun appel réseau.
Le docx n'a pas de notion de page native (la pagination est calculée par
Word au rendering). On approxime : pseudo_pages = max(1, paragraphs // PARAGRAPHS_PER_PAGE).
"""

from __future__ import annotations

import logging
from pathlib import Path

from docx import Document
from docx.opc.exceptions import OpcError

from .exceptions import CorruptedFileError, EmptyDocumentError

logger = logging.getLogger(__name__)

PARAGRAPHS_PER_PAGE = 40  # heuristique : 40 paragraphs ≈ 1 page A4 standard


def parse_docx(path: Path) -> tuple[str, int]:
    """Extrait le texte d'un docx et retourne (texte, pseudo_pages).

    Lève :
        CorruptedFileError : fichier non ouvrable par python-docx.
        EmptyDocumentError : 0 paragraphe non vide.
    """
    if not path.exists():
        raise CorruptedFileError(f"docx introuvable : {path}")
    try:
        doc = Document(str(path))
    except (OpcError, ValueError, KeyError) as exc:
        logger.warning("docx illisible (%s) : %s", type(exc).__name__, path.name)
        raise CorruptedFileError(
            f"docx illisible (`{type(exc).__name__}`) : {path.name}"
        ) from exc

    paragraphs = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    if not paragraphs:
        raise EmptyDocumentError(f"docx vide (0 paragraphe) : {path.name}")

    text = "\n".join(paragraphs)
    pseudo_pages = max(1, len(paragraphs) // PARAGRAPHS_PER_PAGE)
    return text, pseudo_pages
