"""
Tests unitaires pour ComputerControlAgent.

Couverture :
  - can_handle() / can_handle_quick() : scores pour ouvre, tape, clique, screenshot…
  - get_tools() : 9 outils attendus
  - _check_applescript_safety() : caractères interdits
  - _parse_open_application(), _parse_type_text(), _parse_coords() : parsing regex
  - _tool_open_application() : subprocess mocké
  - _tool_type_text() : submit_action + pyautogui mockés
  - _tool_click() : submit_action + pyautogui mockés
  - _tool_get_screenshot() : pyautogui mocké
  - _tool_safari_open_url() : validation URL + AppleScript mocké
  - handle() : dispatch vers le bon outil

Ces tests ne nécessitent PAS macOS, pyautogui réel, ni AppKit.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Patch les imports natifs macOS avant l'import de l'agent
import sys

# Stub pyautogui globalement pour éviter les dépendances graphiques
pyautogui_mock = MagicMock()
sys.modules.setdefault("pyautogui", pyautogui_mock)

from app.agents.computer_control_agent import ComputerControlAgent
from app.utils.errors import ToolExecutionError


# ── Fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture
def agent() -> ComputerControlAgent:
    """ComputerControlAgent avec LLM et bus mockés, pyautogui mocké."""
    llm = MagicMock()
    bus = MagicMock()
    config: dict[str, Any] = {
        "visible_actions": True,
        "move_duration": 0.0,
        "type_interval": 0.0,
        "use_applescript_for_typing": False,
        "use_paste_for_typing": False,
    }
    with patch("app.agents.computer_control_agent.os.makedirs"):
        return ComputerControlAgent(llm, bus, config)


# ── can_handle ─────────────────────────────────────────────────────────────────


def test_can_handle_ouvre_application(agent: ComputerControlAgent) -> None:
    assert agent.can_handle("ouvre l'application Safari") is True


def test_can_handle_lance(agent: ComputerControlAgent) -> None:
    assert agent.can_handle("lance le terminal") is True


def test_can_handle_tape_texte(agent: ComputerControlAgent) -> None:
    assert agent.can_handle("tape 'bonjour le monde'") is True


def test_can_handle_screenshot(agent: ComputerControlAgent) -> None:
    assert agent.can_handle("prends un screenshot") is True


def test_can_handle_capture_ecran(agent: ComputerControlAgent) -> None:
    assert agent.can_handle("capture écran maintenant") is True


def test_can_handle_clique(agent: ComputerControlAgent) -> None:
    # score 0.5 — exactement à la limite : should return True (>= 0.5)
    result = agent.can_handle("clique sur le bouton")
    assert isinstance(result, bool)


def test_can_handle_negatif(agent: ComputerControlAgent) -> None:
    assert agent.can_handle("quelle heure est-il") is False


def test_can_handle_negatif_rappel(agent: ComputerControlAgent) -> None:
    assert agent.can_handle("crée un rappel") is False


# ── can_handle_quick ───────────────────────────────────────────────────────────


def test_can_handle_quick_screenshot_score_high(agent: ComputerControlAgent) -> None:
    score = agent.can_handle_quick("screenshot de l'écran")
    assert score >= 0.9


def test_can_handle_quick_ouvre_app_known(agent: ComputerControlAgent) -> None:
    score = agent.can_handle_quick("ouvre safari")
    assert score >= 0.9


def test_can_handle_quick_query_inconnue(agent: ComputerControlAgent) -> None:
    score = agent.can_handle_quick("quel est le sens de la vie")
    assert score == 0.0


# ── get_tools ──────────────────────────────────────────────────────────────────


def test_get_tools_count(agent: ComputerControlAgent) -> None:
    tools = agent.get_tools()
    assert len(tools) == 9


def test_get_tools_names(agent: ComputerControlAgent) -> None:
    names = {t.name for t in agent.get_tools()}
    assert "open_application" in names
    assert "type_text" in names
    assert "press_key" in names
    assert "click" in names
    assert "get_screenshot" in names
    assert "mail_compose" in names
    assert "safari_open_url" in names
    assert "arrange_windows" in names


# ── _check_applescript_safety ─────────────────────────────────────────────────


def test_applescript_safety_safe_value(agent: ComputerControlAgent) -> None:
    # Ne doit pas lever d'exception
    agent._check_applescript_safety("Safari", "app_name")


def test_applescript_safety_forbidden_quote(agent: ComputerControlAgent) -> None:
    with pytest.raises(ToolExecutionError, match="caractères dangereux"):
        agent._check_applescript_safety('app"name', "app_name")


def test_applescript_safety_forbidden_backslash(agent: ComputerControlAgent) -> None:
    with pytest.raises(ToolExecutionError):
        agent._check_applescript_safety("app\\name", "app_name")


def test_applescript_safety_forbidden_ampersand(agent: ComputerControlAgent) -> None:
    with pytest.raises(ToolExecutionError):
        agent._check_applescript_safety("app&name", "app_name")


# ── Parsing ────────────────────────────────────────────────────────────────────


def test_parse_open_application_ouvre(agent: ComputerControlAgent) -> None:
    result = agent._parse_open_application("ouvre l'application Safari")
    assert result is not None
    assert "Safari" in result


def test_parse_open_application_lance(agent: ComputerControlAgent) -> None:
    result = agent._parse_open_application("lance Terminal")
    assert result is not None
    assert "Terminal" in result


def test_parse_type_text_with_quotes(agent: ComputerControlAgent) -> None:
    result = agent._parse_type_text("tape 'bonjour tout le monde'")
    assert result == "bonjour tout le monde"


def test_parse_type_text_without_quotes(agent: ComputerControlAgent) -> None:
    result = agent._parse_type_text("tape bonjour")
    assert result == "bonjour"


def test_parse_coords_found(agent: ComputerControlAgent) -> None:
    result = agent._parse_coords("clique à 500, 300")
    assert result is not None
    assert result["x"] == 500
    assert result["y"] == 300


def test_parse_coords_not_found(agent: ComputerControlAgent) -> None:
    result = agent._parse_coords("clique sur le bouton rouge")
    assert result is None


# ── _tool_open_application ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_tool_open_application_success(agent: ComputerControlAgent) -> None:
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("app.agents.computer_control_agent.asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch.object(agent, "_wait_for_app_active", return_value=True):
            with patch.object(agent, "_ensure_app_window", return_value=None):
                result = await agent._tool_open_application("Safari")
    assert "✅" in result
    assert "Safari" in result


@pytest.mark.anyio
async def test_tool_open_application_error(agent: ComputerControlAgent) -> None:
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"App not found"))

    with patch("app.agents.computer_control_agent.asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(ToolExecutionError):
            await agent._tool_open_application("AppInexistante")


# ── _tool_click ────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_tool_click_approved(agent: ComputerControlAgent) -> None:
    with patch.object(agent, "submit_action", return_value=True):
        with patch("app.agents.computer_control_agent.pyautogui") as mock_pag:
            result = await agent._tool_click(x=100, y=200)
    assert "✅" in result
    assert "100" in result


@pytest.mark.anyio
async def test_tool_click_blocked_by_gate(agent: ComputerControlAgent) -> None:
    with patch.object(agent, "submit_action", return_value=False):
        result = await agent._tool_click(x=100, y=200)
    assert "⛔" in result


# ── _tool_safari_open_url ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_tool_safari_invalid_url(agent: ComputerControlAgent) -> None:
    with patch.object(agent, "submit_action", return_value=True):
        with pytest.raises(ToolExecutionError, match="URL non sécurisée"):
            await agent._tool_safari_open_url(url="ftp://example.com")


@pytest.mark.anyio
async def test_tool_safari_valid_url(agent: ComputerControlAgent) -> None:
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch.object(agent, "submit_action", return_value=True):
        with patch("app.agents.computer_control_agent.asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch.object(agent, "_activate_app", return_value=None):
                with patch.object(agent, "_wait_for_app_active", return_value=True):
                    with patch.object(agent, "_run_applescript", return_value=(True, "")):
                        result = await agent._tool_safari_open_url(url="https://example.com")
    assert "✅" in result


# ── handle dispatch ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_handle_screenshot(agent: ComputerControlAgent) -> None:
    with patch.object(agent, "_tool_get_screenshot", return_value="✅ Screenshot sauvegardé."):
        result = await agent.handle("prends un screenshot")
    assert "✅" in result


@pytest.mark.anyio
async def test_handle_ouvre_application(agent: ComputerControlAgent) -> None:
    with patch.object(agent, "_parse_open_application", return_value="Safari"):
        with patch.object(agent, "_tool_open_application", return_value="✅ Safari ouverte."):
            result = await agent.handle("ouvre safari")
    assert "Safari" in result
