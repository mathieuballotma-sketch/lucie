"""Erreurs explicites du module document_analyzer.

Aucune erreur silencieuse : tout problème de parsing remonte à l'appelant
sous forme d'exception typée. Le caller décide du message UX (refus poli,
toast, etc.) — la couche métier ne fait que signaler.
"""

from __future__ import annotations


class DocumentAnalyzerError(Exception):
    """Racine des erreurs document_analyzer. À catcher pour fallback global."""


class UnsupportedFormatError(DocumentAnalyzerError):
    """Extension de fichier non supportée (uniquement .pdf et .docx en v1)."""


class EmptyDocumentError(DocumentAnalyzerError):
    """Le document est lisible mais ne contient aucun texte exploitable."""


class ScannedPDFError(DocumentAnalyzerError):
    """PDF dont l'extraction texte est vide ou quasi-vide — typique d'un
    scan image sans OCR. v1 ne fait pas d'OCR : refus explicite (truth rule).
    """


class CorruptedFileError(DocumentAnalyzerError):
    """Fichier illisible (PDF tronqué, docx corrompu, etc.)."""
