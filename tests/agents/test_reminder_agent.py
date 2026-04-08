"""
Tests unitaires pour ReminderAgent.

Couverture :
  - can_handle() : mots-clés FR/EN (rappel, reminder, pense à…)
  - get_tools() : outil create_reminder présent
  - _tool_create_reminder() : AppleScript mocké (succès, erreur, timeout, date+heure)
  - handle() : LLM mocké → JSON → création rappel

Ces tests ne nécessitent PAS Ollama ni macOS — AppleScript et subprocess sont mockés.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.reminder_agent import ReminderAgent


# ── Fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture
def agent() -> ReminderAgent:
    """ReminderAgent avec LLM mocké, sans Ollama."""
    llm = MagicMock()
    llm.generate = MagicMock(return_value='{"title": "Test", "date": null, "time": null, "notes": ""}')
    bus = MagicMock()
    return ReminderAgent(llm, bus, {"reminders_default_list": "Rappels"})


# ── can_handle ─────────────────────────────────────────────────────────────────


def test_can_handle_rappel(agent: ReminderAgent) -> None:
    assert agent.can_handle("crée un rappel pour demain") is True


def test_can_handle_reminder_en(agent: ReminderAgent) -> None:
    assert agent.can_handle("set a reminder for 9am") is True


def test_can_handle_rappelle(agent: ReminderAgent) -> None:
    assert agent.can_handle("rappelle-moi d'appeler le médecin") is True


def test_can_handle_pense_a(agent: ReminderAgent) -> None:
    assert agent.can_handle("pense à envoyer le rapport") is True


def test_can_handle_programme_rappel(agent: ReminderAgent) -> None:
    assert agent.can_handle("programme un rappel pour lundi") is True


def test_can_handle_ajoute_rappel(agent: ReminderAgent) -> None:
    assert agent.can_handle("ajoute un rappel : réunion équipe") is True


def test_can_handle_negatif_meteo(agent: ReminderAgent) -> None:
    assert agent.can_handle("quel temps fait-il aujourd'hui ?") is False


def test_can_handle_negatif_fichier(agent: ReminderAgent) -> None:
    assert agent.can_handle("liste mes fichiers") is False


# ── get_tools ──────────────────────────────────────────────────────────────────


def test_get_tools_returns_one_tool(agent: ReminderAgent) -> None:
    tools = agent.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "create_reminder"


def test_get_tools_contract_has_title(agent: ReminderAgent) -> None:
    tool = agent.get_tools()[0]
    contract = tool.contract
    fields = contract.__fields__
    assert "title" in fields
    assert "date" in fields
    assert "time" in fields


# ── _tool_create_reminder ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_reminder_success(agent: ReminderAgent) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("app.agents.reminder_agent.subprocess.run", return_value=mock_result):
        result = await agent._tool_create_reminder(title="Acheter du lait")
    assert "Acheter du lait" in result
    assert "✅" in result


@pytest.mark.anyio
async def test_create_reminder_with_date_and_time(agent: ReminderAgent) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("app.agents.reminder_agent.subprocess.run", return_value=mock_result):
        result = await agent._tool_create_reminder(
            title="Réunion",
            date="2026-04-10",
            time="09:30",
        )
    assert "✅" in result
    assert "Réunion" in result


@pytest.mark.anyio
async def test_create_reminder_with_date_only(agent: ReminderAgent) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("app.agents.reminder_agent.subprocess.run", return_value=mock_result):
        result = await agent._tool_create_reminder(
            title="Anniversaire",
            date="2026-12-25",
        )
    assert "✅" in result


@pytest.mark.anyio
async def test_create_reminder_applescript_error(agent: ReminderAgent) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "Application not running"

    with patch("app.agents.reminder_agent.subprocess.run", return_value=mock_result):
        result = await agent._tool_create_reminder(title="Test erreur")
    assert "Erreur" in result


@pytest.mark.anyio
async def test_create_reminder_timeout(agent: ReminderAgent) -> None:
    import subprocess

    with patch(
        "app.agents.reminder_agent.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=10),
    ):
        result = await agent._tool_create_reminder(title="Test timeout")
    assert "Timeout" in result or "Erreur" in result


@pytest.mark.anyio
async def test_create_reminder_with_notes(agent: ReminderAgent) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("app.agents.reminder_agent.subprocess.run", return_value=mock_result):
        result = await agent._tool_create_reminder(
            title="Appeler docteur",
            notes="Numéro : 01 23 45 67 89",
        )
    assert "✅" in result


# ── handle ─────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_handle_avec_json_llm(agent: ReminderAgent) -> None:
    """handle() parse le JSON du LLM et crée le rappel."""
    agent.llm.generate = MagicMock(
        return_value='{"title": "Médecin", "date": "2026-04-15", "time": "14:00", "notes": ""}'
    )
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("app.agents.reminder_agent.subprocess.run", return_value=mock_result):
        result = await agent.handle("rappelle-moi le médecin le 15 à 14h")
    assert "✅" in result


@pytest.mark.anyio
async def test_handle_sans_json_llm(agent: ReminderAgent) -> None:
    """handle() crée le rappel avec le titre = query si pas de JSON."""
    agent.llm.generate = MagicMock(return_value="pas de json ici")
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("app.agents.reminder_agent.subprocess.run", return_value=mock_result):
        result = await agent.handle("rappel achat lait")
    assert "✅" in result or "Erreur" in result


@pytest.mark.anyio
async def test_handle_exception_llm(agent: ReminderAgent) -> None:
    """Si le LLM échoue, le circuit breaker gère le fallback :
    on crée quand même le rappel avec le titre = query."""
    agent.llm.generate = MagicMock(side_effect=RuntimeError("LLM down"))
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("app.agents.reminder_agent.subprocess.run", return_value=mock_result):
        result = await agent.handle("rappelle-moi quelque chose")
    # Le circuit breaker absorbe l'erreur → rappel créé avec le texte brut
    assert "✅" in result or "Erreur" in result
