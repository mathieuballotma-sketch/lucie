"""
Working Memory - Mémoire à court terme (dernières interactions).
"""

from collections import deque
from typing import List, Tuple


class WorkingMemory:
    """
    Stocke les dernières interactions utilisateur pour fournir un contexte court terme.
    """

    def __init__(self, capacity: int = 10):
        self.capacity = capacity
        self.history: deque = deque(maxlen=capacity)

    def add(self, query: str, response: str):
        """Ajoute une interaction à l'historique."""
        self.history.append((query, response))

    def get_context(self, n: int = 5) -> str:
        """
        Retourne les n dernières interactions sous forme de chaîne formatée.
        """
        if not self.history:
            return ""
        # Prendre les n dernières (ou moins si pas assez)
        recent = list(self.history)[-n:]
        lines = []
        for i, (q, r) in enumerate(recent, 1):
            lines.append(f"{i}. Utilisateur: {q}")
            lines.append(f"   Assistant: {r}")
        return "\n".join(lines)

    def clear(self):
        """Efface l'historique."""
        self.history.clear()

    def get_last_query(self) -> str:
        """Retourne la dernière requête utilisateur."""
        if self.history:
            return self.history[-1][0]
        return ""

    def get_last_response(self) -> str:
        """Retourne la dernière réponse de l'assistant."""
        if self.history:
            return self.history[-1][1]
        return ""