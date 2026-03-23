"""
Collecte et stockage des retours utilisateur sur les réponses de Lucie.

Utilise SQLite/aiosqlite pour un stockage persistant et thread-safe.
Chaque feedback contient : requête, réponse, note (👍/👎), commentaire optionnel.

Principes :
- Homéostasie : fallbacks gracieux sur chaque opération
- Entropie     : hash blake2b pour anonymiser les données brutes
- Évolution    : statistiques exploitables pour améliorer le RAG
"""

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Dict, List

import aiosqlite

from app.utils.logger import logger

# ---------------------------------------------------------------------------
# Schéma SQL
# ---------------------------------------------------------------------------
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS feedback (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    DEFAULT (datetime('now')),
    query_hash    TEXT    NOT NULL,
    query_text    TEXT    NOT NULL,
    response_hash TEXT    NOT NULL,
    rating        INTEGER NOT NULL,   -- 1=positif, 0=négatif
    comment       TEXT    DEFAULT '',
    agent_used    TEXT    DEFAULT ''
)
"""

_CREATE_INDEX_TIMESTAMP = (
    "CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON feedback(timestamp)"
)
_CREATE_INDEX_RATING = (
    "CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating)"
)
_CREATE_INDEX_HASH = (
    "CREATE INDEX IF NOT EXISTS idx_feedback_query_hash ON feedback(query_hash)"
)


# ---------------------------------------------------------------------------
# Utilitaire de hachage
# ---------------------------------------------------------------------------

def _hash(text: str) -> str:
    """Calcule un hash blake2b (16 octets) sur le texte fourni."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


# ---------------------------------------------------------------------------
# FeedbackCollector
# ---------------------------------------------------------------------------

class FeedbackCollector:
    """
    Collecte et stocke les retours utilisateur sur les réponses de Lucie.

    Thread-safe via asyncio.Lock + aiosqlite.
    Les requêtes brutes sont tronquées à 1 000 caractères avant stockage.
    """

    def __init__(self, db_path: Path) -> None:
        """
        Args:
            db_path: chemin absolu vers le fichier SQLite de feedback.
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._initialized = False

    # ------------------------------------------------------------------
    # Initialisation lazy
    # ------------------------------------------------------------------

    async def _ensure_initialized(self) -> None:
        """Initialise la base de données au premier appel."""
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            try:
                async with aiosqlite.connect(str(self.db_path)) as db:
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.execute(_CREATE_TABLE_SQL)
                    await db.execute(_CREATE_INDEX_TIMESTAMP)
                    await db.execute(_CREATE_INDEX_RATING)
                    await db.execute(_CREATE_INDEX_HASH)
                    await db.commit()
                self._initialized = True
                logger.info(f"📊 FeedbackCollector initialisé → {self.db_path}")
            except Exception as exc:
                logger.error(f"Erreur init FeedbackCollector : {exc}")

    # ------------------------------------------------------------------
    # Enregistrement
    # ------------------------------------------------------------------

    async def record(
        self,
        query: str,
        response: str,
        rating: bool,
        comment: str = "",
        agent_used: str = "",
    ) -> None:
        """
        Enregistre un feedback utilisateur.

        Args:
            query:      requête de l'utilisateur
            response:   réponse de Lucie
            rating:     True = positif (👍), False = négatif (👎)
            comment:    commentaire libre (optionnel)
            agent_used: nom de l'agent ayant traité la requête (optionnel)
        """
        await self._ensure_initialized()
        rating_int = 1 if rating else 0
        query_hash = _hash(query)
        response_hash = _hash(response)
        try:
            async with aiosqlite.connect(str(self.db_path)) as db:
                await db.execute(
                    """
                    INSERT INTO feedback
                        (query_hash, query_text, response_hash, rating, comment, agent_used)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        query_hash,
                        query[:1000],
                        response_hash,
                        rating_int,
                        comment[:500],
                        agent_used[:100],
                    ),
                )
                await db.commit()
            emoji = "👍" if rating else "👎"
            logger.info(
                f"{emoji} Feedback enregistré — rating={rating_int}, agent={agent_used!r}"
            )
        except Exception as exc:
            logger.error(f"Erreur enregistrement feedback : {exc}")

    # ------------------------------------------------------------------
    # Statistiques
    # ------------------------------------------------------------------

    async def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques globales de satisfaction.

        Returns:
            dict avec clés : total, positifs, negatifs, ratio (0.0–1.0).
        """
        await self._ensure_initialized()
        try:
            async with aiosqlite.connect(str(self.db_path)) as db:
                async with db.execute(
                    "SELECT COUNT(*), SUM(rating) FROM feedback"
                ) as cursor:
                    row = await cursor.fetchone()
            if row is None or row[0] == 0:
                return {"total": 0, "positifs": 0, "negatifs": 0, "ratio": 0.0}
            total = int(row[0])
            positifs = int(row[1] or 0)
            negatifs = total - positifs
            ratio = positifs / total if total > 0 else 0.0
            return {
                "total": total,
                "positifs": positifs,
                "negatifs": negatifs,
                "ratio": round(ratio, 3),
            }
        except Exception as exc:
            logger.error(f"Erreur lecture stats feedback : {exc}")
            return {"total": 0, "positifs": 0, "negatifs": 0, "ratio": 0.0}

    async def get_negative_patterns(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retourne les requêtes les plus souvent mal notées.

        Args:
            limit: nombre maximum de résultats.

        Returns:
            liste de dicts {query_text, count, last_seen}.
        """
        await self._ensure_initialized()
        try:
            async with aiosqlite.connect(str(self.db_path)) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT query_text,
                           COUNT(*)        AS count,
                           MAX(timestamp)  AS last_seen
                    FROM   feedback
                    WHERE  rating = 0
                    GROUP  BY query_hash
                    ORDER  BY count DESC
                    LIMIT  ?
                    """,
                    (limit,),
                ) as cursor:
                    rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error(f"Erreur lecture patterns négatifs : {exc}")
            return []

    async def get_recent(
        self, days: int = 7, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Retourne les feedbacks récents pour le rapport hebdomadaire.

        Args:
            days:  nombre de jours en arrière (défaut : 7).
            limit: nombre maximum de résultats.

        Returns:
            liste de dicts {query_text, rating, comment, timestamp, agent_used}.
        """
        await self._ensure_initialized()
        try:
            async with aiosqlite.connect(str(self.db_path)) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT query_text, rating, comment, timestamp, agent_used
                    FROM   feedback
                    WHERE  timestamp >= datetime('now', ?)
                    ORDER  BY timestamp DESC
                    LIMIT  ?
                    """,
                    (f"-{days} days", limit),
                ) as cursor:
                    rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error(f"Erreur lecture feedbacks récents : {exc}")
            return []
