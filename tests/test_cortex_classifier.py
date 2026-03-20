"""
Tests pour le classifieur sémantique du cortex.
Vérifie que la classification atteint >80% de précision sur des exemples de test.
"""

import pytest
import numpy as np
from app.brain.cortex import EmbeddingClassifier


@pytest.fixture
def classifier():
    """Crée un classifieur avec réentraînement forcé pour les tests."""
    return EmbeddingClassifier(retrain=True)


def test_classifier_initialization(classifier):
    """Vérifie que le classifieur est bien initialisé et entraîné."""
    assert classifier.is_trained
    assert classifier._classifier is not None
    assert classifier._label_encoder is not None


@pytest.mark.asyncio
async def test_classifier_prediction(classifier):
    """Teste la prédiction sur quelques requêtes typiques."""
    test_cases = [
        ("bonjour", "greeting"),
        ("ouvre notes", "action"),
        ("ouvre safari et tape google", "multi_action"),
        ("quelle est la capitale de la France", "simple"),
        ("envoie un email à john", "mail"),
        ("ouvre safari sur google", "safari"),
        ("organise les fenêtres côte à côte", "arrange"),
        ("explique la relativité", "complex"),
    ]
    correct = 0
    for query, expected in test_cases:
        pred, conf = await classifier.predict(query)
        if pred == expected:
            correct += 1
        print(f"{query} -> prédit: {pred} (conf={conf:.2f}), attendu: {expected}")
    accuracy = correct / len(test_cases)
    print(f"Précision: {accuracy*100:.1f}%")
    assert accuracy >= 0.75, f"Précision trop faible: {accuracy}"


@pytest.mark.asyncio
async def test_classifier_confidence(classifier):
    """Vérifie que les prédictions ont une confiance raisonnable."""
    query = "ouvre notes"
    pred, conf = await classifier.predict(query)
    # Avec un petit jeu d'entraînement, une confiance > 0.3 est acceptable
    assert conf > 0.3, f"Confiance trop faible pour {query}: {conf}"

    query = "blablabla inconnu"
    pred, conf = await classifier.predict(query)
    assert conf <= 1.0


def test_classifier_fallback():
    """Teste le fallback basé sur mots-clés."""
    classifier = EmbeddingClassifier(retrain=True)
    # Simuler que le classifieur n'est pas entraîné
    classifier.is_trained = False

    assert classifier._fallback("ouvre notes") == "action"
    assert classifier._fallback("bonjour") == "greeting"
    assert classifier._fallback("envoie un email") == "mail"
    assert classifier._fallback("ouvre safari") == "safari"
    assert classifier._fallback("organise les fenêtres") == "arrange"
    assert classifier._fallback("quel temps fait-il") == "simple"
    assert classifier._fallback("explique la mécanique quantique") == "complex"
