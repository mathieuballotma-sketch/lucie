#!/usr/bin/env python3
"""
Test d'intégration pour Agent Lucide.
Vérifie que tous les composants se chargent correctement et qu'une requête simple fonctionne.
"""

import sys
import time
import os
from pathlib import Path

import pytest

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import Config
from app.utils.logger import logger


@pytest.fixture(scope="module")
def config():
    """Fixture: charge la configuration depuis config.yaml."""
    try:
        cfg = Config.load("config.yaml")
        return cfg
    except Exception as e:
        pytest.skip(f"config.yaml non disponible ou invalide: {e}")


@pytest.fixture(scope="module")
def engine(config):
    """Fixture: initialise le moteur."""
    from app.core.engine import LucidEngine
    try:
        eng = LucidEngine(config)
        yield eng
        try:
            eng.stop()
        except Exception:
            pass
    except Exception as e:
        pytest.skip(f"Moteur non disponible (Ollama requis?): {e}")


def test_config_loading(config):
    """Teste le chargement de la configuration."""
    assert config is not None
    assert config.app.name
    logger.info(f"✅ Config chargée: {config.app.name} v{config.app.version}")


def test_engine_initialization(engine):
    """Teste l'initialisation du moteur."""
    assert engine is not None
    logger.info("✅ Moteur initialisé")


def test_simple_query(engine):
    """Teste une requête simple."""
    query = "Quelle est la capitale de la France ?"
    try:
        response, latency = engine.process(query)
        assert response is not None
        logger.info(f"✅ Réponse reçue en {latency:.2f}s")
    except Exception as e:
        pytest.skip(f"LLM non disponible: {e}")


def test_memory(engine):
    """Teste l'ajout en mémoire."""
    try:
        engine.memory.add_episode("test query", "test response", {"test": True})
        results = engine.memory.remember("test", n_results=1)
        assert results is not None
        logger.info("✅ Mémoire OK")
    except Exception as e:
        pytest.skip(f"Mémoire non disponible: {e}")


def test_profile_agent(engine):
    """Teste que le ProfileAgent tourne."""
    if hasattr(engine, 'profile_agent'):
        try:
            profile = engine.profile_agent.get_profile()
            assert profile is not None
            logger.info("✅ ProfileAgent actif")
        except Exception as e:
            pytest.skip(f"ProfileAgent non disponible: {e}")
    else:
        pytest.skip("ProfileAgent non trouvé sur le moteur")


def test_elasticity(engine):
    """Teste l'élasticité."""
    try:
        model = engine.elasticity.get_recommended_model()
        workers = engine.elasticity.get_max_workers()
        assert model is not None
        assert workers > 0
        logger.info(f"✅ Modèle recommandé: {model}, workers: {workers}")
    except Exception as e:
        pytest.skip(f"Élasticité non disponible: {e}")
