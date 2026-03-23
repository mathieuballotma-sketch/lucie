"""
Memory Service - Façade pour les mémoires court terme et long terme.
"""

from typing import Optional, List, Dict, Any

from .episodic_memory import EpisodicMemory
from .working_memory import WorkingMemory


class MemoryService:
    def __init__(self, episodic: EpisodicMemory, working: WorkingMemory):
        self.episodic = episodic
        self.working = working

    def add_to_working(self, query: str, response: str) -> None:
        """Ajoute une interaction à la mémoire court terme."""
        self.working.add(query, response)

    def get_working_context(self, n: int = 5) -> str:
        """Récupère les n dernières interactions."""
        return self.working.get_context(n)

    async def add_episode(self, query: str, response: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Ajoute un épisode à la mémoire long terme."""
        await self.episodic.add_episode(query, response, metadata)

    async def remember(self, query: str, n_results: int = 5, min_similarity: float = 0.0) -> List[Dict[str, Any]]:
        """Recherche des épisodes similaires."""
        return await self.episodic.remember(query, n_results, min_similarity)