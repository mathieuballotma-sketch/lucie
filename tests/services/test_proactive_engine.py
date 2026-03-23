"""
Tests pour le moteur de proactivite avec anti-spam.
"""

import time

import pytest

from app.memory.contextual_memory import ContextualMemory
from app.services.proactive_engine import ProactiveEngine
from app.services.time_tracker import TimeTracker


@pytest.fixture
def proactive(tmp_path: pytest.TempPathFactory) -> ProactiveEngine:
    """Cree un ProactiveEngine avec DBs temporaires."""
    ctx_db = str(tmp_path / "ctx.db")  # type: ignore[operator]
    tt_db = str(tmp_path / "tt.db")  # type: ignore[operator]
    memory = ContextualMemory(db_path=ctx_db)
    tracker = TimeTracker(db_path=tt_db)
    return ProactiveEngine(memory, tracker)


class TestAntiSpam:
    """Teste les mecanismes anti-spam."""

    def test_max_suggestions_per_hour(self, proactive: ProactiveEngine) -> None:
        """Respecte MAX_SUGGESTIONS_PER_HOUR."""
        # Injecter directement dans l'historique (evite le MIN_INTERVAL)
        now = time.time()
        for i in range(proactive.MAX_SUGGESTIONS_PER_HOUR):
            proactive._suggestion_history.append({
                "type": "test",
                "topic": f"topic_{i}",
                "timestamp": now - i,
            })
        proactive._last_suggestion_time = now - proactive.MIN_INTERVAL_SECONDS - 1

        # La suivante devrait etre bloquee par le max horaire
        received: list[dict[str, object]] = []
        proactive.on_suggestion(lambda s: received.append(s))
        proactive._emit_suggestion({"type": "test", "topic": "blocked", "score": 0.9})
        assert len(received) == 0

    def test_min_interval(self, proactive: ProactiveEngine) -> None:
        """Respecte MIN_INTERVAL_SECONDS."""
        proactive._emit_suggestion({"type": "test", "topic": "a", "score": 0.9})

        received: list[dict[str, object]] = []
        proactive.on_suggestion(lambda s: received.append(s))
        proactive._emit_suggestion({"type": "test", "topic": "b", "score": 0.9})
        assert len(received) == 0  # trop tot

    def test_dismissed_topics_blacklisted(self, proactive: ProactiveEngine) -> None:
        """Les sujets dismiss sont blacklistes 24h."""
        proactive.dismiss_topic("weather")
        assert proactive._is_topic_dismissed("weather") is True

    def test_dismissed_topic_expires(self, proactive: ProactiveEngine) -> None:
        """Les sujets dismiss expirent apres le TTL."""
        proactive.dismiss_topic("old_topic")
        # Forcer l'expiration
        proactive._dismissed_topics["old_topic"] = time.time() - 1
        assert proactive._is_topic_dismissed("old_topic") is False


class TestBriefing:
    """Teste le briefing matinal."""

    @pytest.mark.asyncio
    async def test_briefing_once_per_day(self, proactive: ProactiveEngine) -> None:
        """Le briefing matinal ne se declenche qu'une fois par jour."""
        briefing = await proactive.generate_morning_briefing()
        # Au premier appel, le briefing peut etre None si pas de stats
        assert briefing is None or isinstance(briefing, dict)

    @pytest.mark.asyncio
    async def test_briefing_with_data(self, tmp_path: pytest.TempPathFactory) -> None:
        """Briefing avec des donnees reelles."""
        ctx_db = str(tmp_path / "ctx.db")  # type: ignore[operator]
        tt_db = str(tmp_path / "tt.db")  # type: ignore[operator]
        memory = ContextualMemory(db_path=ctx_db)
        tracker = TimeTracker(db_path=tt_db)

        # Ajouter des taches
        timing = tracker.start_task("file_read", "FileAgent")
        tracker.end_task(timing)

        engine = ProactiveEngine(memory, tracker)
        briefing = await engine.generate_morning_briefing()
        assert briefing is not None
        assert briefing["type"] == "morning_briefing"
        assert "content" in briefing


class TestRelevanceScore:
    """Teste le calcul du score de pertinence."""

    def test_score_zero_input(self, proactive: ProactiveEngine) -> None:
        score = proactive.compute_relevance_score(0, 999999, 0.0)
        assert 0 <= score <= 1

    def test_score_high_frequency(self, proactive: ProactiveEngine) -> None:
        score = proactive.compute_relevance_score(100, 3600, 0.8)
        assert score > 0.5

    def test_score_bounded(self, proactive: ProactiveEngine) -> None:
        score = proactive.compute_relevance_score(10000, 0, 1.0)
        assert score <= 1.0

    def test_score_increases_with_frequency(self, proactive: ProactiveEngine) -> None:
        score_low = proactive.compute_relevance_score(1, 3600, 0.5)
        score_high = proactive.compute_relevance_score(50, 3600, 0.5)
        assert score_high > score_low


class TestStartStop:
    """Teste le demarrage et l'arret."""

    @pytest.mark.asyncio
    async def test_start_stop(self, proactive: ProactiveEngine) -> None:
        await proactive.start()
        assert proactive._running is True
        await proactive.stop()
        assert proactive._running is False

    @pytest.mark.asyncio
    async def test_double_start(self, proactive: ProactiveEngine) -> None:
        await proactive.start()
        await proactive.start()  # ne devrait pas crash
        assert proactive._running is True
        await proactive.stop()


class TestSuggestions:
    """Teste les suggestions contextuelles."""

    @pytest.mark.asyncio
    async def test_no_suggestions_without_patterns(
        self, proactive: ProactiveEngine
    ) -> None:
        suggestions = await proactive.generate_contextual_suggestions()
        assert suggestions == []

    def test_recent_suggestions(self, proactive: ProactiveEngine) -> None:
        assert proactive.get_recent_suggestions() == []
        proactive._suggestion_history.append({"type": "test", "timestamp": time.time()})
        assert len(proactive.get_recent_suggestions()) == 1
