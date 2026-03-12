import asyncio
from typing import List, Optional
from app.memory import MemoryService
from app.utils.logger import logger

class MemoryManager:
    def __init__(self, memory_service: MemoryService, config: dict):
        self.memory = memory_service
        self.max_short_term = config.get("max_short_term", 5)
        self.max_long_term = config.get("max_long_term", 3)

    async def get_context(self, user_id: str, query: str) -> str:
        # Récupérer la mémoire à court terme (dernières interactions)
        short_term = self.memory.get_working_context(n=self.max_short_term)
        # Récupérer la mémoire à long terme (souvenirs similaires)
        long_term_results = self.memory.remember(query, n_results=self.max_long_term)
        long_term = "\n".join([r.get("response", "") for r in long_term_results])
        context = ""
        if short_term:
            context += f"Conversation récente:\n{short_term}\n"
        if long_term:
            context += f"Souvenirs pertinents:\n{long_term}\n"
        return context
