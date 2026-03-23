"""
Module feedback — collecte et exploitation des retours utilisateur.

Exporte :
- FeedbackCollector : enregistre les notes (👍/👎) et commentaires
- RAGReinforcer     : ajuste les scores RAG en fonction du feedback
"""

from .collector import FeedbackCollector
from .rag_reinforcer import RAGReinforcer

__all__ = ["FeedbackCollector", "RAGReinforcer"]
