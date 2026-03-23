"""
Embedder utilisant Ollama (mxbai-embed-large) au lieu de sentence-transformers.
Fournit une interface compatible avec l'ancien DummyEmbedder et SentenceTransformer.
"""

from typing import Any, List, Optional, Union

import httpx
import numpy as np
import ollama

from ..utils.logger import logger


class OllamaEmbedder:
    """
    Génère des embeddings via un modèle Ollama local.
    Compatible avec l'interface encode() de SentenceTransformer.
    """

    def __init__(
        self,
        model: str = "mxbai-embed-large",
        host: str = "http://localhost:11434",
        timeout: float = 30.0,
        dimension: Optional[int] = None,
    ) -> None:
        """
        Args:
            model: Nom du modèle d'embedding Ollama.
            host: URL du serveur Ollama.
            timeout: Timeout HTTP en secondes.
            dimension: Dimension forcée (si None, détectée automatiquement).
        """
        self.model = model
        self._client = ollama.Client(
            host=host,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )

        # Détecter la dimension avec un embedding test
        if dimension is not None:
            self.dimension = dimension
        else:
            self.dimension = self._detect_dimension()

        logger.info(
            f"✅ OllamaEmbedder initialisé (modèle={model}, dim={self.dimension})"
        )

    def _detect_dimension(self) -> int:
        """Détecte la dimension du modèle en générant un embedding test."""
        try:
            resp = self._client.embeddings(model=self.model, prompt="test")
            emb: Any = resp.get("embedding", [])
            if emb:
                return int(len(emb))
        except Exception as e:
            logger.warning(f"Impossible de détecter la dimension: {e}")
        return 1024  # fallback mxbai-embed-large default

    def encode(
        self,
        texts: Union[str, List[str]],
        **_kwargs: Any,
    ) -> "np.ndarray[Any, Any]":
        """
        Encode un ou plusieurs textes en vecteurs d'embedding.

        Args:
            texts: Un texte ou une liste de textes.

        Returns:
            np.ndarray de shape (n, dimension) ou (dimension,) si un seul texte.
        """
        if isinstance(texts, str):
            text_list: List[str] = [texts]
            single = True
        else:
            text_list = texts
            single = False

        embeddings = []
        for text in text_list:
            emb = self._embed_single(text)
            embeddings.append(emb)

        result: np.ndarray[Any, Any] = np.array(embeddings, dtype=np.float32)
        if single:
            return result[0]  # type: ignore[no-any-return]
        return result

    def embed_query(self, text: str) -> List[float]:
        """
        Embed un seul texte et retourne un vecteur (liste de floats).
        Utilisé par EpisodicMemory.embedding_fn.
        """
        return list(self._embed_single(text).tolist())

    def _embed_single(self, text: str) -> "np.ndarray[Any, Any]":
        """Génère l'embedding d'un seul texte via Ollama."""
        try:
            resp = self._client.embeddings(model=self.model, prompt=text)
            emb: Any = resp.get("embedding", [])
            if emb:
                return np.array(emb, dtype=np.float32)
        except Exception as e:
            logger.error(f"Erreur embedding Ollama: {e}")

        # Fallback : vecteur de zéros
        return np.zeros(self.dimension, dtype=np.float32)

    def get_sentence_embedding_dimension(self) -> int:
        """Retourne la dimension des embeddings (compatibilité SentenceTransformer)."""
        return self.dimension
