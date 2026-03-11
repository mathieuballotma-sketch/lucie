import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.computer_control_agent import ComputerControlAgent


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
    """Teste l'ouverture d'une application déjà en cours d'exécution."""
    mock_appkit.runningApplications.return_value = [MockApp("Notes")]

    start = time.monotonic()
    result = await agent._tool_open_application("Notes")
    duration = time.monotonic() - start

    assert duration < 0.5, f"Trop lent : {duration:.3f}s"
    # Vérifie que l'activation a bien été demandée via AppleScript
    agent._run_applescript.assert_awaited_with('tell application "Notes" to activate', timeout=3.0)
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

    mock_subprocess.assert_called_once_with(
        "open", "-a", "Calculator",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE
    )
    assert "ouverte" in result


@pytest.mark.asyncio
async def test_open_application_fallback_on_exception(agent, mock_appkit):
    """Teste le fallback AppleScript lorsque l'API Cocoa lève une exception."""
    # Forcer une exception lors de l'appel à runningApplications
    mock_appkit.runningApplications.side_effect = Exception("Cocoa crash")

    # On mocke _fallback_open_application pour éviter la vraie logique
    agent._fallback_open_application = AsyncMock(return_value="fallback OK")

    result = await agent._tool_open_application("Notes")

    agent._fallback_open_application.assert_awaited_once()
    assert result == "fallback OK"


@pytest.mark.asyncio
async def test_fallback_open_application_running(agent, mock_appkit):
    """Teste le fallback lorsque l'application est déjà ouverte."""
    # Simuler que la vérification AppleScript retourne "true"
    agent._run_applescript = AsyncMock(return_value=(True, "true"))
    # On remet le mock de _run_applescript pour ce test (car on l'a peut-être redéfini)
    # Mais on veut aussi vérifier l'appel à _activate_app, donc on garde la vraie méthode _activate_app
    # On va plutôt vérifier que _run_applescript a été appelé avec le script d'activation

    start_time = time.time()
    result = await agent._fallback_open_application("Notes", start_time)

    # Vérifier que la vérification a été faite
    agent._run_applescript.assert_any_call(
        'tell application "System Events" to exists process "Notes"', timeout=3.0
    )
    # Vérifier que l'activation a été demandée
    agent._run_applescript.assert_any_call('tell application "Notes" to activate', timeout=3.0)
    assert "(fallback)" in result and "déjà ouverte" in result


@pytest.mark.asyncio
async def test_fallback_open_application_not_running(agent, mock_appkit):
    """Teste le fallback lorsque l'application n'est pas ouverte."""
    agent._run_applescript = AsyncMock(return_value=(True, "false"))

    with patch('asyncio.create_subprocess_exec') as mock_subprocess:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))
        mock_subprocess.return_value = mock_process

        start_time = time.time()
        result = await agent._fallback_open_application("Calculator", start_time)

    assert "ouverte" in result


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
    assert "disposées côte à côte" in result
    assert agent._run_applescript.call_count >= 2