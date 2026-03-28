"""Tests unitaires pour ClipboardAgent."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.clipboard_agent import (
    ClipboardAgent,
    ContentType,
    detect_content_type,
    get_proposals,
)


# ---------------------------------------------------------------------------
# detect_content_type
# ---------------------------------------------------------------------------


def test_detect_url_http() -> None:
    assert detect_content_type("https://example.com/page") == ContentType.URL


def test_detect_url_http_plain() -> None:
    assert detect_content_type("http://example.org") == ContentType.URL


def test_detect_email() -> None:
    assert detect_content_type("user@example.com") == ContentType.EMAIL


def test_detect_email_with_plus() -> None:
    assert detect_content_type("user+tag@sub.example.com") == ContentType.EMAIL


def test_detect_phone_international() -> None:
    assert detect_content_type("+33 6 12 34 56 78") == ContentType.PHONE


def test_detect_code_python_def() -> None:
    assert detect_content_type("def foo():\n    return 42") == ContentType.CODE


def test_detect_code_python_class() -> None:
    assert detect_content_type("class MyClass:\n    pass") == ContentType.CODE


def test_detect_code_js_arrow() -> None:
    assert detect_content_type("const fn = () => { return 1; }") == ContentType.CODE


def test_detect_code_import() -> None:
    assert detect_content_type("import os\nimport sys") == ContentType.CODE


def test_detect_long_text() -> None:
    assert detect_content_type("a" * 60) == ContentType.LONG_TEXT


def test_detect_unknown_short_text() -> None:
    assert detect_content_type("bonjour") == ContentType.UNKNOWN


def test_detect_unknown_empty() -> None:
    assert detect_content_type("") == ContentType.UNKNOWN


def test_detect_unknown_whitespace_only() -> None:
    assert detect_content_type("   ") == ContentType.UNKNOWN


# ---------------------------------------------------------------------------
# get_proposals
# ---------------------------------------------------------------------------


def test_proposals_url_not_empty() -> None:
    proposals = get_proposals(ContentType.URL)
    assert len(proposals) >= 2


def test_proposals_url_content() -> None:
    proposals = get_proposals(ContentType.URL)
    assert any("Safari" in p or "Résumer" in p for p in proposals)


def test_proposals_email_not_empty() -> None:
    assert len(get_proposals(ContentType.EMAIL)) >= 1


def test_proposals_code_has_explain() -> None:
    proposals = get_proposals(ContentType.CODE)
    assert any("Expliquer" in p for p in proposals)


def test_proposals_long_text_has_summarize() -> None:
    proposals = get_proposals(ContentType.LONG_TEXT)
    assert any("Résumer" in p for p in proposals)


def test_proposals_unknown_empty() -> None:
    assert get_proposals(ContentType.UNKNOWN) == []


# ---------------------------------------------------------------------------
# ClipboardAgent construction
# ---------------------------------------------------------------------------


@pytest.fixture
def agent() -> ClipboardAgent:
    llm = MagicMock()
    bus = MagicMock()
    return ClipboardAgent(llm, bus, {})


def test_can_handle_returns_false(agent: ClipboardAgent) -> None:
    assert agent.can_handle("quelque chose") is False


def test_can_handle_empty_returns_false(agent: ClipboardAgent) -> None:
    assert agent.can_handle("") is False


def test_get_tools_empty(agent: ClipboardAgent) -> None:
    assert agent.get_tools() == []


def test_custom_poll_interval() -> None:
    llm, bus = MagicMock(), MagicMock()
    a = ClipboardAgent(llm, bus, {"clipboard_poll_interval": "2.5"})
    assert a._poll_interval == 2.5


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_start_without_pyobjc_does_not_run(agent: ClipboardAgent) -> None:
    """start() ne lance pas la tâche si PyObjC est absent."""
    with patch("app.agents.clipboard_agent._PYOBJC_AVAILABLE", False):
        agent.start()
    assert not agent._running
    assert agent._monitoring_task is None


def test_stop_without_start_is_safe(agent: ClipboardAgent) -> None:
    """stop() ne plante pas si l'agent n'a jamais été démarré."""
    agent.stop()
    assert not agent._running


def test_start_is_idempotent(agent: ClipboardAgent) -> None:
    """Appeler start() deux fois ne crée pas deux tâches."""
    with patch("app.agents.clipboard_agent._PYOBJC_AVAILABLE", True):
        with patch("asyncio.create_task") as mock_create:
            agent._running = True  # simuler déjà démarré
            agent.start()
            mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# _check_clipboard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_clipboard_no_change_no_publish(agent: ClipboardAgent) -> None:
    """Pas de publication si changeCount est identique au précédent."""
    agent._last_change_count = 5
    publish_mock = AsyncMock()
    event_bus_mock = MagicMock()
    event_bus_mock.publish = publish_mock
    agent.event_bus = event_bus_mock
    agent.token = "test-token"

    with patch.object(agent, "_read_pasteboard", return_value=(5, "https://example.com")):
        await agent._check_clipboard()

    publish_mock.assert_not_called()


@pytest.mark.asyncio
async def test_check_clipboard_url_publishes(agent: ClipboardAgent) -> None:
    """Publie une proposition quand une URL est copiée."""
    agent._last_change_count = 0
    publish_mock = AsyncMock()
    event_bus_mock = MagicMock()
    event_bus_mock.publish = publish_mock
    agent.event_bus = event_bus_mock
    agent.token = "test-token"

    with patch.object(agent, "_read_pasteboard", return_value=(1, "https://example.com")):
        await agent._check_clipboard()

    publish_mock.assert_awaited_once()
    call_kwargs = publish_mock.call_args.kwargs
    assert call_kwargs["channel"] == "clipboard.proposal"
    assert call_kwargs["data"]["content_type"] == ContentType.URL.value
    assert "proposals" in call_kwargs["data"]


@pytest.mark.asyncio
async def test_check_clipboard_unknown_no_publish(agent: ClipboardAgent) -> None:
    """Pas de publication si le contenu est trop court et sans pattern."""
    agent._last_change_count = 0
    publish_mock = AsyncMock()
    event_bus_mock = MagicMock()
    event_bus_mock.publish = publish_mock
    agent.event_bus = event_bus_mock
    agent.token = "test-token"

    with patch.object(agent, "_read_pasteboard", return_value=(1, "ok")):
        await agent._check_clipboard()

    publish_mock.assert_not_called()


@pytest.mark.asyncio
async def test_check_clipboard_none_pasteboard_no_crash(agent: ClipboardAgent) -> None:
    """Retour None du pasteboard ne plante pas."""
    agent._last_change_count = 0
    with patch.object(agent, "_read_pasteboard", return_value=None):
        await agent._check_clipboard()  # ne doit pas lever d'exception


@pytest.mark.asyncio
async def test_no_publish_without_event_bus(agent: ClipboardAgent) -> None:
    """Pas de crash si event_bus est None."""
    agent._last_change_count = 0
    agent.event_bus = None
    agent.token = None

    with patch.object(agent, "_read_pasteboard", return_value=(1, "https://example.com")):
        await agent._check_clipboard()


@pytest.mark.asyncio
async def test_no_publish_without_token(agent: ClipboardAgent) -> None:
    """Pas de publication si le token est absent."""
    agent._last_change_count = 0
    agent.event_bus = MagicMock()
    agent.event_bus.publish = AsyncMock()
    agent.token = None

    with patch.object(agent, "_read_pasteboard", return_value=(1, "https://example.com")):
        await agent._check_clipboard()

    agent.event_bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# _read_pasteboard (sans PyObjC)
# ---------------------------------------------------------------------------


def test_read_pasteboard_without_pyobjc_returns_none(agent: ClipboardAgent) -> None:
    """_read_pasteboard retourne None si PyObjC est absent."""
    with patch("app.agents.clipboard_agent._NSPasteboard", None):
        with patch("app.agents.clipboard_agent._NSStringPboardType", None):
            result = agent._read_pasteboard()
    assert result is None
