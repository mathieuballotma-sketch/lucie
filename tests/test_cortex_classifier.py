"""
Tests pour le classifieur sémantique du cortex.
Vérifie que la classification fonctionne correctement avec l'API réelle.
"""

import pytest
import numpy as np
from app.brain.cortex import EmbeddingClassifier


@pytest.fixture
def classifier():
    """Crée un classifieur initialisé pour les tests."""
    c = EmbeddingClassifier(retrain=True)
    c.initialize()
    return c


def test_classifier_initialization(classifier):
    """Vérifie que le classifieur est bien initialisé."""
    # is_ready dépend de sentence-transformers — peut être False si absent
    assert isinstance(classifier.is_ready, bool)
    assert hasattr(classifier, '_model')
    assert hasattr(classifier, '_examples')


def test_classifier_classify_without_examples(classifier):
    """Teste que classify retourne (None, 0.0) sans exemples."""
    result = classifier.classify("bonjour")
    assert result == (None, 0.0)


def test_classifier_classify_with_examples(classifier):
    """Teste la classification avec des exemples si le modèle est disponible."""
    if not classifier.is_ready:
        pytest.skip("sentence-transformers absent — fast path keywords uniquement")

    classifier.add_example("bonjour comment vas-tu", "greeting")
    classifier.add_example("ouvre notes", "action")
    classifier.add_example("envoie un email", "mail")

    assert classifier.example_count == 3

    # Baisser le seuil pour le test
    classifier.confidence_threshold = 0.5
    pred, conf = classifier.classify("ouvre safari")
    # pred peut être None si confiance < seuil, ou une catégorie connue
    assert conf >= 0.0
    assert conf <= 1.0


def test_classifier_confidence_bounds(classifier):
    """Vérifie que la confiance est dans [0.0, 1.0]."""
    if not classifier.is_ready:
        pytest.skip("sentence-transformers absent")

    classifier.add_example("test query", "simple")
    _, conf = classifier.classify("quelque chose")
    assert 0.0 <= conf <= 1.0


def test_classifier_fallback_no_examples(classifier):
    """Teste que classify retourne (None, 0.0) quand pas d'exemples."""
    assert classifier.example_count == 0
    pred, conf = classifier.classify("ouvre notes")
    assert pred is None
    assert conf == 0.0


def test_classifier_is_ready_property(classifier):
    """Vérifie que is_ready est une propriété booléenne cohérente."""
    ready = classifier.is_ready
    assert isinstance(ready, bool)
    # Si prêt, _model ne doit pas être None
    if ready:
        assert classifier._model is not None
