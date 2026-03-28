"""
Tests unitaires pour InsightsEngine.
"""

import time
from pathlib import Path
from typing import Any, Dict

import pytest

from app.services.insights_engine import (
    Insight,
    InsightPriority,
    InsightsEngine,
    InsightType,
)


@pytest.fixture
def engine(tmp_path: Path) -> InsightsEngine:
    """InsightsEngine avec BDD temporaire."""
    return InsightsEngine(db_path=str(tmp_path / "insights.db"))


class TestInit:
    def test_creates_db_file(self, tmp_path: Path) -> None:
        db = tmp_path / "ins.db"
        InsightsEngine(db_path=str(db))
        assert db.exists()

    def test_default_db_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        e = InsightsEngine()
        assert (tmp_path / "data" / "insights.db").exists()
        e.close()


class TestStoreAndRetrieve:
    def _make_insight(self, title: str = "Test insight") -> Insight:
        return Insight(
            insight_type=InsightType.ORGANIZATION,
            title=title,
            content="Contenu test",
            score=0.7,
            priority=InsightPriority.MEDIUM,
        )

    def test_store_returns_id(self, engine: InsightsEngine) -> None:
        insight = self._make_insight()
        stored_id = engine.store_insight(insight)
        assert stored_id is not None
        assert stored_id > 0

    def test_store_dedup_returns_none(self, engine: InsightsEngine) -> None:
        insight = self._make_insight()
        engine.store_insight(insight)
        second_id = engine.store_insight(self._make_insight())
        assert second_id is None

    def test_store_different_title_not_dedup(self, engine: InsightsEngine) -> None:
        engine.store_insight(self._make_insight("A"))
        second_id = engine.store_insight(self._make_insight("B"))
        assert second_id is not None

    def test_get_pending_returns_stored(self, engine: InsightsEngine) -> None:
        engine.store_insight(self._make_insight())
        pending = engine.get_pending_insights()
        assert len(pending) == 1
        assert pending[0].title == "Test insight"

    def test_get_pending_respects_min_score(self, engine: InsightsEngine) -> None:
        low = Insight(
            insight_type=InsightType.ORGANIZATION,
            title="Low score",
            content="...",
            score=0.3,
            priority=InsightPriority.LOW,
        )
        engine.store_insight(low)
        assert engine.get_pending_insights(min_score=0.5) == []

    def test_get_pending_respects_limit(self, engine: InsightsEngine) -> None:
        for i in range(5):
            engine.store_insight(
                Insight(
                    insight_type=InsightType.ORGANIZATION,
                    title=f"Insight {i}",
                    content="...",
                    score=0.8,
                    priority=InsightPriority.LOW,
                )
            )
        assert len(engine.get_pending_insights(limit=3)) == 3

    def test_mark_seen_hides_insight(self, engine: InsightsEngine) -> None:
        stored_id = engine.store_insight(self._make_insight())
        assert stored_id is not None
        engine.mark_seen(stored_id)
        assert engine.get_pending_insights() == []

    def test_expired_insight_not_returned(self, engine: InsightsEngine) -> None:
        """Un insight expire ne doit pas apparaitre dans get_pending_insights."""
        insight = self._make_insight("Expired")
        stored_id = engine.store_insight(insight)
        assert stored_id is not None
        # Forcer l'expiration directement en BDD
        engine._conn.execute(
            "UPDATE insights SET expires_at = ? WHERE id = ?",
            (time.time() - 1, stored_id),
        )
        engine._conn.commit()
        assert engine.get_pending_insights() == []


class TestAnalyzeFiles:
    def test_no_insights_for_normal_files(
        self, engine: InsightsEngine, tmp_path: Path
    ) -> None:
        f = tmp_path / "report.pdf"
        f.write_text("content")
        insights = engine.analyze_files([str(f)])
        assert insights == []

    def test_detects_draft_file(
        self, engine: InsightsEngine, tmp_path: Path
    ) -> None:
        f = tmp_path / "draft_report.docx"
        f.write_text("wip")
        insights = engine.analyze_files([str(f)])
        assert len(insights) == 1
        assert insights[0].insight_type == InsightType.FILES_UNFINISHED

    def test_detects_wip_file(
        self, engine: InsightsEngine, tmp_path: Path
    ) -> None:
        f = tmp_path / "wip_feature.py"
        f.write_text("# todo")
        insights = engine.analyze_files([str(f)])
        assert len(insights) == 1

    def test_ignores_old_files(
        self, engine: InsightsEngine, tmp_path: Path
    ) -> None:
        f = tmp_path / "draft_old.txt"
        f.write_text("old")
        # Simuler un fichier vieux de 10 jours
        import os
        old_ts = time.time() - 10 * 86400
        os.utime(str(f), (old_ts, old_ts))
        insights = engine.analyze_files([str(f)])
        assert insights == []

    def test_ignores_nonexistent_path(self, engine: InsightsEngine) -> None:
        insights = engine.analyze_files(["/does/not/exist/draft.txt"])
        assert insights == []

    def test_score_bounded(
        self, engine: InsightsEngine, tmp_path: Path
    ) -> None:
        f = tmp_path / "tmp_test.txt"
        f.write_text("x")
        insights = engine.analyze_files([str(f)])
        if insights:
            assert 0.0 <= insights[0].score <= 1.0


class TestAnalyzeReminders:
    def test_no_insight_for_future_reminder(
        self, engine: InsightsEngine
    ) -> None:
        reminders = [{"due_at": time.time() + 3600, "title": "Future"}]
        assert engine.analyze_reminders(reminders) == []

    def test_overdue_reminder_generates_insight(
        self, engine: InsightsEngine
    ) -> None:
        reminders = [{"due_at": time.time() - 7200, "title": "Late meeting"}]
        insights = engine.analyze_reminders(reminders)
        assert len(insights) == 1
        assert insights[0].insight_type == InsightType.REMINDERS_OVERDUE
        assert "Late meeting" in insights[0].title

    def test_overdue_24h_is_high_priority(self, engine: InsightsEngine) -> None:
        reminders = [{"due_at": time.time() - 48 * 3600, "title": "Very late"}]
        insights = engine.analyze_reminders(reminders)
        assert insights[0].priority == InsightPriority.HIGH

    def test_overdue_1h_is_medium_priority(self, engine: InsightsEngine) -> None:
        reminders = [{"due_at": time.time() - 3600, "title": "Bit late"}]
        insights = engine.analyze_reminders(reminders)
        assert insights[0].priority == InsightPriority.MEDIUM

    def test_reminder_without_due_at_ignored(
        self, engine: InsightsEngine
    ) -> None:
        reminders = [{"title": "No due date"}]
        assert engine.analyze_reminders(reminders) == []

    def test_score_bounded(self, engine: InsightsEngine) -> None:
        reminders = [{"due_at": time.time() - 999999, "title": "Ancient"}]
        insights = engine.analyze_reminders(reminders)
        assert 0.0 <= insights[0].score <= 1.0


class TestAnalyzePatterns:
    def test_no_insight_below_threshold(self, engine: InsightsEngine) -> None:
        current = {"emails": 5}
        baseline = {"emails": 4}
        assert engine.analyze_patterns(current, baseline) == []

    def test_anomaly_detected(self, engine: InsightsEngine) -> None:
        current = {"emails": 20}
        baseline = {"emails": 5}
        insights = engine.analyze_patterns(current, baseline)
        assert len(insights) == 1
        assert insights[0].insight_type == InsightType.UNUSUAL_PATTERN

    def test_zero_baseline_skipped(self, engine: InsightsEngine) -> None:
        current = {"metric": 10}
        baseline: Dict[str, int] = {}
        assert engine.analyze_patterns(current, baseline) == []

    def test_score_bounded(self, engine: InsightsEngine) -> None:
        current = {"x": 1000}
        baseline = {"x": 1}
        insights = engine.analyze_patterns(current, baseline)
        assert 0.0 <= insights[0].score <= 1.0


class TestAnalyzeOrganization:
    def test_no_insight_for_small_folder(self, engine: InsightsEngine) -> None:
        stats = [{"path": "/home/user/docs", "file_count": 50}]
        assert engine.analyze_organization(stats) == []

    def test_insight_for_crowded_folder(self, engine: InsightsEngine) -> None:
        stats = [{"path": "/home/user/downloads", "file_count": 150}]
        insights = engine.analyze_organization(stats)
        assert len(insights) == 1
        assert insights[0].insight_type == InsightType.ORGANIZATION
        assert insights[0].priority == InsightPriority.LOW

    def test_score_bounded(self, engine: InsightsEngine) -> None:
        stats = [{"path": "/x", "file_count": 9999}]
        insights = engine.analyze_organization(stats)
        assert 0.0 <= insights[0].score <= 1.0


class TestRunFullAnalysis:
    def test_run_full_stores_insights(
        self, engine: InsightsEngine, tmp_path: Path
    ) -> None:
        f = tmp_path / "draft_note.txt"
        f.write_text("draft")
        results = engine.run_full_analysis(files=[str(f)])
        assert len(results) >= 1
        pending = engine.get_pending_insights()
        assert len(pending) >= 1

    def test_run_full_dedup_on_second_call(
        self, engine: InsightsEngine, tmp_path: Path
    ) -> None:
        f = tmp_path / "draft_test.txt"
        f.write_text("x")
        engine.run_full_analysis(files=[str(f)])
        second = engine.run_full_analysis(files=[str(f)])
        # Dedup: le second appel ne doit pas stocker de doublon
        for ins in second:
            assert ins.insight_id is None

    def test_returns_all_types(
        self, engine: InsightsEngine, tmp_path: Path
    ) -> None:
        f = tmp_path / "wip_stuff.txt"
        f.write_text("x")
        reminders = [{"due_at": time.time() - 3600, "title": "Late"}]
        current = {"mails": 30}
        baseline = {"mails": 10}
        folder = [{"path": "/downloads", "file_count": 200}]
        results = engine.run_full_analysis(
            files=[str(f)],
            reminders=reminders,
            current_stats=current,
            baseline_stats=baseline,
            folder_stats=folder,
        )
        types = {r.insight_type for r in results}
        assert InsightType.FILES_UNFINISHED in types
        assert InsightType.REMINDERS_OVERDUE in types
        assert InsightType.UNUSUAL_PATTERN in types
        assert InsightType.ORGANIZATION in types


class TestGetSummaryForBriefing:
    def test_empty_when_no_insights(self, engine: InsightsEngine) -> None:
        assert engine.get_summary_for_briefing() == ""

    def test_returns_formatted_string(self, engine: InsightsEngine) -> None:
        engine.store_insight(
            Insight(
                insight_type=InsightType.REMINDERS_OVERDUE,
                title="Rappel manque",
                content="...",
                score=0.8,
                priority=InsightPriority.HIGH,
            )
        )
        summary = engine.get_summary_for_briefing()
        assert "Insights:" in summary
        assert "Rappel manque" in summary

    def test_marks_insights_as_seen(self, engine: InsightsEngine) -> None:
        engine.store_insight(
            Insight(
                insight_type=InsightType.ORGANIZATION,
                title="Dossier plein",
                content="...",
                score=0.6,
                priority=InsightPriority.LOW,
            )
        )
        engine.get_summary_for_briefing()
        # Apres le briefing, l'insight doit etre marque comme vu
        assert engine.get_pending_insights() == []

    def test_priority_symbols(self, engine: InsightsEngine) -> None:
        for priority, symbol in [
            (InsightPriority.HIGH, "!"),
            (InsightPriority.MEDIUM, "~"),
            (InsightPriority.LOW, "."),
        ]:
            e = InsightsEngine(db_path=":memory:")  # type: ignore[arg-type]
            e._init_db()
            e.store_insight(
                Insight(
                    insight_type=InsightType.ORGANIZATION,
                    title=f"Test {priority.value}",
                    content="...",
                    score=0.9,
                    priority=priority,
                )
            )
            summary = e.get_summary_for_briefing()
            assert f"[{symbol}]" in summary
            e.close()


class TestPurgeExpired:
    def test_purge_removes_expired(self, engine: InsightsEngine) -> None:
        stored_id = engine.store_insight(
            Insight(
                insight_type=InsightType.ORGANIZATION,
                title="Old insight",
                content="...",
                score=0.5,
                priority=InsightPriority.LOW,
            )
        )
        assert stored_id is not None
        engine._conn.execute(
            "UPDATE insights SET expires_at = ? WHERE id = ?",
            (time.time() - 1, stored_id),
        )
        engine._conn.commit()
        deleted = engine.purge_expired()
        assert deleted == 1

    def test_purge_keeps_valid(self, engine: InsightsEngine) -> None:
        engine.store_insight(
            Insight(
                insight_type=InsightType.ORGANIZATION,
                title="Fresh",
                content="...",
                score=0.5,
                priority=InsightPriority.LOW,
            )
        )
        deleted = engine.purge_expired()
        assert deleted == 0


class TestClose:
    def test_close_does_not_raise(self, engine: InsightsEngine) -> None:
        engine.close()
