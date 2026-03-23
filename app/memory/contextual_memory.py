"""
Memoire contextuelle persistante pour Agent Lucide.
Stocke les preferences utilisateur, les patterns d'usage, et fournit
du contexte pertinent pour chaque requete.
"""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)


class ContextualMemory:
    """Memoire a long terme des preferences et habitudes de l'utilisateur."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            data_dir = Path("./data")
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "contextual_memory.db")

        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_db()
        logger.info(f"ContextualMemory initialisee ({db_path})")

    def _init_db(self) -> None:
        """Cree les tables si elles n'existent pas."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                hit_count INTEGER DEFAULT 1,
                last_used TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, key)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL,
                pattern_data TEXT NOT NULL,
                frequency INTEGER DEFAULT 1,
                last_seen TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    async def learn_preference(
        self,
        category: str,
        key: str,
        value: str,
        confidence: float = 0.5,
    ) -> None:
        """Apprend une preference. La confiance augmente si confirmee, baisse si contredite."""
        with self._lock:
            existing = self._conn.execute(
                "SELECT value, confidence, hit_count FROM preferences WHERE category = ? AND key = ?",
                (category, key),
            ).fetchone()

            if existing:
                old_value, old_conf, hit_count = existing
                if old_value == value:
                    # Confirme — augmenter la confiance
                    new_conf = min(1.0, old_conf + 0.1)
                    new_count = hit_count + 1
                else:
                    # Contredit — baisser puis remplacer
                    new_conf = max(0.1, old_conf - 0.2)
                    new_count = 1
                self._conn.execute(
                    """
                    UPDATE preferences
                    SET value = ?, confidence = ?, hit_count = ?,
                        last_used = CURRENT_TIMESTAMP
                    WHERE category = ? AND key = ?
                    """,
                    (value, new_conf, new_count, category, key),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO preferences (category, key, value, confidence)
                    VALUES (?, ?, ?, ?)
                    """,
                    (category, key, value, confidence),
                )
            self._conn.commit()

    async def get_preference(self, category: str, key: str) -> Optional[str]:
        """Recupere une preference avec score de confiance > 0.3."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT value, confidence FROM preferences
                WHERE category = ? AND key = ? AND confidence >= 0.3
                """,
                (category, key),
            ).fetchone()
        if row:
            return str(row[0])
        return None

    async def get_preferences_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Recupere toutes les preferences d'une categorie."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT key, value, confidence, hit_count
                FROM preferences
                WHERE category = ? AND confidence >= 0.3
                ORDER BY confidence DESC
                """,
                (category,),
            ).fetchall()
        return [
            {"key": r[0], "value": r[1], "confidence": r[2], "hit_count": r[3]}
            for r in rows
        ]

    async def learn_pattern(self, pattern_type: str, pattern_data: Dict[str, Any]) -> None:
        """Apprend un pattern d'usage (heure, frequence, sequence d'actions)."""
        data_json = json.dumps(pattern_data)
        with self._lock:
            # Verifier si un pattern similaire existe
            existing = self._conn.execute(
                """
                SELECT id, frequency FROM usage_patterns
                WHERE pattern_type = ? AND pattern_data = ?
                """,
                (pattern_type, data_json),
            ).fetchone()

            if existing:
                self._conn.execute(
                    """
                    UPDATE usage_patterns
                    SET frequency = frequency + 1, last_seen = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (existing[0],),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO usage_patterns (pattern_type, pattern_data)
                    VALUES (?, ?)
                    """,
                    (pattern_type, data_json),
                )
            self._conn.commit()

    async def get_patterns(self, pattern_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Recupere les patterns d'usage."""
        with self._lock:
            if pattern_type:
                rows = self._conn.execute(
                    """
                    SELECT pattern_type, pattern_data, frequency, last_seen
                    FROM usage_patterns
                    WHERE pattern_type = ?
                    ORDER BY frequency DESC
                    """,
                    (pattern_type,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT pattern_type, pattern_data, frequency, last_seen
                    FROM usage_patterns
                    ORDER BY frequency DESC
                    """
                ).fetchall()
        return [
            {
                "type": r[0],
                "data": json.loads(r[1]),
                "frequency": r[2],
                "last_seen": r[3],
            }
            for r in rows
        ]

    async def get_context_for_query(self, query: str) -> Dict[str, Any]:
        """Retourne le contexte pertinent pour une requete donnee."""
        context: Dict[str, Any] = {}

        # Preferences de communication
        comm_prefs = await self.get_preferences_by_category("communication")
        if comm_prefs:
            context["communication"] = {p["key"]: p["value"] for p in comm_prefs}

        # Preferences de workflow
        workflow_prefs = await self.get_preferences_by_category("workflow")
        if workflow_prefs:
            context["workflow"] = {p["key"]: p["value"] for p in workflow_prefs}

        # Patterns recents
        patterns = await self.get_patterns()
        if patterns:
            context["recent_patterns"] = patterns[:5]

        # Sujets frequents
        content_prefs = await self.get_preferences_by_category("content")
        if content_prefs:
            context["content_interests"] = {p["key"]: p["value"] for p in content_prefs}

        return context

    def close(self) -> None:
        """Ferme la connexion SQLite."""
        self._conn.close()
