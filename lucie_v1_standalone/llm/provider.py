"""
LLMProvider — Protocol définissant l'interface de tout fournisseur LLM.

Aucun import du reste du repo.
Implémentations concrètes dans des modules séparés (ollama_provider.py, …).
"""

from __future__ import annotations

from typing import Iterator, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Interface minimale pour tout fournisseur LLM local."""

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        options: dict | None = None,
        stream: bool = False,
        keep_alive: str = "10m",
    ) -> str | Iterator[str]:
        """
        Génère une réponse.

        Args:
            prompt: Prompt utilisateur.
            system: System prompt.
            options: Paramètres de sampling (num_ctx, temperature, …).
            stream: Si True, retourne un Iterator[str] chunk par chunk.
            keep_alive: Durée de maintien du modèle en mémoire GPU.

        Returns:
            str si stream=False, Iterator[str] si stream=True.
        """
        ...

    def available_models(self) -> list[str]:
        """Retourne la liste des modèles disponibles sur ce fournisseur."""
        ...

    def load_model(self, name: str) -> None:
        """Pré-warm : charge le modèle en mémoire sans générer de texte."""
        ...
