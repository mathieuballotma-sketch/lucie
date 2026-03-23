"""
Tests pour le suivi du temps gagne.
"""

import time

import pytest

from app.services.time_tracker import TaskTiming, TimeTracker


class TestTaskTiming:
    """Teste le dataclass TaskTiming."""

    def test_actual_time_running(self) -> None:
        timing = TaskTiming(task_type="test", agent_name="TestAgent")
        time.sleep(0.05)
        assert timing.actual_time >= 0.04

    def test_actual_time_completed(self) -> None:
        timing = TaskTiming(
            task_type="test",
            agent_name="TestAgent",
            start_time=100.0,
            end_time=105.0,
        )
        assert timing.actual_time == 5.0

    def test_time_saved_positive(self) -> None:
        timing = TaskTiming(
            task_type="test",
            agent_name="TestAgent",
            start_time=100.0,
            end_time=102.0,
            estimated_manual_time=120.0,
        )
        assert timing.time_saved == 118.0

    def test_time_saved_no_estimate(self) -> None:
        timing = TaskTiming(
            task_type="test",
            agent_name="TestAgent",
            start_time=100.0,
            end_time=102.0,
        )
        assert timing.time_saved == 0.0

    def test_time_saved_never_negative(self) -> None:
        timing = TaskTiming(
            task_type="test",
            agent_name="TestAgent",
            start_time=100.0,
            end_time=200.0,
            estimated_manual_time=10.0,
        )
        assert timing.time_saved == 0.0


class TestTimeTracker:
    """Teste le tracker persistant en SQLite."""

    def test_start_end_task(self, tmp_path: pytest.TempPathFactory) -> None:
        db = str(tmp_path / "test.db")  # type: ignore[operator]
        tracker = TimeTracker(db_path=db)
        timing = tracker.start_task("file_read", "FileAgent")
        assert timing.task_type == "file_read"
        assert timing.estimated_manual_time == 30.0

        time.sleep(0.05)
        saved = tracker.end_task(timing)
        assert saved > 0
        tracker.close()

    def test_daily_stats(self, tmp_path: pytest.TempPathFactory) -> None:
        db = str(tmp_path / "test.db")  # type: ignore[operator]
        tracker = TimeTracker(db_path=db)

        timing = tracker.start_task("file_read", "FileAgent")
        tracker.end_task(timing)

        stats = tracker.get_daily_stats()
        assert stats["task_count"] == 1
        assert stats["time_saved_seconds"] > 0
        tracker.close()

    def test_weekly_stats(self, tmp_path: pytest.TempPathFactory) -> None:
        db = str(tmp_path / "test.db")  # type: ignore[operator]
        tracker = TimeTracker(db_path=db)

        timing = tracker.start_task("web_search", "SearchAgent")
        tracker.end_task(timing)

        stats = tracker.get_weekly_stats()
        assert stats["task_count"] == 1
        tracker.close()

    def test_all_time_stats(self, tmp_path: pytest.TempPathFactory) -> None:
        db = str(tmp_path / "test.db")  # type: ignore[operator]
        tracker = TimeTracker(db_path=db)

        for task_type in ("file_read", "web_search"):
            timing = tracker.start_task(task_type, "Agent")
            tracker.end_task(timing)

        stats = tracker.get_all_time_stats()
        assert stats["task_count"] == 2
        tracker.close()

    def test_streak_empty(self, tmp_path: pytest.TempPathFactory) -> None:
        db = str(tmp_path / "test.db")  # type: ignore[operator]
        tracker = TimeTracker(db_path=db)
        assert tracker.get_streak() == 0
        tracker.close()

    def test_streak_today(self, tmp_path: pytest.TempPathFactory) -> None:
        db = str(tmp_path / "test.db")  # type: ignore[operator]
        tracker = TimeTracker(db_path=db)

        timing = tracker.start_task("file_read", "Agent")
        tracker.end_task(timing)

        assert tracker.get_streak() >= 1
        tracker.close()

    def test_format_duration(self) -> None:
        assert TimeTracker._format_duration(30) == "30s"
        assert TimeTracker._format_duration(90) == "2min"
        assert TimeTracker._format_duration(3600) == "1h"
        assert TimeTracker._format_duration(5400) == "1h30"

    def test_status_for_hud(self, tmp_path: pytest.TempPathFactory) -> None:
        db = str(tmp_path / "test.db")  # type: ignore[operator]
        tracker = TimeTracker(db_path=db)

        timing = tracker.start_task("planning", "PlannerAgent")
        tracker.end_task(timing)

        status = tracker.get_status_for_hud()
        assert "daily_saved" in status
        assert "total_saved" in status
        assert "streak" in status
        tracker.close()

    def test_unknown_task_type_no_estimate(self, tmp_path: pytest.TempPathFactory) -> None:
        db = str(tmp_path / "test.db")  # type: ignore[operator]
        tracker = TimeTracker(db_path=db)

        timing = tracker.start_task("unknown_type", "Agent")
        assert timing.estimated_manual_time is None
        saved = tracker.end_task(timing)
        assert saved == 0.0
        tracker.close()
