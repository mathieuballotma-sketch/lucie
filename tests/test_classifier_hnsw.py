"""
Tests — EmbeddingClassifier avec FAISS IndexFlatIP + cache LRU
"""
import pytest


def test_faiss_classify():
    """Vérifie la classification FAISS k-NN vote pondéré."""
    from app.brain.cortex.classifier import EmbeddingClassifier
    clf = EmbeddingClassifier()
    if not clf.initialize():
        pytest.skip("sentence-transformers non disponible")
    # Seuil bas pour test avec peu d'exemples (4 seulement)
    clf.confidence_threshold = 0.5
    clf.add_example("ouvre safari", "computer_control")
    clf.add_example("lance chrome", "computer_control")
    clf.add_example("crée un fichier", "file_agent")
    clf.add_example("supprime le dossier", "file_agent")
    label, score = clf.classify("ouvre firefox")
    assert label == "computer_control"
    assert score > 0.5


def test_embed_cache():
    """Vérifie que le cache LRU retourne le même objet."""
    from app.brain.cortex.classifier import EmbeddingClassifier
    clf = EmbeddingClassifier()
    if not clf.initialize():
        pytest.skip("sentence-transformers non disponible")
    v1 = clf.embed("test phrase")
    v2 = clf.embed("test phrase")
    assert v1 is not None
    assert v2 is not None
    # Même objet en cache
    assert v1 is v2


def test_fallback_without_faiss():
    """Vérifie le fallback linéaire si FAISS est désactivé."""
    from app.brain.cortex.classifier import EmbeddingClassifier
    clf = EmbeddingClassifier()
    if not clf.initialize():
        pytest.skip("sentence-transformers non disponible")
    # Forcer la désactivation de FAISS
    clf._index = None
    clf.add_example("bonjour", "greeting")
    clf.add_example("salut", "greeting")
    clf.add_example("ouvre terminal", "computer_control")
    label, score = clf.classify("hey salut")
    # Doit fonctionner en scan linéaire
    assert label == "greeting" or label is None
    assert score > 0.0


def test_rebuild_index():
    """Vérifie la reconstruction de l'index FAISS."""
    from app.brain.cortex.classifier import EmbeddingClassifier, _FAISS_AVAILABLE
    if not _FAISS_AVAILABLE:
        pytest.skip("FAISS non installé")
    clf = EmbeddingClassifier()
    if not clf.initialize():
        pytest.skip("sentence-transformers non disponible")
    clf.add_example("envoie un mail", "smart_mail")
    clf.add_example("lis mes mails", "smart_mail")
    assert clf._index.ntotal == 2
    # Reconstruction
    clf._rebuild_index()
    assert clf._index.ntotal == 2
    assert len(clf._labels) == 2


def test_cache_lru_eviction():
    """Vérifie l'éviction LRU quand le cache dépasse la taille max."""
    from app.brain.cortex.classifier import EmbeddingClassifier, _EMBED_CACHE_MAX
    clf = EmbeddingClassifier()
    if not clf.initialize():
        pytest.skip("sentence-transformers non disponible")
    # Remplir le cache au max + 1
    for i in range(_EMBED_CACHE_MAX + 1):
        clf.embed(f"phrase unique numéro {i}")
    # Le cache ne doit pas dépasser la taille max
    assert len(clf._embed_cache) <= _EMBED_CACHE_MAX
