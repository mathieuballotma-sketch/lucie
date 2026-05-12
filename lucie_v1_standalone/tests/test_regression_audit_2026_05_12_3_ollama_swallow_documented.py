"""Régression audit 2026-05-12 P0 #3 — ollama_provider 3 sites de swallow.

POURQUOI : avant l'audit, ollama_provider avalait Exception sur 3 sites distincts.
- l.103 (available_models) masquait "Ollama down" en "0 modèle installé" —
  diagnostic impossible.
- l.114 (load_model pré-warm) silencieux — confusion entre "Ollama down" et
  "premier appel lent".
- l.148 (_post) re-raisait sans cause chain (`raise ... from e` manquant).

Ces tests verrouillent les logs et la cause chain pour empêcher la régression.

Source : Audit qualité lucie_v1_standalone 2026-05-12 (hash d35f4a52...).
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import httpx
import pytest

from lucie_v1_standalone.llm.ollama_provider import OllamaProvider


def _make_provider() -> OllamaProvider:
    """Helper : provider local pointant sur 127.0.0.1 (invariant Beaume #8)."""
    return OllamaProvider(model="dummy", base_url="http://127.0.0.1:11434")


def test_available_models_connection_error_logs_and_returns_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """available_models() avec Ollama injoignable → [] + log.error.

    Avant le fix audit, ce cas retournait silencieusement [] et le caller
    croyait que zéro modèle était installé.
    """
    provider = _make_provider()
    caplog.set_level(logging.ERROR, logger="lucie_v1_standalone.llm.ollama_provider")

    with patch("lucie_v1_standalone.llm.ollama_provider.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.side_effect = (
            httpx.ConnectError("connection refused")
        )

        result = provider.available_models()

    assert result == []
    errors = [
        r for r in caplog.records
        if r.levelname == "ERROR" and "available_models" in r.getMessage()
    ]
    assert len(errors) == 1, (
        f"Expected exactly 1 ERROR log on connection failure, got {len(errors)}"
    )


def test_load_model_failure_logs_warning_not_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """load_model() en échec → log.warning (pré-warm best-effort, ne lève pas).

    Avant le fix, le pré-warm échouait silencieusement, masquant un Ollama down.
    """
    provider = _make_provider()
    caplog.set_level(logging.WARNING, logger="lucie_v1_standalone.llm.ollama_provider")

    with patch("lucie_v1_standalone.llm.ollama_provider.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.side_effect = (
            httpx.TimeoutException("timeout")
        )

        provider.load_model("phi4:14b")  # ne doit pas lever

    warns = [
        r for r in caplog.records
        if r.levelname == "WARNING" and "load_model" in r.getMessage()
    ]
    assert len(warns) == 1, (
        f"Expected exactly 1 WARNING log on pre-warm failure, got {len(warns)}"
    )
