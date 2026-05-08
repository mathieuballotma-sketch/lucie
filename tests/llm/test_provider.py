"""
Tests unitaires LLMProvider Protocol + OllamaProvider.
Utilise un mock httpx — aucun appel réseau.
"""

import json
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from lucie_v1_standalone.llm.provider import LLMProvider
from lucie_v1_standalone.llm.ollama_provider import OllamaProvider


# ---------------------------------------------------------------------------
# Protocol conformity
# ---------------------------------------------------------------------------

def test_ollama_provider_is_llm_provider() -> None:
    """OllamaProvider satisfait le LLMProvider Protocol."""
    provider = OllamaProvider()
    assert isinstance(provider, LLMProvider)


# ---------------------------------------------------------------------------
# generate() sync
# ---------------------------------------------------------------------------

def _make_response(text: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"response": text, "done": True}
    resp.raise_for_status = MagicMock()
    return resp


@patch("lucie_v1_standalone.llm.ollama_provider.httpx.Client")
def test_generate_returns_text(mock_client_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_client.post.return_value = _make_response("Réponse simulée")

    provider = OllamaProvider(model="test-model")
    result = provider.generate("test prompt")

    assert result == "Réponse simulée"
    mock_client.post.assert_called_once()
    call_json = mock_client.post.call_args[1]["json"]
    assert call_json["model"] == "test-model"
    assert call_json["stream"] is False


@patch("lucie_v1_standalone.llm.ollama_provider.httpx.Client")
def test_generate_retries_on_empty(mock_client_cls: MagicMock) -> None:
    """Retry automatique si première réponse vide (bug gemma4:e4b first-call)."""
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    empty_resp = _make_response("")
    real_resp = _make_response("Réponse après retry")
    mock_client.post.side_effect = [empty_resp, real_resp]

    provider = OllamaProvider()
    result = provider.generate("test prompt")

    assert result == "Réponse après retry"
    assert mock_client.post.call_count == 2


@patch("lucie_v1_standalone.llm.ollama_provider.httpx.Client")
def test_generate_passes_options(mock_client_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_client.post.return_value = _make_response("ok")

    provider = OllamaProvider()
    provider.generate("test", options={"num_ctx": 4096, "temperature": 0.3})

    call_json = mock_client.post.call_args[1]["json"]
    assert call_json["options"]["num_ctx"] == 4096
    assert call_json["options"]["temperature"] == 0.3


@patch("lucie_v1_standalone.llm.ollama_provider.httpx.Client")
def test_generate_passes_system_and_keep_alive(mock_client_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_client.post.return_value = _make_response("ok")

    provider = OllamaProvider()
    provider.generate("test", system="Tu es Beaume.", keep_alive="5m")

    call_json = mock_client.post.call_args[1]["json"]
    assert call_json["system"] == "Tu es Beaume."
    assert call_json["keep_alive"] == "5m"


# ---------------------------------------------------------------------------
# available_models()
# ---------------------------------------------------------------------------

@patch("lucie_v1_standalone.llm.ollama_provider.httpx.Client")
def test_available_models(mock_client_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    resp = MagicMock()
    resp.json.return_value = {"models": [{"name": "gemma4:e4b"}, {"name": "gemma4:e2b"}]}
    resp.raise_for_status = MagicMock()
    mock_client.get.return_value = resp

    provider = OllamaProvider()
    models = provider.available_models()

    assert "gemma4:e4b" in models
    assert "gemma4:e2b" in models


@patch("lucie_v1_standalone.llm.ollama_provider.httpx.Client")
def test_available_models_returns_empty_on_error(mock_client_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_client.get.side_effect = Exception("connexion refusée")

    provider = OllamaProvider()
    models = provider.available_models()

    assert models == []


# ---------------------------------------------------------------------------
# from_config()
# ---------------------------------------------------------------------------

def test_from_config() -> None:
    provider = OllamaProvider.from_config({
        "base_url": "http://192.168.1.1:11434",
        "timeout": 60.0,
        "model": "gemma4:e2b",
    })
    assert provider._base_url == "http://192.168.1.1:11434"
    assert provider._timeout == 60.0
    assert provider._model == "gemma4:e2b"
