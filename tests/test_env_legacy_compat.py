"""Tests du fallback compat `env_legacy` (Sprint 1ter rebrand).

Vérifie que :
  - `BEAUME_*` est prioritaire sur `LUCIE_*` ;
  - en absence de `BEAUME_*`, `LUCIE_*` est lu (alias deprecated) ;
  - un `DeprecationWarning` est émis sur usage de `LUCIE_*` ;
  - un log WARNING est produit (unique par variable) ;
  - le `default` s'applique si aucune des deux n'est définie.
"""

from __future__ import annotations

import logging
import warnings

import pytest

from lucie_v1_standalone.config import env_legacy
from lucie_v1_standalone import config as config_mod


@pytest.fixture(autouse=True)
def _reset_warned_legacy():
    """Vide le cache de warnings entre tests pour isoler les assertions."""
    config_mod._warned_legacy.clear()
    yield
    config_mod._warned_legacy.clear()


def test_beaume_takes_priority(monkeypatch):
    monkeypatch.setenv("BEAUME_FOO_TEST", "new")
    monkeypatch.setenv("LUCIE_FOO_TEST", "legacy")
    assert env_legacy("FOO_TEST") == "new"


def test_lucie_fallback_when_beaume_absent(monkeypatch, caplog):
    monkeypatch.delenv("BEAUME_FOO_TEST", raising=False)
    monkeypatch.setenv("LUCIE_FOO_TEST", "legacy")
    with caplog.at_level(logging.WARNING, logger="lucie_v1_standalone.config"):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            value = env_legacy("FOO_TEST")
    assert value == "legacy"
    assert any(
        issubclass(w.category, DeprecationWarning) and "LUCIE_FOO_TEST" in str(w.message)
        for w in captured
    ), "DeprecationWarning attendu pour LUCIE_FOO_TEST"
    assert any("LUCIE_FOO_TEST" in rec.message for rec in caplog.records), (
        "log WARNING attendu pour LUCIE_FOO_TEST"
    )


def test_default_when_neither_set(monkeypatch):
    monkeypatch.delenv("BEAUME_FOO_TEST", raising=False)
    monkeypatch.delenv("LUCIE_FOO_TEST", raising=False)
    assert env_legacy("FOO_TEST", "fallback") == "fallback"
    assert env_legacy("FOO_TEST") is None


def test_warning_emitted_only_once(monkeypatch, caplog):
    monkeypatch.delenv("BEAUME_FOO_TEST", raising=False)
    monkeypatch.setenv("LUCIE_FOO_TEST", "x")
    with caplog.at_level(logging.WARNING, logger="lucie_v1_standalone.config"):
        env_legacy("FOO_TEST")
        env_legacy("FOO_TEST")
        env_legacy("FOO_TEST")
    warnings_count = sum(
        1 for rec in caplog.records if "LUCIE_FOO_TEST" in rec.message
    )
    assert warnings_count == 1, (
        f"Le log WARNING doit être émis une seule fois par variable, vu {warnings_count}"
    )
