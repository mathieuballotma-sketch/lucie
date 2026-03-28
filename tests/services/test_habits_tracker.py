"""
Tests unitaires pour HabitsTracker.
"""

import time
from pathlib import Path

import pytest

from app.services.habits_tracker import HabitsTracker, Suggestion


@pytest.fixture
def tracker(tmp_path: Path) -> HabitsTracker:
    """HabitsTracker avec BDD temporaire."""
    return HabitsTracker(db_path=str(tmp_path / "habits.db"))


class TestInit:
    """Teste l'initialisation."""

    def test_creates_db_file(self, tmp_path: Path) -> None:
        db = tmp_path / "h.db"
        HabitsTracker(db_path=str(db))
        assert db.exists()

    def test_default_db_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sans db_path, la BDD est creee dans ./data/habits.db."""
        monkeypatch.chdir(tmp_path)
        t = HabitsTracker()
        assert (tmp_path / "data" / "habits.db").exists()
        t.close()


class TestRecordAction:
    """Teste l'enregistrement des actions."""

    def test_record_creates_habit(self, tracker: HabitsTracker) -> None:
        tracker.record_action("open_email")
        habits = tracker.get_all_habits()
        assert len(habits) == 1
        assert habits[0]["action"] == "open_email"
        assert habits[0]["frequency"] == 1

    def test_record_increments_frequency(self, tracker: HabitsTracker) -> None:
        ts = time.time()
        # Meme action, meme heure, meme jour → frequence incremente
        tracker.record_action("read_news", timestamp=ts)
        tracker.record_action("read_news", timestamp=ts)
        habits = tracker.get_all_habits()
        assert habits[0]["frequency"] == 2

    def test_record_increases_confidence(self, tracker: HabitsTracker) -> None:
        ts = time.time()
        tracker.record_action("check_slack", timestamp=ts)
        conf_before = tracker.get_all_habits()[0]["confidence"]
        tracker.record_action("check_slack", timestamp=ts)
        conf_after = tracker.get_all_habits()[0]["confidence"]
        assert conf_after > conf_before

    def test_record_different_hours_creates_separate_habits(
        self, tracker: HabitsTracker
    ) -> None:
        # 9h00 → timestamp factice pour 9h
        from datetime import datetime, timedelta

        now = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        later = now + timedelta(hours=5)
        tracker.record_action("task", timestamp=now.timestamp())
        tracker.record_action("task", timestamp=later.timestamp())
        habits = tracker.get_all_habits()
        assert len(habits) == 2

    def test_record_with_context(self, tracker: HabitsTracker) -> None:
        tracker.record_action("web_search", context={"query": "python"})
        habits = tracker.get_all_habits()
        assert len(habits) == 1

    def test_confidence_capped_at_one(self, tracker: HabitsTracker) -> None:
        ts = time.time()
        for _ in range(50):
            tracker.record_action("spam", timestamp=ts)
        habits = tracker.get_all_habits()
        assert habits[0]["confidence"] <= 1.0


class TestGetSuggestions:
    """Teste la generation de suggestions."""

    def test_no_suggestions_below_min_frequency(
        self, tracker: HabitsTracker
    ) -> None:
        ts = time.time()
        # 2 occurrences < MIN_FREQUENCY_FOR_SUGGESTION (3)
        tracker.record_action("low_freq", timestamp=ts)
        tracker.record_action("low_freq", timestamp=ts)
        suggestions = tracker.get_suggestions(current_time=ts)
        assert suggestions == []

    def test_no_suggestions_below_confidence_threshold(
        self, tracker: HabitsTracker
    ) -> None:
        ts = time.time()
        # 3 fois mais confidence = 0.1 + 2*0.05 = 0.2 < 0.4
        for _ in range(3):
            tracker.record_action("low_conf", timestamp=ts)
        suggestions = tracker.get_suggestions(current_time=ts)
        assert suggestions == []

    def test_suggestion_returned_after_enough_records(
        self, tracker: HabitsTracker
    ) -> None:
        ts = time.time()
        # 10 occurrences : confidence = 0.1 + 9*0.05 = 0.55 >= 0.4
        for _ in range(10):
            tracker.record_action("daily_task", timestamp=ts)
        suggestions = tracker.get_suggestions(current_time=ts)
        assert len(suggestions) == 1
        assert isinstance(suggestions[0], Suggestion)
        assert suggestions[0].action == "daily_task"

    def test_suggestion_contains_message(self, tracker: HabitsTracker) -> None:
        ts = time.time()
        for _ in range(10):
            tracker.record_action("email", timestamp=ts)
        suggestions = tracker.get_suggestions(current_time=ts)
        assert len(suggestions) == 1
        assert "email" in suggestions[0].message

    def test_no_suggestions_wrong_day(self, tracker: HabitsTracker) -> None:
        from datetime import datetime, timedelta

        today = datetime.now()
        yesterday = today - timedelta(days=1)
        ts_yesterday = yesterday.timestamp()
        for _ in range(10):
            tracker.record_action("work", timestamp=ts_yesterday)
        # Suggestions pour aujourd'hui (jour different de hier)
        if today.weekday() != yesterday.weekday():
            suggestions = tracker.get_suggestions(current_time=today.timestamp())
            assert suggestions == []

    def test_suggestion_hour_window(self, tracker: HabitsTracker) -> None:
        from datetime import datetime

        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        ts = now.timestamp()
        for _ in range(10):
            tracker.record_action("morning_task", timestamp=ts)
        # +1h: toujours dans la fenetre HOUR_WINDOW=1
        from datetime import timedelta
        ts_plus1 = (now + timedelta(hours=1)).timestamp()
        suggestions = tracker.get_suggestions(current_time=ts_plus1)
        assert len(suggestions) >= 1


class TestGetAllHabits:
    """Teste la lecture de tous les patterns."""

    def test_empty_by_default(self, tracker: HabitsTracker) -> None:
        assert tracker.get_all_habits() == []

    def test_min_frequency_filter(self, tracker: HabitsTracker) -> None:
        ts = time.time()
        tracker.record_action("once", timestamp=ts)
        tracker.record_action("twice", timestamp=ts)
        tracker.record_action("twice", timestamp=ts)
        assert len(tracker.get_all_habits(min_frequency=2)) == 1
        assert len(tracker.get_all_habits(min_frequency=1)) == 2

    def test_day_name_in_result(self, tracker: HabitsTracker) -> None:
        tracker.record_action("check")
        habits = tracker.get_all_habits()
        assert "day" in habits[0]
        assert habits[0]["day"] in HabitsTracker.DAY_NAMES


class TestDecayOldHabits:
    """Teste la depreciation des vieilles habitudes."""

    def test_decay_old_reduces_confidence_and_removes(
        self, tracker: HabitsTracker
    ) -> None:
        # Injecter directement une habitude tres ancienne
        old_ts = time.time() - 200 * 86400
        tracker.record_action("ancient", timestamp=old_ts)
        # Forcer confidence a 0.1 en BDD (valeur initiale apres 1 enregistrement)
        deleted = tracker.decay_old_habits(max_age_days=90)
        # confidence 0.1 - 0.1 = 0.0 → supprime
        assert deleted == 1
        assert tracker.get_all_habits() == []

    def test_recent_habits_not_deleted(self, tracker: HabitsTracker) -> None:
        ts = time.time()
        tracker.record_action("recent", timestamp=ts)
        deleted = tracker.decay_old_habits(max_age_days=90)
        assert deleted == 0
        assert len(tracker.get_all_habits()) == 1


class TestClose:
    def test_close_does_not_raise(self, tracker: HabitsTracker) -> None:
        tracker.close()  # ne doit pas lever d'exception
