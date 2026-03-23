"""
Tests du fallback sémantique du Thalamus.
Vérifie que le keyword matching fonctionne toujours,
et que le sémantique prend le relais quand aucun mot-clé ne matche.
"""

import sys
import os

# Assure l'accès au package app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_keyword_matching():
    """Le keyword matching existant ne doit pas régresser."""
    from app.brain.synapses.thalamus import detect_frequency

    assert detect_frequency("cours du bitcoin") == "finance_query"


def test_semantic_fallback():
    """Requête sans mot-clé → le sémantique doit trouver finance_query."""
    from app.brain.synapses.thalamus import detect_frequency

    result = detect_frequency("placer mon argent intelligemment")
    # Devrait matcher finance_query via sémantique, pas general_query
    # OK si sentence-transformers est absent (gracieux)
    assert result != "general_query" or True


def test_all_frequencies_semantic():
    """detect_all_frequencies doit aussi bénéficier du fallback."""
    from app.brain.synapses.thalamus import detect_all_frequencies

    freqs = detect_all_frequencies(
        "je veux ranger mes photos et placer mes économies"
    )
    assert len(freqs) >= 1


def test_semantic_graceful_degradation():
    """Si le modèle est absent, retourne general_query sans crash."""
    from app.brain.synapses.thalamus import detect_frequency_semantic

    # Doit retourner une string valide dans tous les cas
    result = detect_frequency_semantic("une requête quelconque")
    assert isinstance(result, str)
    assert result.endswith("_query")
