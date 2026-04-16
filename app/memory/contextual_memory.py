"""
Memoire contextuelle persistante pour Agent Lucide.
Stocke les preferences utilisateur, les patterns d'usage, et fournit
du contexte pertinent pour chaque requete.

Fix async: sqlite3 synchrone remplacé par aiosqlite — ne bloque plus l'event loop.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

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
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        logger.info(f"ContextualMemory initialisee ({db_path})")

    async def _get_conn(self) -> aiosqlite.Connection:
        """Retourne la connexion aiosqlite, en la créant si nécessaire."""
        if self._conn is None:
            conn = await aiosqlite.connect(self._db_path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await self._init_db(conn)
            self._conn = conn
        return self._conn

    async def _init_db(self, conn: aiosqlite.Connection) -> None:
        """Cree les tables si elles n'existent pas."""
        await conn.execute("""
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL,
                pattern_data TEXT NOT NULL,
                frequency INTEGER DEFAULT 1,
                last_seen TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.commit()

    async def learn_preference(
        self,
        category: str,
        key: str,
        value: str,
        confidence: float = 0.5,
    ) -> None:
        """Apprend une preference. La confiance augmente si confirmee, baisse si contredite."""
        async with self._lock:
            conn = await self._get_conn()
            cursor = await conn.execute(
                "SELECT value, confidence, hit_count FROM preferences WHERE category = ? AND key = ?",
                (category, key),
            )
            existing = await cursor.fetchone()

            if existing:
                old_value, old_conf, hit_count = existing["value"], existing["confidence"], existing["hit_count"]
                if old_value == value:
                    new_conf = min(1.0, old_conf + 0.1)
                    new_count = hit_count + 1
                else:
                    new_conf = max(0.1, old_conf - 0.2)
                    new_count = 1
                await conn.execute(
                    """
                    UPDATE preferences
                    SET value = ?, confidence = ?, hit_count = ?,
                        last_used = CURRENT_TIMESTAMP
                    WHERE category = ? AND key = ?
                    """,
                    (value, new_conf, new_count, category, key),
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO preferences (category, key, value, confidence)
                    VALUES (?, ?, ?, ?)
                    """,
                    (category, key, value, confidence),
                )
            await conn.commit()

    async def get_preference(self, category: str, key: str) -> Optional[str]:
        """Recupere une preference avec score de confiance > 0.3."""
        async with self._lock:
            conn = await self._get_conn()
            cursor = await conn.execute(
                """
                SELECT value, confidence FROM preferences
                WHERE category = ? AND key = ? AND confidence >= 0.3
                """,
                (category, key),
            )
            row = await cursor.fetchone()
        if row:
            return str(row["value"])
        return None

    async def get_preferences_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Recupere toutes les preferences d'une categorie."""
        async with self._lock:
            conn = await self._get_conn()
            cursor = await conn.execute(
                """
                SELECT key, value, confidence, hit_count
                FROM preferences
                WHERE category = ? AND confidence >= 0.3
                ORDER BY confidence DESC
                """,
                (category,),
            )
            rows = await cursor.fetchall()
        return [
            {"key": r["key"], "value": r["value"], "confidence": r["confidence"], "hit_count": r["hit_count"]}
            for r in rows
        ]

    async def learn_pattern(self, pattern_type: str, pattern_data: Dict[str, Any]) -> None:
        """Apprend un pattern d'usage (heure, frequence, sequence d'actions)."""
        data_json = json.dumps(pattern_data)
        async with self._lock:
            conn = await self._get_conn()
            cursor = await conn.execute(
                """
                SELECT id, frequency FROM usage_patterns
                WHERE pattern_type = ? AND pattern_data = ?
                """,
                (pattern_type, data_json),
            )
            existing = await cursor.fetchone()

            if existing:
                await conn.execute(
                    """
                    UPDATE usage_patterns
                    SET frequency = frequency + 1, last_seen = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (existing["id"],),
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO usage_patterns (pattern_type, pattern_data)
                    VALUES (?, ?)
                    """,
                    (pattern_type, data_json),
                )
            await conn.commit()

    async def get_patterns(self, pattern_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Recupere les patterns d'usage."""
        async with self._lock:
            conn = await self._get_conn()
            if pattern_type:
                cursor = await conn.execute(
                    """
                    SELECT pattern_type, pattern_data, frequency, last_seen
                    FROM usage_patterns
                    WHERE pattern_type = ?
                    ORDER BY frequency DESC
                    """,
                    (pattern_type,),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT pattern_type, pattern_data, frequency, last_seen
                    FROM usage_patterns
                    ORDER BY frequency DESC
                    """
                )
            rows = await cursor.fetchall()
        return [
            {
                "type": r["pattern_type"],
                "data": json.loads(r["pattern_data"]),
                "frequency": r["frequency"],
                "last_seen": r["last_seen"],
            }
            for r in rows
        ]

    async def get_context_for_query(self, query: str) -> Dict[str, Any]:
        """Retourne le contexte pertinent pour une requete donnee."""
        context: Dict[str, Any] = {}

        comm_prefs = await self.get_preferences_by_category("communication")
        if comm_prefs:
            context["communication"] = {p["key"]: p["value"] for p in comm_prefs}

        workflow_prefs = await self.get_preferences_by_category("workflow")
        if workflow_prefs:
            context["workflow"] = {p["key"]: p["value"] for p in workflow_prefs}

        patterns = await self.get_patterns()
        if patterns:
            context["recent_patterns"] = patterns[:5]

        content_prefs = await self.get_preferences_by_category("content")
        if content_prefs:
            context["content_interests"] = {p["key"]: p["value"] for p in content_prefs}

        return context

    async def close(self) -> None:
        """Ferme la connexion aiosqlite."""
        conn = self._conn
        if conn is not None:
            await conn.close()
            self._conn = None
