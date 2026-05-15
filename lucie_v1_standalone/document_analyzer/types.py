"""Structures de retour du document_analyzer.

Dataclasses frozen pour interdire la mutation post-analyse (truth rule :
le résultat est un fait à l'instant T, pas un état mutable).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Article:
    """Un article applicable retourné par le retriever.

    `url` pointe vers Légifrance ; si l'article provient de la KB curatée
    locale (pas de mapping LEGIARTI), `url` est une URL de recherche
    Légifrance par num d'article — toujours cliquable.
    """

    id: str
    title: str
    url: str
    relevance: float


@dataclass(frozen=True)
class DocumentAnalysisResult:
    """Résultat d'analyse d'un PDF/docx client.

    Champs :
      - `pages` : nombre de pages PDF, ou pseudo-pages docx (paragraphs / 40).
      - `format` : "pdf" ou "docx".
      - `subject_detected` : id de thème (ex: "droit_social"). None si refus
        sans thème identifié.
      - `confidence` : [0.0, 1.0]. 0.0 si refus.
      - `articles_applicables` : liste vide si refus total. Peuplée si in-scope
        OU refus partiel (un domaine secondaire hors-scope a été détecté mais
        on a quand même traité la partie in-scope).
      - `refusal_reason` : None si analyse complète sans réserve. Message
        localisé (français, ton avocat) si refus total ou partiel.
      - `processing_time_ms` : durée totale parsing + détection + retriever.
    """

    pages: int
    format: str
    subject_detected: Optional[str]
    confidence: float
    articles_applicables: tuple[Article, ...] = field(default_factory=tuple)
    refusal_reason: Optional[str] = None
    processing_time_ms: int = 0

    def to_dict(self) -> dict:
        """Sérialisation JSON-friendly pour le démo / wizard W-1 carte 6."""
        return {
            "pages": self.pages,
            "format": self.format,
            "subject_detected": self.subject_detected,
            "confidence": round(self.confidence, 3),
            "articles_applicables": [
                {
                    "id": a.id,
                    "title": a.title,
                    "url": a.url,
                    "relevance": round(a.relevance, 2),
                }
                for a in self.articles_applicables
            ],
            "refusal_reason": self.refusal_reason,
            "processing_time_ms": self.processing_time_ms,
        }
