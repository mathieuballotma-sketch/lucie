import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.computer_control_agent import ComputerControlAgent
from app.utils.errors import ToolExecutionError


class MockApp:
    """Mock d'une application NSRunningApplication."""
    def __init__(self, name):
        self._name = name
        self._pid = 1234

    def localizedName(self):
        return self._name

    def processIdentifier(self):
        return self._pid


@pytest.fixture
def mock_appkit():
    """Remplace le module AppKit dans l'agent par un mock."""
    patcher = patch('app.agents.computer_control_agent.AppKit')
    mock_kit = patcher.start()
    mock_workspace = MagicMock()
    mock_kit.NSWorkspace.sharedWorkspace.return_value = mock_workspace
    mock_kit.NSScreen = MagicMock()
    yield mock_workspace
    patcher.stop()


@pytest.fixture
def agent(mock_appkit):
    """Crée une instance de l'agent avec des services mockés."""
    llm_mock = MagicMock()
    bus_mock = MagicMock()
    config = {}
    agent = ComputerControlAgent(llm_mock, bus_mock, config)
    # On remplace _run_applescript par un mock pour éviter les vrais appels
    agent._run_applescript = AsyncMock(return_value=(True, ""))
    # On NE mocke PAS _activate_app pour pouvoir tester sa vraie implémentation
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

    mock_subprocess.assert_called_once_with(
        "open", "-a", "Calculator",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE
    )
    assert "ouverte" in result


@pytest.mark.asyncio
async def test_open_application_fallback_on_exception(agent, mock_appkit):
    """Teste que _tool_open_application lève ToolExecutionError si le subprocess échoue."""
    with patch('asyncio.create_subprocess_exec') as mock_subprocess:
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"Application introuvable"))
        mock_subprocess.return_value = mock_process

        with pytest.raises(ToolExecutionError):
            await agent._tool_open_application("AppInexistante")


@pytest.mark.asyncio
async def test_fallback_open_application_running(agent, mock_appkit):
    """Teste _wait_for_app_active quand l'application est active."""
    # Simuler que Notes est l'application en premier plan
    mock_app = MockApp("Notes")
    mock_appkit.frontmostApplication.return_value = mock_app

    result = await agent._wait_for_app_active("Notes", timeout=0.5)

    assert result is True


@pytest.mark.asyncio
async def test_fallback_open_application_not_running(agent, mock_appkit):
    """Teste _wait_for_app_active quand l'application n'est pas active (timeout)."""
    # Simuler qu'aucune app n'est au premier plan
    mock_appkit.frontmostApplication.return_value = None

    result = await agent._wait_for_app_active("Calculator", timeout=0.15)

    assert result is False


@pytest.mark.asyncio
async def test_activate_app(agent, mock_appkit):
    """Teste l'activation via AppleScript."""
    await agent._activate_app("Notes")
    agent._run_applescript.assert_called_once_with('tell application "Notes" to activate', timeout=3.0)


@pytest.mark.asyncio
async def test_type_text_with_applescript(agent, mock_appkit):
    """Teste la saisie de texte via AppleScript."""
    agent._run_applescript = AsyncMock(return_value=(True, ""))
    success = await agent._type_text_with_applescript("hello", interval=0.05, use_paste=False)
    assert success is True
    agent._run_applescript.assert_called()


@pytest.mark.asyncio
async def test_mail_compose(agent, mock_appkit):
    """Teste la composition d'email."""
    agent._run_applescript = AsyncMock(return_value=(True, ""))
    result = await agent._tool_mail_compose(to="test@example.com", subject="Sujet", body="Corps", send=False)
    assert "préparé" in result


@pytest.mark.asyncio
async def test_safari_open_url(agent, mock_appkit):
    """Teste l'ouverture d'URL dans Safari."""
    agent._activate_app = AsyncMock()
    agent._wait_for_app_active = AsyncMock(return_value=True)
    agent._run_applescript = AsyncMock(return_value=(True, ""))
    result = await agent._tool_safari_open_url("https://example.com", new_tab=False)
    assert "ouverte" in result


@pytest.mark.asyncio
async def test_arrange_side_by_side(agent, mock_appkit):
    """Teste la disposition côte à côte."""
    agent._activate_app = AsyncMock()
    agent._wait_for_app_active = AsyncMock(return_value=True)
    agent._run_applescript = AsyncMock(return_value=(True, ""))
    agent._get_screen_size = AsyncMock(return_value=(1920, 1080))

    result = await agent._arrange_side_by_side(["Notes", "Safari"])
    assert "côte à côte" in result
    assert agent._run_applescript.call_count >= 2
