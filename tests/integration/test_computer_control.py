# tests/integration/test_computer_control.py
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.computer_control_agent import ComputerControlAgent
from app.utils.errors import ToolExecutionError


class MockApp:
    def __init__(self, name):
        self._name = name
        self._pid = 1234

    def localizedName(self):
        return self._name

    def processIdentifier(self):
        return self._pid


@pytest.fixture
def mock_appkit(monkeypatch):
    """Remplace AppKit dans l'agent par un mock pour éviter les appels réels."""
    patcher = patch('app.agents.computer_control_agent.AppKit')
    mock_kit = patcher.start()
    mock_workspace = MagicMock()
    mock_kit.NSWorkspace.sharedWorkspace.return_value = mock_workspace
    mock_kit.NSScreen = MagicMock()
    yield mock_workspace
    patcher.stop()


@pytest.fixture
def agent(mock_appkit):
    """Crée une instance de l'agent avec des mocks pour les appels système."""
    llm_mock = MagicMock()
    bus_mock = MagicMock()
    config = {}
    agent = ComputerControlAgent(llm_mock, bus_mock, config)
    # Remplacer les méthodes asynchrones par des mocks pour contrôler le comportement
    agent._run_applescript = AsyncMock(return_value=(True, ""))
    agent._activate_app = AsyncMock()
    agent._wait_for_app_active = AsyncMock(return_value=True)
    return agent


@pytest.mark.asyncio
async def test_open_application_already_running(agent, mock_appkit):
    """Teste l'ouverture d'une application via subprocess (réussit)."""
    with patch('asyncio.create_subprocess_exec') as mock_subprocess:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))
        mock_subprocess.return_value = mock_process

        result = await agent._tool_open_application("Notes")

    mock_subprocess.assert_called_once_with(
        "open", "-a", "Notes",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE
    )
    assert "ouverte" in result


@pytest.mark.asyncio
async def test_open_application_not_running(agent, mock_appkit):
    """Teste l'ouverture d'une application non en cours d'exécution."""
    mock_appkit.runningApplications.return_value = []

    with patch('asyncio.create_subprocess_exec') as mock_subprocess:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))
        mock_subprocess.return_value = mock_process

        result = await agent._tool_open_application("Calculator")

    # Vérifier que le sous-processus a été appelé pour lancer l'application
    mock_subprocess.assert_called_once_with(
        "open", "-a", "Calculator",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE
    )
    assert "ouverte" in result


@pytest.mark.asyncio
async def test_open_application_fallback_on_exception(agent, mock_appkit):
    """Teste que ToolExecutionError est levée si le subprocess échoue."""
    with patch('asyncio.create_subprocess_exec') as mock_subprocess:
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"Application introuvable"))
        mock_subprocess.return_value = mock_process

        with pytest.raises(ToolExecutionError):
            await agent._tool_open_application("AppInexistante")
