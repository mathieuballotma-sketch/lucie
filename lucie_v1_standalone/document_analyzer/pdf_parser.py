"""Parsing PDF déterministe pour Beaume document_analyzer.

100% local : pdfplumber lit le fichier sur le disque, aucun appel réseau.
Détection scan-image : si le texte extrait est vide ou < MIN_TEXT_CHARS,
on remonte ScannedPDFError plutôt que retourner un texte vide silencieux
(truth rule — l'avocat doit savoir qu'on ne peut pas traiter ce dossier).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pdfplumber

from .exceptions import CorruptedFileError, EmptyDocumentError, ScannedPDFError

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 50  # seuil détection scan : sous ce seuil on considère "scan image"


def parse_pdf(path: Path) -> tuple[str, int]:
    """Extrait le texte d'un PDF et retourne (texte, nombre_de_pages).

    Lève :
        CorruptedFileError : pdfplumber n'arrive pas à ouvrir le fichier.
        EmptyDocumentError : 0 page.
        ScannedPDFError : texte total < MIN_TEXT_CHARS (scan image probable).
    """
    if not path.exists():
        raise CorruptedFileError(f"PDF introuvable : {path}")
    try:
        with pdfplumber.open(str(path)) as pdf:
            pages_count = len(pdf.pages)
            if pages_count == 0:
                raise EmptyDocumentError(f"PDF vide (0 page) : {path.name}")
            chunks: list[str] = []
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text:
                    chunks.append(page_text)
            text = "\n".join(chunks).strip()
    except (EmptyDocumentError, ScannedPDFError):
        raise
    except Exception as exc:
        # pdfplumber peut lever PDFSyntaxError, struct.error, etc. selon la
        # façon dont le fichier est cassé. On capture large et on remonte un
        # type stable côté caller.
        logger.warning("PDF illisible (%s) : %s", type(exc).__name__, path.name)
        raise CorruptedFileError(
            f"PDF illisible (`{type(exc).__name__}`) : {path.name}"
        ) from exc

    if len(text) < MIN_TEXT_CHARS:
        raise ScannedPDFError(
            f"Dossier non lisible (scan image, {len(text)} chars extraits "
            f"sur {pages_count} pages). OCR pas encore disponible en v1."
        )
    return text, pages_count
