"""Tests R2 — warm-up Ollama au boot HUD (sprint S1 Speed-Optimizer).

Ces tests vérifient le contrat de _warmup_blocking sans dépendre d'Ollama
ni de PyObjC. _warmup_blocking est exécuté dans un thread séparé pour
respecter son assertion interne (garde-fou anti main-thread).
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest


def _run_in_thread(target, timeout: float = 5.0) -> None:
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=timeout)
    assert not t.is_alive(), "_warmup_blocking n'a pas terminé dans le timeout"


def test_warmup_calls_generate_with_one_token(monkeypatch):
    """Le warm-up doit appeler ollama_client.generate avec num_predict=1
    sur SPEED_MODEL."""
    monkeypatch.delenv("LUCIE_SKIP_WARMUP", raising=False)
    captured = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return ""

    def worker():
        with patch(
            "lucie_v1_standalone.ollama_client.generate",
            side_effect=fake_generate,
        ):
            from main_hud import _warmup_blocking
            _warmup_blocking()

    _run_in_thread(worker)
    assert captured.get("model") == "gemma4:e4b"
    assert captured.get("options", {}).get("num_predict") == 1
    assert captured.get("options", {}).get("temperature") == 0


def test_warmup_skipped_when_env_set(monkeypatch):
    """LUCIE_SKIP_WARMUP=1 → generate ne doit jamais être appelée."""
    monkeypatch.setenv("LUCIE_SKIP_WARMUP", "1")
    called = False

    async def fake_generate(**kwargs):
        nonlocal called
        called = True
        return ""

    def worker():
        with patch(
            "lucie_v1_standalone.ollama_client.generate",
            side_effect=fake_generate,
        ):
            from main_hud import _warmup_blocking
            _warmup_blocking()

    _run_in_thread(worker)
    assert called is False


def test_warmup_swallows_exception(monkeypatch):
    """Une exception dans generate ne doit jamais remonter — l'UI doit
    démarrer même si Ollama est down."""
    monkeypatch.delenv("LUCIE_SKIP_WARMUP", raising=False)

    async def fake_generate(**kwargs):
        raise RuntimeError("ollama down")

    raised = []

    def worker():
        try:
            with patch(
                "lucie_v1_standalone.ollama_client.generate",
                side_effect=fake_generate,
            ):
                from main_hud import _warmup_blocking
                _warmup_blocking()
        except Exception as exc:  # noqa: BLE001
            raised.append(exc)

    _run_in_thread(worker)
    assert raised == [], f"exception non avalée: {raised}"


def test_warmup_main_thread_assertion(monkeypatch):
    """Sur le main thread, _warmup_blocking doit AssertionError (garde-fou
    anti AppKit/asyncio)."""
    monkeypatch.delenv("LUCIE_SKIP_WARMUP", raising=False)
    from main_hud import _warmup_blocking

    with pytest.raises(AssertionError):
        _warmup_blocking()
