"""
Suivi des habitudes utilisateur pour la proactivite.
Enregistre les actions recurrentes et detecte les patterns temporels
(heure, jour de la semaine, frequence) afin de proposer des actions
avant meme que l'utilisateur les demande.
"""

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Suggestion:
    """Suggestion basee sur un pattern d'habitude detecte."""

    action: str
    confidence: float
    message: str
    frequency: int
    context: Dict[str, Any] = field(default_factory=dict)


class HabitsTracker:
    """
    Suivi et detection des habitudes recurrentes de l'utilisateur.

    Stocke les actions dans SQLite (table habits) avec leur heure et
    jour de la semaine. Detecte les patterns par frequence et propose
    des suggestions contextuelles.
    """

    MIN_FREQUENCY_FOR_SUGGESTION: int = 3
    CONFIDENCE_THRESHOLD: float = 0.4
    HOUR_WINDOW: int = 1  # +/- 1 heure pour matcher un pattern

    DAY_NAMES: List[str] = [
        "lundi", "mardi", "mercredi", "jeudi",
        "vendredi", "samedi", "dimanche",
    ]

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Initialise le tracker avec une base SQLite.

        Args:
            db_path: Chemin vers la BDD. Par defaut ./data/habits.db.
        """
        if db_path is None:
            data_dir = Path("./data")
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "habits.db")

        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_db()
        logger.info(f"HabitsTracker initialise ({db_path})")

    def _init_db(self) -> None:
        """Cree les tables et index si inexistants."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                hour_of_day INTEGER NOT NULL,
                day_of_week INTEGER NOT NULL,
                frequency INTEGER DEFAULT 1,
                last_seen REAL NOT NULL,
                confidence REAL DEFAULT 0.1,
                context TEXT DEFAULT '{}',
                UNIQUE(action, hour_of_day, day_of_week)
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_habits_action ON habits(action)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_habits_hour ON habits(hour_of_day)"
        )
        self._conn.commit()

    def record_action(
        self,
        action: str,
        context: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """
        Enregistre une action et incremente sa frequence.

        Args:
            action: Identifiant de l'action (ex: "open_email", "web_search").
            context: Donnees contextuelles libres associees a l'action.
            timestamp: Horodatage Unix. Utilise time.time() si omis.
        """
        ts = timestamp if timestamp is not None else time.time()
        dt = datetime.fromtimestamp(ts)
        hour = dt.hour
        day = dt.weekday()  # 0=lundi … 6=dimanche
        ctx_json = json.dumps(context or {})

        with self._lock:
            existing = self._conn.execute(
                """
                SELECT id, frequency, confidence FROM habits
                WHERE action = ? AND hour_of_day = ? AND day_of_week = ?
                """,
                (action, hour, day),
            ).fetchone()

            if existing:
                row_id: int = existing[0]
                freq: int = existing[1]
                conf: float = existing[2]
                new_freq = freq + 1
                new_conf = min(1.0, conf + 0.05)
                self._conn.execute(
                    """
                    UPDATE habits
                    SET frequency = ?, confidence = ?, last_seen = ?, context = ?
                    WHERE id = ?
                    """,
                    (new_freq, new_conf, ts, ctx_json, row_id),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO habits
                        (action, hour_of_day, day_of_week, frequency, last_seen,
                         confidence, context)
                    VALUES (?, ?, ?, 1, ?, 0.1, ?)
                    """,
                    (action, hour, day, ts, ctx_json),
                )
            self._conn.commit()

    def get_suggestions(
        self,
        current_time: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Suggestion]:
        """
        Retourne les suggestions pertinentes pour l'heure et le jour actuels.

        Args:
            current_time: Horodatage Unix de reference. Defaut: maintenant.
            context: Contexte courant (non utilise actuellement, reserve).

        Returns:
            Liste de Suggestion triee par confiance decroissante.
        """
        ts = current_time if current_time is not None else time.time()
        dt = datetime.fromtimestamp(ts)
        hour = dt.hour
        day = dt.weekday()

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT action, frequency, confidence, last_seen, context
                FROM habits
                WHERE
                    ABS(hour_of_day - ?) <= ?
                    AND day_of_week = ?
                    AND frequency >= ?
                    AND confidence >= ?
                ORDER BY confidence DESC, frequency DESC
                LIMIT 5
                """,
                (
                    hour,
                    self.HOUR_WINDOW,
                    day,
                    self.MIN_FREQUENCY_FOR_SUGGESTION,
                    self.CONFIDENCE_THRESHOLD,
                ),
            ).fetchall()

        suggestions: List[Suggestion] = []
        day_name = self.DAY_NAMES[day]

        for row in rows:
            action: str = row[0]
            freq: int = row[1]
            conf: float = row[2]
            ctx: Dict[str, Any] = {}
            try:
                ctx = json.loads(row[4])
            except (json.JSONDecodeError, TypeError):
                pass

            msg = (
                f"Chaque {day_name} vers {hour}h, tu fais '{action}' "
                f"({freq} fois, confiance {conf:.0%}). "
                "Veux-tu que je le lance ?"
            )
            suggestions.append(
                Suggestion(
                    action=action,
                    confidence=conf,
                    message=msg,
                    frequency=freq,
                    context=ctx,
                )
            )

        return suggestions

    def get_all_habits(self, min_frequency: int = 1) -> List[Dict[str, Any]]:
        """
        Retourne tous les patterns d'habitudes enregistres.

        Args:
            min_frequency: Frequence minimale pour etre inclus.

        Returns:
            Liste de dicts avec action, hour, day, frequency, confidence.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT action, hour_of_day, day_of_week, frequency,
                       confidence, last_seen
                FROM habits
                WHERE frequency >= ?
                ORDER BY frequency DESC
                """,
                (min_frequency,),
            ).fetchall()

        return [
            {
                "action": r[0],
                "hour": r[1],
                "day": self.DAY_NAMES[r[2]],
                "day_index": r[2],
                "frequency": r[3],
                "confidence": r[4],
                "last_seen": r[5],
            }
            for r in rows
        ]

    def decay_old_habits(self, max_age_days: int = 90) -> int:
        """
        Reduit la confiance des habitudes non vues depuis max_age_days jours
        et supprime celles dont la confiance atteint zero.

        Args:
            max_age_days: Age limite avant declenchement de la depreciation.

        Returns:
            Nombre d'habitudes supprimees.
        """
        threshold = time.time() - max_age_days * 86400
        with self._lock:
            self._conn.execute(
                """
                UPDATE habits
                SET confidence = MAX(0.0, confidence - 0.1)
                WHERE last_seen < ?
                """,
                (threshold,),
            )
            result = self._conn.execute(
                "DELETE FROM habits WHERE confidence <= 0.0"
            )
            deleted: int = result.rowcount
            self._conn.commit()

        if deleted > 0:
            logger.info(f"HabitsTracker: {deleted} habitudes supprimees (trop anciennes)")
        return deleted

    def close(self) -> None:
        """Ferme la connexion SQLite."""
        self._conn.close()
