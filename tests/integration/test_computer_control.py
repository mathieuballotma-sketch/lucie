# tests/integration/test_computer_control.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.computer_control_agent import ComputerControlAgent


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
    """Remplace AppKit par un mock pour éviter les appels réels."""
    mock_workspace = MagicMock()
    mock_workspace.runningApplications.return_value = []
    mock_workspace.frontmostApplication.return_value = None

    mock_appkit = MagicMock()
    mock_appkit.NSWorkspace.sharedWorkspace.return_value = mock_workspace
    mock_appkit.NSScreen = MagicMock()
    monkeypatch.setitem('sys.modules', 'AppKit', mock_appkit)
    return mock_workspace


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
    """Teste l'ouverture d'une application déjà en cours d'exécution."""
    # Simuler que l'application "Notes" est en cours d'exécution
    mock_appkit.runningApplications.return_value = [MockApp("Notes")]

    result = await agent._tool_open_application("Notes")

    # Vérifier que l'activation a été appelée et que le message est correct
    agent._activate_app.assert_awaited_once_with("Notes")
    assert "déjà ouverte" in result


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
    """Teste le fallback AppleScript lorsque l'API Cocoa lève une exception."""
    mock_appkit.runningApplications.side_effect = Exception("Cocoa crash")

    # On mocke la méthode de fallback pour éviter la vraie logique
    agent._fallback_open_application = AsyncMock(return_value="fallback OK")

    result = await agent._tool_open_application("Notes")

    agent._fallback_open_application.assert_awaited_once()
    assert result == "fallback OK"