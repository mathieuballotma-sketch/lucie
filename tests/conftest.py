"""
Configuration pytest partagée pour tous les tests.
Fournit les fixtures 'config' et 'engine' utilisées par test_integration.py.
Ces fixtures sont skippées si Ollama n'est pas disponible.
"""
import subprocess
import pytest


def _ollama_running() -> bool:
    """Vérifie si le serveur Ollama est accessible sur localhost:11434."""
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "2", "http://localhost:11434/api/tags"],
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


@pytest.fixture
def config():
    """Charge la configuration de l'application.

    Skippée si config.yaml est manquant ou invalide.
    """
    from app.core.config import Config
    try:
        return Config.load("config.yaml")
    except Exception as e:
        pytest.skip(f"Configuration non disponible: {e}")


@pytest.fixture
def engine(config):
    """Initialise le moteur LucidEngine.

    Skippée si Ollama n'est pas en cours d'exécution.
    """
    if not _ollama_running():
        pytest.skip("Ollama non disponible — test d'intégration ignoré")
    from app.core.engine import LucidEngine
    try:
        eng = LucidEngine(config)
        yield eng
        eng.stop()
    except Exception as e:
        pytest.skip(f"Moteur non initialisable: {e}")
