"""Tests — setup_logging() : idempotence, LUCIE_QUIET, niveau override.

Note : pytest installe ses propres `LogCaptureHandler` sur le root logger.
Les tests comptent uniquement les handlers *Lucie* (StreamHandler ajouté
par setup_logging + RotatingFileHandler) via un filtre sur le type.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import pytest

from lucie_v1_standalone.logging_config import _SENTINEL, setup_logging


def _count_lucie_handlers(root: logging.Logger) -> int:
    """Handlers installés par setup_logging (ignore ceux de pytest)."""
    count = 0
    for h in root.handlers:
        if isinstance(h, RotatingFileHandler):
            count += 1
        elif isinstance(h, logging.StreamHandler) and not isinstance(
            h, logging.FileHandler
        ) and type(h).__name__ == "StreamHandler":
            # Exclut les LogCaptureHandler de pytest qui héritent aussi
            # de StreamHandler mais ont un autre nom de classe.
            count += 1
    return count


@pytest.fixture
def clean_root_logger():
    """Snapshot du root logger avant test, restauration après."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_sentinel = getattr(root, _SENTINEL, False)
    # On garde les handlers pytest, on enlève juste ceux de Lucie si présents.
    root.handlers = [
        h for h in root.handlers
        if not isinstance(h, RotatingFileHandler)
        and type(h).__name__ != "StreamHandler"
    ]
    if hasattr(root, _SENTINEL):
        delattr(root, _SENTINEL)
    yield root
    root.handlers = saved_handlers
    root.level = saved_level
    if saved_sentinel:
        setattr(root, _SENTINEL, True)
    elif hasattr(root, _SENTINEL):
        delattr(root, _SENTINEL)


def test_setup_logging_installs_two_handlers(clean_root_logger, monkeypatch):
    """Un StreamHandler + un RotatingFileHandler après setup_logging()."""
    monkeypatch.delenv("LUCIE_QUIET", raising=False)
    monkeypatch.delenv("LUCIE_LOG_LEVEL", raising=False)
    setup_logging()
    assert _count_lucie_handlers(clean_root_logger) == 2
    assert clean_root_logger.level == logging.INFO
    assert getattr(clean_root_logger, _SENTINEL, False) is True


def test_setup_logging_idempotent(clean_root_logger, monkeypatch):
    """Un second appel ne doit PAS ajouter de handlers Lucie supplémentaires."""
    monkeypatch.delenv("LUCIE_QUIET", raising=False)
    setup_logging()
    count_after_first = _count_lucie_handlers(clean_root_logger)
    setup_logging()
    setup_logging()
    assert _count_lucie_handlers(clean_root_logger) == count_after_first


def test_lucie_quiet_bypass(clean_root_logger, monkeypatch):
    """LUCIE_QUIET=1 → setup_logging est un no-op complet (aucun handler Lucie)."""
    monkeypatch.setenv("LUCIE_QUIET", "1")
    setup_logging()
    assert _count_lucie_handlers(clean_root_logger) == 0
    assert getattr(clean_root_logger, _SENTINEL, False) is False


def test_lucie_log_level_override(clean_root_logger, monkeypatch):
    """LUCIE_LOG_LEVEL=DEBUG doit se refléter sur le root logger."""
    monkeypatch.delenv("LUCIE_QUIET", raising=False)
    monkeypatch.setenv("LUCIE_LOG_LEVEL", "DEBUG")
    setup_logging()
    assert clean_root_logger.level == logging.DEBUG
