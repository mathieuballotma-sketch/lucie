"""Pytest conftest — assure l'isolation des tests qui rechargent des modules.

`test_article_validator.py` utilise `importlib.reload(cfg)` + `reload(av)` dans
ses fixtures pour injecter une DB Légifrance factice. Le `monkeypatch.setenv`
restaure les env vars en teardown, MAIS les constantes Python capturées au
niveau module (`config.LEGIFRANCE_ENABLED`, import de
`article_validator.LEGIFRANCE_ENABLED` depuis config) restent figées sur la
valeur captée au moment du reload.

Sans cette réinitialisation, les tests suivants (`test_cerveau_oiseaux.py`)
voient un `article_validator` qui croit Légifrance activée et pointe vers un
tmp_path disparu — ou pire, se rabat sur la DB Légifrance réelle (~4.6 GB)
et exécute des requêtes de 12 s. D'où ce fixture autouse qui recharge les
modules à l'état par défaut après CHAQUE test qui en a reloaded.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _reset_article_validator_module():
    """Recharge config + article_validator depuis l'état d'environnement actuel
    après chaque test. No-op pour les tests qui ne touchent pas ces modules ;
    salvateur pour ceux qui `importlib.reload` à l'intérieur d'un scope
    `monkeypatch.setenv`."""
    yield
    try:
        import lucie_v1_standalone.config as cfg
        import lucie_v1_standalone.dialogue.article_validator as av
        importlib.reload(cfg)
        importlib.reload(av)
        av.clear_validator_cache()
    except Exception:
        # Pas d'obstacle au reporting de test en cas de soucis de reload.
        pass
