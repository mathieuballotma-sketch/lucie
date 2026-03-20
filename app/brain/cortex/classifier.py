"""
EmbeddingClassifier — classification rapide des requêtes
Loi : moindre action — all-MiniLM-L6-v2 pour le Fast Path
"""

from __future__ import annotations

import logging
import time
from typing import Optional, List, Tuple
import numpy as np

logger = logging.getLogger(__name__)

_mini_model = None


def _load_mini_model():
    """Charge all-MiniLM-L6-v2 depuis sentence-transformers (22 Mo)."""
    global _mini_model
    if _mini_model is not None:
        return _mini_model
    try:
        from sentence_transformers import SentenceTransformer
        _mini_model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("✅ all-MiniLM-L6-v2 chargé (384d)")
    except ImportError:
        logger.warning("⚠️ sentence-transformers absent — fallback Ollama")
        _mini_model = None
    return _mini_model


class EmbeddingClassifier:
    """
    Classifie les requêtes en < 10ms via embeddings locaux légers.
    Utilisé exclusivement par le Fast Path du FrontalCortex.
    """

    def __init__(self, retrain: bool = False) -> None:
        self._model = None
        self._examples: List[Tuple[np.ndarray, str]] = []
        self.confidence_threshold: float = 0.75
        self._ready: bool = False

    def initialize(self) -> bool:
        """Initialise le modèle léger. Retourne True si prêt."""
        self._model = _load_mini_model()
        self._ready = self._model is not None
        return self._ready

    def embed(self, text: str) -> Optional[np.ndarray]:
        """Encode un texte en vecteur 384d."""
        if self._model is None:
            return None
        try:
            vec = self._model.encode(text, normalize_embeddings=True)
            return vec.astype(np.float32)
        except Exception as e:
            logger.error(f"Erreur embed : {e}")
            return None

    def embed_batch(self, texts: List[str]) -> Optional[np.ndarray]:
        """Encode plusieurs textes en batch."""
        if self._model is None:
            return None
        try:
            vecs = self._model.encode(texts, normalize_embeddings=True, batch_size=32)
            return vecs.astype(np.float32)
        except Exception as e:
            logger.error(f"Erreur embed_batch : {e}")
            return None

    def add_example(self, text: str, label: str) -> None:
        """Ajoute un exemple d'entraînement (texte → label agent)."""
        vec = self.embed(text)
        if vec is not None:
            self._examples.append((vec, label))

    def classify(self, text: str) -> Tuple[Optional[str], float]:
        """
        Classifie une requête par similarité cosinus.
        Retourne (label, confidence) — None si confiance < seuil.
        """
        if not self._ready or not self._examples:
            return None, 0.0

        vec = self.embed(text)
        if vec is None:
            return None, 0.0

        t0 = time.perf_counter()

        best_label: Optional[str] = None
        best_score: float = 0.0

        for example_vec, label in self._examples:
            score = float(np.dot(vec, example_vec))
            if score > best_score:
                best_score = score
                best_label = label

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(f"classify '{text[:30]}' → {best_label} ({best_score:.3f}) en {elapsed_ms:.1f}ms")

        if best_score >= self.confidence_threshold:
            return best_label, best_score
        return None, best_score

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def example_count(self) -> int:
        return len(self._examples)
