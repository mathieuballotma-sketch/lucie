"""
EmbeddingClassifier — classification rapide des requêtes
Loi : moindre action — all-MiniLM-L6-v2 pour le Fast Path
FAISS HNSW pour recherche vectorielle O(log n) + cache LRU embeddings
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any, Optional, List, Tuple, Dict

import numpy as np
import numpy.typing as npt

# Import FAISS avec fallback gracieux
try:
    import faiss
    _FAISS_AVAILABLE = True
except ImportError:
    faiss = None
    _FAISS_AVAILABLE = False

logger = logging.getLogger(__name__)

_mini_model = None

# Taille maximale du cache d'embeddings
_EMBED_CACHE_MAX = 1024


def _load_mini_model() -> Any:
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
    FAISS IndexFlatIP pour recherche rapide, fallback scan linéaire.
    """

    def __init__(self, retrain: bool = False) -> None:
        self._model = None
        self._examples: List[Tuple[npt.NDArray[np.float32], str]] = []
        self.confidence_threshold: float = 0.75
        self._ready: bool = False
        # Index FAISS — Inner Product car vecteurs normalisés (cosine = dot)
        self._index: Any = None
        # Labels alignés sur les positions dans l'index FAISS
        self._labels: List[str] = []
        # Cache LRU des embeddings (clé: texte, valeur: vecteur)
        self._embed_cache: OrderedDict[str, npt.NDArray[np.float32]] = OrderedDict()

    def initialize(self) -> bool:
        """Initialise le modèle léger. Retourne True si prêt."""
        self._model = _load_mini_model()
        self._ready = self._model is not None
        if self._ready and _FAISS_AVAILABLE:
            # Dimension 384 pour all-MiniLM-L6-v2
            self._index = faiss.IndexFlatIP(384)
            logger.info("✅ Index FAISS IndexFlatIP(384) initialisé")
        elif self._ready:
            logger.warning("⚠️ FAISS non disponible — scan linéaire uniquement")
        return self._ready

    def embed(self, text: str) -> Optional[npt.NDArray[np.float32]]:
        """Encode un texte en vecteur 384d avec cache LRU."""
        if self._model is None:
            return None
        # Vérification cache
        if text in self._embed_cache:
            # Remonter en tête du LRU
            self._embed_cache.move_to_end(text)
            return self._embed_cache[text]
        try:
            vec = self._model.encode(text, normalize_embeddings=True)
            vec = vec.astype(np.float32)
            # Insertion dans le cache avec éviction LRU
            self._embed_cache[text] = vec
            if len(self._embed_cache) > _EMBED_CACHE_MAX:
                # Évicter l'entrée la plus ancienne
                self._embed_cache.popitem(last=False)
            return vec
        except Exception as e:
            logger.error(f"Erreur embed : {e}")
            return None

    def embed_batch(self, texts: List[str]) -> Optional[npt.NDArray[np.float32]]:
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
            # Ajout dans l'index FAISS si disponible
            if self._index is not None:
                vec_2d = vec.reshape(1, -1)
                self._index.add(vec_2d)
                self._labels.append(label)

    def _rebuild_index(self) -> None:
        """Reconstruit l'index FAISS depuis _examples."""
        if not _FAISS_AVAILABLE or not self._examples:
            return
        try:
            self._index = faiss.IndexFlatIP(384)
            self._labels = []
            vecs = np.array([v for v, _ in self._examples], dtype=np.float32)
            self._index.add(vecs)
            self._labels = [label for _, label in self._examples]
            logger.info(f"🔄 Index FAISS reconstruit — {len(self._labels)} vecteurs")
        except Exception as e:
            logger.error(f"Erreur reconstruction index FAISS : {e}")
            self._index = None
            self._labels = []

    def classify(self, text: str) -> Tuple[Optional[str], float]:
        """
        Classifie une requête.
        Stratégie : FAISS k=5 vote pondéré → fallback scan linéaire.
        Retourne (label, confidence) — None si confiance < seuil.
        """
        if not self._ready or not self._examples:
            return None, 0.0

        vec = self.embed(text)
        if vec is None:
            return None, 0.0

        t0 = time.perf_counter()

        # Tentative FAISS — recherche rapide O(log n)
        if self._index is not None and self._index.ntotal > 0:
            try:
                return self._classify_faiss(vec, t0, text)
            except Exception as e:
                logger.warning(f"⚠️ FAISS classify échoué, fallback linéaire : {e}")

        # Fallback — scan linéaire O(n) identique à l'original
        return self._classify_linear(vec, t0, text)

    def _classify_faiss(self, vec: npt.NDArray[np.float32], t0: float, text: str) -> Tuple[Optional[str], float]:
        """Classification via FAISS k-NN avec vote pondéré."""
        vec_2d = vec.reshape(1, -1)
        k = min(5, self._index.ntotal)
        # scores = dot product = cosine similarity (vecteurs normalisés)
        scores, indices = self._index.search(vec_2d, k)

        # Vote pondéré par score de similarité
        label_scores: Dict[str, float] = {}
        for i in range(k):
            idx = int(indices[0][i])
            score = float(scores[0][i])
            if idx < 0 or idx >= len(self._labels):
                continue
            lbl = self._labels[idx]
            label_scores[lbl] = label_scores.get(lbl, 0.0) + score

        if not label_scores:
            return None, 0.0

        # Meilleur label par score pondéré cumulé
        best_label = max(label_scores, key=lambda k: label_scores[k])
        # Score de confiance = meilleur score brut parmi les k voisins du meilleur label
        best_score = 0.0
        for i in range(k):
            idx = int(indices[0][i])
            if idx < 0 or idx >= len(self._labels):
                continue
            if self._labels[idx] == best_label:
                best_score = max(best_score, float(scores[0][i]))

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(f"classify FAISS '{text[:30]}' → {best_label} ({best_score:.3f}) en {elapsed_ms:.1f}ms")

        if best_score >= self.confidence_threshold:
            return best_label, best_score
        return None, best_score

    def _classify_linear(self, vec: npt.NDArray[np.float32], t0: float, text: str) -> Tuple[Optional[str], float]:
        """Fallback — scan linéaire identique à l'original."""
        best_label: Optional[str] = None
        best_score: float = 0.0

        for example_vec, label in self._examples:
            score = float(np.dot(vec, example_vec))
            if score > best_score:
                best_score = score
                best_label = label

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(f"classify linéaire '{text[:30]}' → {best_label} ({best_score:.3f}) en {elapsed_ms:.1f}ms")

        if best_score >= self.confidence_threshold:
            return best_label, best_score
        return None, best_score

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def example_count(self) -> int:
        return len(self._examples)
