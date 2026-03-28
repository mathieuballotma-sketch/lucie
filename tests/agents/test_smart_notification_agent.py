"""Tests unitaires pour SmartNotificationAgent."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agents.smart_notification_agent import (
    Notification,
    Priority,
    SmartNotificationAgent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agent() -> SmartNotificationAgent:
    llm = MagicMock()
    bus = MagicMock()
    return SmartNotificationAgent(llm, bus, {})


@pytest.fixture
def agent_with_memory() -> SmartNotificationAgent:
    llm = MagicMock()
    bus = MagicMock()
    memory = MagicMock()
    memory.add_episode = AsyncMock()
    return SmartNotificationAgent(llm, bus, {}, memory_service=memory)


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


def test_can_handle_focus_activate(agent: SmartNotificationAgent) -> None:
    assert agent.can_handle("active le mode focus") is True


def test_can_handle_focus_disable(agent: SmartNotificationAgent) -> None:
    assert agent.can_handle("désactiver focus mode") is True


def test_can_handle_focus_mode(agent: SmartNotificationAgent) -> None:
    assert agent.can_handle("mode focus") is True


def test_can_handle_missed(agent: SmartNotificationAgent) -> None:
    assert agent.can_handle("qu'ai-je manqué") is True


def test_can_handle_notifications_recentes(agent: SmartNotificationAgent) -> None:
    assert agent.can_handle("dernières notifications") is True


def test_can_handle_resume(agent: SmartNotificationAgent) -> None:
    assert agent.can_handle("résume les notifications") is True


def test_cannot_handle_unrelated(agent: SmartNotificationAgent) -> None:
    assert agent.can_handle("quel temps fait-il") is False


def test_cannot_handle_empty(agent: SmartNotificationAgent) -> None:
    assert agent.can_handle("") is False


# ---------------------------------------------------------------------------
# get_tools
# ---------------------------------------------------------------------------


def test_get_tools_has_toggle_focus(agent: SmartNotificationAgent) -> None:
    tools = agent.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "toggle_focus"


# ---------------------------------------------------------------------------
# _classify_priority
# ---------------------------------------------------------------------------


def test_classify_critical_alerte(agent: SmartNotificationAgent) -> None:
    p = agent._classify_priority("Sécurité", "Intrusion détectée", "alerte")
    assert p == Priority.CRITICAL


def test_classify_critical_2fa(agent: SmartNotificationAgent) -> None:
    p = agent._classify_priority("App", "Code de vérification", "")
    assert p == Priority.CRITICAL


def test_classify_important_meeting(agent: SmartNotificationAgent) -> None:
    p = agent._classify_priority("Calendrier", "Réunion dans 5 minutes", "")
    assert p == Priority.IMPORTANT


def test_classify_important_appel_manque(agent: SmartNotificationAgent) -> None:
    p = agent._classify_priority("Téléphone", "Appel manqué", "")
    assert p == Priority.IMPORTANT


def test_classify_informative_update(agent: SmartNotificationAgent) -> None:
    p = agent._classify_priority("App Store", "Mise à jour disponible", "info")
    assert p == Priority.INFORMATIVE


def test_classify_noise_social(agent: SmartNotificationAgent) -> None:
    p = agent._classify_priority("Twitter", "Quelqu'un a liké votre post", "")
    assert p == Priority.NOISE


def test_classify_noise_empty(agent: SmartNotificationAgent) -> None:
    p = agent._classify_priority("App", "", "")
    assert p == Priority.NOISE


# ---------------------------------------------------------------------------
# ingest — comportement standard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_noise_returns_none(agent: SmartNotificationAgent) -> None:
    agent.event_bus = MagicMock()
    agent.event_bus.publish = AsyncMock()
    agent.token = "tok"

    result = await agent.ingest("Twitter", "Nouveau like", "quelqu'un a liké")
    assert result is None
    agent.event_bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_critical_returns_notification(agent: SmartNotificationAgent) -> None:
    agent.event_bus = MagicMock()
    agent.event_bus.publish = AsyncMock()
    agent.token = "tok"

    result = await agent.ingest("Sécurité", "alerte intrusion", "erreur critique détectée")
    assert result is not None
    assert result.priority == Priority.CRITICAL
    assert result.seen is True
    agent.event_bus.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_important_published(agent: SmartNotificationAgent) -> None:
    agent.event_bus = MagicMock()
    agent.event_bus.publish = AsyncMock()
    agent.token = "tok"

    result = await agent.ingest("Calendrier", "réunion dans 5 min", "meeting")
    assert result is not None
    assert result.priority == Priority.IMPORTANT
    agent.event_bus.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_appends_to_queue(agent: SmartNotificationAgent) -> None:
    agent.event_bus = MagicMock()
    agent.event_bus.publish = AsyncMock()
    agent.token = "tok"

    await agent.ingest("App", "test", "corps")
    assert len(agent._notification_queue) == 1


# ---------------------------------------------------------------------------
# Mode focus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_focus_blocks_non_critical(agent: SmartNotificationAgent) -> None:
    await agent._tool_toggle_focus(enabled=True)
    agent.event_bus = MagicMock()
    agent.event_bus.publish = AsyncMock()
    agent.token = "tok"

    result = await agent.ingest("Calendrier", "réunion", "meeting dans 5 min")
    assert result is None
    assert len(agent._missed_while_focus) == 1
    agent.event_bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_focus_lets_critical_through(agent: SmartNotificationAgent) -> None:
    await agent._tool_toggle_focus(enabled=True)
    agent.event_bus = MagicMock()
    agent.event_bus.publish = AsyncMock()
    agent.token = "tok"

    result = await agent.ingest("Sécurité", "alerte", "erreur critique")
    assert result is not None
    assert result.priority == Priority.CRITICAL
    assert len(agent._missed_while_focus) == 0


@pytest.mark.asyncio
async def test_focus_clears_missed_on_activate(agent: SmartNotificationAgent) -> None:
    agent._missed_while_focus = [Notification("App", "T", "B")]
    await agent._tool_toggle_focus(enabled=True)
    assert len(agent._missed_while_focus) == 0


# ---------------------------------------------------------------------------
# _summarize_missed
# ---------------------------------------------------------------------------


def test_summarize_empty_returns_message(agent: SmartNotificationAgent) -> None:
    result = agent._summarize_missed()
    assert "Aucune" in result


def test_summarize_shows_count(agent: SmartNotificationAgent) -> None:
    agent._missed_while_focus = [
        Notification("App", "Titre1", "corps", Priority.IMPORTANT),
        Notification("App2", "Titre2", "corps2", Priority.NOISE),
    ]
    result = agent._summarize_missed()
    assert "2" in result


def test_summarize_clears_queue(agent: SmartNotificationAgent) -> None:
    agent._missed_while_focus = [
        Notification("App", "Titre", "corps", Priority.IMPORTANT),
    ]
    agent._summarize_missed()
    assert len(agent._missed_while_focus) == 0


def test_summarize_shows_app_name(agent: SmartNotificationAgent) -> None:
    agent._missed_while_focus = [
        Notification("MonApp", "Mon Titre", "corps", Priority.CRITICAL),
    ]
    result = agent._summarize_missed()
    assert "MonApp" in result


# ---------------------------------------------------------------------------
# _list_recent
# ---------------------------------------------------------------------------


def test_list_recent_empty(agent: SmartNotificationAgent) -> None:
    result = agent._list_recent()
    assert "Aucune" in result


def test_list_recent_shows_seen_notifications(agent: SmartNotificationAgent) -> None:
    notif = Notification("MonApp", "Mon Titre", "Corps", Priority.IMPORTANT, seen=True)
    agent._notification_queue.append(notif)
    result = agent._list_recent()
    assert "MonApp" in result
    assert "Mon Titre" in result


def test_list_recent_hides_unseen(agent: SmartNotificationAgent) -> None:
    notif = Notification("App", "Titre", "Corps", Priority.NOISE, seen=False)
    agent._notification_queue.append(notif)
    result = agent._list_recent()
    assert "Aucune" in result


# ---------------------------------------------------------------------------
# _tool_toggle_focus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toggle_focus_on(agent: SmartNotificationAgent) -> None:
    result = await agent._tool_toggle_focus(enabled=True)
    assert agent._focus_mode is True
    assert "activé" in result.lower()


@pytest.mark.asyncio
async def test_toggle_focus_off(agent: SmartNotificationAgent) -> None:
    agent._focus_mode = True
    result = await agent._tool_toggle_focus(enabled=False)
    assert agent._focus_mode is False
    assert "désactivé" in result.lower()


# ---------------------------------------------------------------------------
# handle (routing)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_focus_activate(agent: SmartNotificationAgent) -> None:
    result = await agent.handle("activer le mode focus")
    assert agent._focus_mode is True
    assert "activé" in result.lower()


@pytest.mark.asyncio
async def test_handle_focus_disable(agent: SmartNotificationAgent) -> None:
    agent._focus_mode = True
    result = await agent.handle("désactiver mode focus")
    assert agent._focus_mode is False


@pytest.mark.asyncio
async def test_handle_missed_returns_summary(agent: SmartNotificationAgent) -> None:
    result = await agent.handle("qu'ai-je manqué")
    assert "Aucune" in result or "manquées" in result


@pytest.mark.asyncio
async def test_handle_recent(agent: SmartNotificationAgent) -> None:
    result = await agent.handle("dernières notifications")
    assert "Aucune" in result or "récentes" in result.lower()


# ---------------------------------------------------------------------------
# learn_preference
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_learn_preference_calls_memory(
    agent_with_memory: SmartNotificationAgent,
) -> None:
    await agent_with_memory.learn_preference("Twitter", "ignorer")
    agent_with_memory.memory_service.add_episode.assert_awaited_once()


@pytest.mark.asyncio
async def test_learn_preference_without_memory_no_crash(
    agent: SmartNotificationAgent,
) -> None:
    """learn_preference ne plante pas si memory_service est absent."""
    await agent.learn_preference("Twitter", "ignorer")


@pytest.mark.asyncio
async def test_learn_preference_memory_error_no_crash(
    agent_with_memory: SmartNotificationAgent,
) -> None:
    """Une exception dans MemoryService est gérée proprement."""
    agent_with_memory.memory_service.add_episode = AsyncMock(side_effect=RuntimeError("db error"))
    await agent_with_memory.learn_preference("App", "ignorer")  # ne doit pas lever
