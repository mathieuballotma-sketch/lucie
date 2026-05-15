"""document_analyzer — analyse déterministe d'un PDF/docx client.

Module additif pur. Aucune modification du pipeline droit social actuel.
Lecture seule sur `retriever`, `theme_mapping` et `out_of_scope`.

Cas d'usage : Beaume reçoit un dossier client (PDF / docx) en input, en
extrait le sujet juridique principal et les articles applicables en moins
de 30 secondes, 100% en local sur le Mac de l'avocat.

API publique :
    >>> from lucie_v1_standalone.document_analyzer import analyze_document
    >>> result = await analyze_document("dossier.pdf")
    >>> result.subject_detected
    'droit_social'
    >>> [a.id for a in result.articles_applicables]
    ['L.1233-3', 'L.1233-2', ...]
"""

from .document_processor import analyze_document
from .exceptions import (
    CorruptedFileError,
    DocumentAnalyzerError,
    EmptyDocumentError,
    ScannedPDFError,
    UnsupportedFormatError,
)
from .types import Article, DocumentAnalysisResult

__all__ = [
    "analyze_document",
    "Article",
    "DocumentAnalysisResult",
    "DocumentAnalyzerError",
    "UnsupportedFormatError",
    "EmptyDocumentError",
    "ScannedPDFError",
    "CorruptedFileError",
]
