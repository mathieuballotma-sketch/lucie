"""Régression Sprint 6 P2c-2 — pinning déterministe transport Ollama.

POURQUOI : selon `docs/architecture.md`, output(X) = constante n'est garanti
pour un appel LLM Ollama que si `temperature=0` ET un seed fixe sont passés
dans le payload. Sans cela, la batterie 50q mesure du bruit (variance LLM)
en plus du signal P2c-1 (prompt enrichi). Le module
`lucie_v1_standalone.llm.determinism` injecte ces deux paramètres au niveau
transport (ollama_client + ollama_provider) plutôt que par agent — un seul
point de vérité, audit grep-able, garantie inviolable contre l'oubli.

Tests :
  1. unit `apply_deterministic_options` — flag on/off, immutabilité, écrasement
  2. intégration `ollama_client.generate` (async, /api/generate) — payload réel
  3. intégration `ollama_provider.OllamaProvider.generate` (sync) — payload réel
  4. `apply_deterministic_options(None)` retourne un dict pinning même sans
     options entrantes (cas d'un agent qui n'a pas de PARAMS spécifiques).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lucie_v1_standalone import ollama_client
from lucie_v1_standalone.llm import determinism
from lucie_v1_standalone.llm.determinism import (
    _DETERMINISTIC_SEED,
    apply_deterministic_options,
    is_deterministic_enabled,
)
from lucie_v1_standalone.llm.ollama_provider import OllamaProvider


# ──────────────────────────────────────────────────────────────────────────────
# 1. Unit — apply_deterministic_options
# ──────────────────────────────────────────────────────────────────────────────


def test_seed_and_temperature_pinned_when_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag par défaut (et explicite "1") → seed=42 + temperature=0 injectés,
    autres clés préservées. Verrouille la propriété fondamentale du module."""
    monkeypatch.setenv("BEAUME_LLM_DETERMINISTIC", "1")
    result = apply_deterministic_options({"num_ctx": 4096, "top_p": 0.9})
    assert result["seed"] == _DETERMINISTIC_SEED == 42
    assert result["temperature"] == 0
    assert result["num_ctx"] == 4096
    assert result["top_p"] == 0.9


def test_no_pinning_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag explicitement off → aucune injection, dict retourné est une copie
    inchangée. Permet `BEAUME_LLM_DETERMINISTIC=0` comme kill-switch propre."""
    monkeypatch.setenv("BEAUME_LLM_DETERMINISTIC", "0")
    result = apply_deterministic_options({"num_ctx": 4096, "temperature": 0.3})
    assert "seed" not in result
    assert result["temperature"] == 0.3, (
        "Flag off ne doit JAMAIS écraser la temperature fournie par l'agent."
    )
    assert result["num_ctx"] == 4096
    assert not is_deterministic_enabled()


def test_temperature_overridden_even_when_already_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag on + temperature=0.3 en entrée (cas REDACTEUR_PARAMS) → écrasée à 0.
    C'est le comportement attendu : le pinning a priorité sur les PARAMS pour
    garantir la reproductibilité de la batterie. La sortie ne dépend plus de
    l'agent qui appelle."""
    monkeypatch.setenv("BEAUME_LLM_DETERMINISTIC", "1")
    result = apply_deterministic_options({"temperature": 0.3})
    assert result["temperature"] == 0


def test_options_none_returns_pinned_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag on + options=None → dict avec seulement seed+temperature. Cas d'un
    appel LLM qui n'a pas de PARAMS spécifiques (ex: petit utilitaire LLM)."""
    monkeypatch.setenv("BEAUME_LLM_DETERMINISTIC", "1")
    result = apply_deterministic_options(None)
    assert result == {"temperature": 0, "seed": _DETERMINISTIC_SEED}


def test_input_dict_is_not_mutated(monkeypatch: pytest.MonkeyPatch) -> None:
    """La fonction retourne une COPIE, jamais le même objet. Protège contre
    des effets de bord sur les dicts `*_PARAMS` partagés au niveau module
    (notamment `REDACTEUR_PARAMS` mutée silencieusement = catastrophe)."""
    monkeypatch.setenv("BEAUME_LLM_DETERMINISTIC", "1")
    original = {"num_ctx": 4096, "temperature": 0.3}
    snapshot = dict(original)
    result = apply_deterministic_options(original)
    assert original == snapshot, "L'argument a été muté — interdiction absolue."
    assert result is not original


# ──────────────────────────────────────────────────────────────────────────────
# 2. Intégration ollama_client.generate (async, /api/generate)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_client_generate_payload_contains_seed_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vérifie qu'un appel réel à `ollama_client.generate` injecte seed+temperature
    dans le payload HTTP, MÊME quand `options=None` côté caller. C'est le
    contrat d'audit : on peut grep `seed` dans le payload pour prouver le pinning."""
    monkeypatch.setenv("BEAUME_LLM_DETERMINISTIC", "1")

    captured_payload: dict[str, Any] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"response": "ok", "total_duration": 0}

    async def fake_post(url: str, json: dict, **_: Any) -> _FakeResponse:
        captured_payload.update(json)
        return _FakeResponse()

    with patch("httpx.AsyncClient") as MockClient:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.post = AsyncMock(side_effect=fake_post)
        MockClient.return_value = instance

        result = await ollama_client.generate(
            model="gemma4:e4b",
            prompt="test",
            system="sys",
            options=None,
        )

    assert result == "ok"
    assert captured_payload["options"]["seed"] == _DETERMINISTIC_SEED
    assert captured_payload["options"]["temperature"] == 0


@pytest.mark.asyncio
async def test_ollama_client_generate_payload_no_seed_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag off → aucun seed dans le payload, et si l'agent ne passe pas d'options,
    le payload ne contient PAS de clé `options` (préserve l'ancien comportement
    strict pour ne pas modifier les statistiques Ollama)."""
    monkeypatch.setenv("BEAUME_LLM_DETERMINISTIC", "0")

    captured_payload: dict[str, Any] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"response": "ok", "total_duration": 0}

    async def fake_post(url: str, json: dict, **_: Any) -> _FakeResponse:
        captured_payload.update(json)
        return _FakeResponse()

    with patch("httpx.AsyncClient") as MockClient:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.post = AsyncMock(side_effect=fake_post)
        MockClient.return_value = instance

        await ollama_client.generate(
            model="gemma4:e4b",
            prompt="test",
            system="sys",
            options=None,
        )

    assert "options" not in captured_payload, (
        "Flag off + options=None : aucune clé options ne doit être posée dans "
        "le payload (préserve la sémantique pré-P2c-2)."
    )


# ──────────────────────────────────────────────────────────────────────────────
# 3. Intégration OllamaProvider.generate (sync, /api/generate)
# ──────────────────────────────────────────────────────────────────────────────


def test_ollama_provider_generate_payload_pinned_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Même propriété que test précédent mais via la classe sync OllamaProvider
    (chemin alternatif). Garantit que les DEUX modules transport partagent la
    même politique de pinning, audit-able par un seul grep `apply_deterministic`."""
    monkeypatch.setenv("BEAUME_LLM_DETERMINISTIC", "1")

    captured_payload: dict[str, Any] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"response": "réponse pinned"}

    def fake_post(url: str, json: dict, **_: Any) -> _FakeResponse:
        captured_payload.update(json)
        return _FakeResponse()

    with patch("httpx.Client") as MockClient:
        instance = MagicMock()
        instance.__enter__ = MagicMock(return_value=instance)
        instance.__exit__ = MagicMock(return_value=False)
        instance.post = MagicMock(side_effect=fake_post)
        MockClient.return_value = instance

        provider = OllamaProvider(model="gemma4:e4b")
        result = provider.generate(
            "Question juridique",
            system="Tu es Beaume.",
            options={"num_ctx": 4096, "temperature": 0.5},
        )

    assert result == "réponse pinned"
    options = captured_payload["options"]
    assert options["seed"] == _DETERMINISTIC_SEED
    assert options["temperature"] == 0, "0.5 doit être écrasé à 0 sous le flag."
    assert options["num_ctx"] == 4096, "Les autres clés doivent rester intactes."


# ──────────────────────────────────────────────────────────────────────────────
# 4. Sentinelle constante seed
# ──────────────────────────────────────────────────────────────────────────────


def test_seed_constant_value_is_42() -> None:
    """Garde-fou anti-changement silencieux de la constante seed. Si quelqu'un
    la modifie en 43, toutes les batteries de mesure historiques deviennent
    incomparables : ce test force une décision consciente accompagnée de
    l'actualisation des références de batterie."""
    assert determinism._DETERMINISTIC_SEED == 42
