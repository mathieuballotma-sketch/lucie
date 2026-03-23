"""
Suivi du temps gagne grace a Lucie.
Mesure le temps reel des taches automatisees, compare avec l'estimation manuelle,
et persiste les resultats en SQLite.
"""

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TaskTiming:
    """Mesure le temps d'une tache automatisee."""

    task_type: str
    agent_name: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    estimated_manual_time: Optional[float] = None

    @property
    def actual_time(self) -> float:
        """Duree reelle de la tache en secondes."""
        if self.end_time is None:
            return time.time() - self.start_time
        return self.end_time - self.start_time

    @property
    def time_saved(self) -> float:
        """Temps gagne en secondes."""
        if self.estimated_manual_time is None:
            return 0.0
        return max(0.0, self.estimated_manual_time - self.actual_time)


class TimeTracker:
    """Suivi du temps gagne grace a Lucie, persiste en SQLite."""

    # Estimations moyennes du temps manuel par type de tache (en secondes)
    MANUAL_ESTIMATES: Dict[str, float] = {
        "file_read": 30.0,
        "file_write": 120.0,
        "web_search": 180.0,
        "document_gen": 1800.0,
        "email_draft": 300.0,
        "code_analysis": 600.0,
        "data_extraction": 900.0,
        "reminder_set": 15.0,
        "knowledge_query": 120.0,
        "planning": 900.0,
    }

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            data_dir = Path("./data")
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "time_tracker.db")

        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_db()
        logger.info(f"TimeTracker initialise ({db_path})")

    def _init_db(self) -> None:
        """Cree la table si elle n'existe pas."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS task_timings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL,
                actual_duration REAL,
                estimated_manual_time REAL,
                time_saved REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    def start_task(self, task_type: str, agent_name: str) -> TaskTiming:
        """Demarre le chronometrage d'une tache.

        Args:
            task_type: Type de tache (cle de MANUAL_ESTIMATES).
            agent_name: Nom de l'agent executant.

        Returns:
            TaskTiming a passer a end_task().
        """
        estimated = self.MANUAL_ESTIMATES.get(task_type)
        timing = TaskTiming(
            task_type=task_type,
            agent_name=agent_name,
            estimated_manual_time=estimated,
        )
        return timing

    def end_task(self, timing: TaskTiming) -> float:
        """Termine le chronometrage et persiste le resultat.

        Args:
            timing: TaskTiming retourne par start_task().

        Returns:
            Temps gagne en secondes.
        """
        timing.end_time = time.time()
        saved = timing.time_saved

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO task_timings
                    (task_type, agent_name, start_time, end_time,
                     actual_duration, estimated_manual_time, time_saved)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timing.task_type,
                    timing.agent_name,
                    timing.start_time,
                    timing.end_time,
                    timing.actual_time,
                    timing.estimated_manual_time,
                    saved,
                ),
            )
            self._conn.commit()

        return saved

    def get_daily_stats(self) -> Dict[str, Any]:
        """Statistiques du jour."""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(time_saved), 0),
                       COALESCE(SUM(actual_duration), 0)
                FROM task_timings
                WHERE DATE(created_at) = ?
                """,
                (today,),
            ).fetchone()

        count = row[0] if row else 0
        total_saved = row[1] if row else 0.0
        total_duration = row[2] if row else 0.0

        return {
            "date": today,
            "task_count": count,
            "time_saved_seconds": total_saved,
            "time_saved_formatted": self._format_duration(total_saved),
            "total_duration_seconds": total_duration,
        }

    def get_weekly_stats(self) -> Dict[str, Any]:
        """Statistiques de la semaine."""
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(time_saved), 0),
                       COALESCE(SUM(actual_duration), 0)
                FROM task_timings
                WHERE DATE(created_at) >= ?
                """,
                (week_ago,),
            ).fetchone()

        count = row[0] if row else 0
        total_saved = row[1] if row else 0.0
        total_duration = row[2] if row else 0.0

        return {
            "task_count": count,
            "time_saved_seconds": total_saved,
            "time_saved_formatted": self._format_duration(total_saved),
            "total_duration_seconds": total_duration,
        }

    def get_all_time_stats(self) -> Dict[str, Any]:
        """Statistiques depuis le debut."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(time_saved), 0),
                       COALESCE(SUM(actual_duration), 0)
                FROM task_timings
                """
            ).fetchone()

        count = row[0] if row else 0
        total_saved = row[1] if row else 0.0
        total_duration = row[2] if row else 0.0

        return {
            "task_count": count,
            "time_saved_seconds": total_saved,
            "time_saved_formatted": self._format_duration(total_saved),
            "total_duration_seconds": total_duration,
        }

    def get_streak(self) -> int:
        """Nombre de jours consecutifs d'utilisation."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT DISTINCT DATE(created_at) as d
                FROM task_timings
                ORDER BY d DESC
                """
            ).fetchall()

        if not rows:
            return 0

        dates = [datetime.strptime(r[0], "%Y-%m-%d").date() for r in rows]
        today = datetime.now().date()

        # Verifier que le dernier jour d'utilisation est aujourd'hui ou hier
        if dates[0] < today - timedelta(days=1):
            return 0

        streak = 1
        for i in range(1, len(dates)):
            if dates[i - 1] - dates[i] == timedelta(days=1):
                streak += 1
            else:
                break

        return streak

    def get_status_for_hud(self) -> Dict[str, Any]:
        """Retourne un resume pour le HUD."""
        daily = self.get_daily_stats()
        all_time = self.get_all_time_stats()
        return {
            "daily_saved": daily["time_saved_formatted"],
            "daily_tasks": daily["task_count"],
            "total_saved": all_time["time_saved_formatted"],
            "total_tasks": all_time["task_count"],
            "streak": self.get_streak(),
        }

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Formate une duree en texte lisible."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.0f}min"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            if minutes > 0:
                return f"{hours}h{minutes:02d}"
            return f"{hours}h"

    def close(self) -> None:
        """Ferme la connexion SQLite."""
        self._conn.close()
