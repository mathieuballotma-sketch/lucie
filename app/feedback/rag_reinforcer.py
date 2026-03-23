"""
Renforcement du RAG via le feedback utilisateur.

Maintient un index de scores parallèle (SQLite) pour booster ou pénaliser
les résultats sans modifier l'index FAISS directement.

Principe :
- Feedback positif (👍) → +1.0 sur le score de la requête
- Feedback négatif (👎) → −1.0 sur le score de la requête
- Le score cumulé peut être consulté pour réordonner les résultats RAG
"""

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import aiosqlite

from app.utils.logger import logger

# ---------------------------------------------------------------------------
# Schéma SQL
# ---------------------------------------------------------------------------
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS rag_scores (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash     TEXT    NOT NULL UNIQUE,
    score_delta    REAL    NOT NULL DEFAULT 0.0,
    last_updated   TEXT    DEFAULT (datetime('now')),
    total_positive INTEGER DEFAULT 0,
    total_negative INTEGER DEFAULT 0
)
"""


def _hash(text: str) -> str:
    """Hash blake2b pour identifier un vecteur de requête."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


# ---------------------------------------------------------------------------
# RAGReinforcer
# ---------------------------------------------------------------------------

class RAGReinforcer:
    """
    Utilise le feedback pour améliorer la pertinence du RAG.

    Maintient un score additionnel par requête :
    - Feedback positif → +BOOST_VALUE  (favorise ce vecteur)
    - Feedback négatif → +PENALTY_VALUE (pénalise ce vecteur)

    Le score est persisté dans SQLite et peut être consulté
    pour ajuster le ranking des résultats FAISS.
    """

    BOOST_VALUE: float = 1.0
    PENALTY_VALUE: float = -1.0

    def __init__(self, db_path: Path) -> None:
        """
        Args:
            db_path: chemin absolu vers le fichier SQLite des scores RAG.
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
                    await db.commit()
                self._initialized = True
                logger.info(f"🔧 RAGReinforcer initialisé → {self.db_path}")
            except Exception as exc:
                logger.error(f"Erreur init RAGReinforcer : {exc}")

    # ------------------------------------------------------------------
    # Renforcement
    # ------------------------------------------------------------------

    async def reinforce(self, query: str, positive: bool) -> None:
        """
        Ajuste le score du vecteur associé à la requête.

        Args:
            query:    requête originale de l'utilisateur.
            positive: True pour booster, False pour pénaliser.
        """
        await self._ensure_initialized()
        query_hash = _hash(query)
        delta = self.BOOST_VALUE if positive else self.PENALTY_VALUE
        pos_inc = 1 if positive else 0
        neg_inc = 0 if positive else 1
        try:
            async with aiosqlite.connect(str(self.db_path)) as db:
                # UPSERT : création ou mise à jour du score cumulé
                await db.execute(
                    """
                    INSERT INTO rag_scores
                        (query_hash, score_delta, total_positive, total_negative)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(query_hash) DO UPDATE SET
                        score_delta    = score_delta    + excluded.score_delta,
                        total_positive = total_positive + excluded.total_positive,
                        total_negative = total_negative + excluded.total_negative,
                        last_updated   = datetime('now')
                    """,
                    (query_hash, delta, pos_inc, neg_inc),
                )
                await db.commit()
            action = "boosté ↑" if positive else "pénalisé ↓"
            logger.debug(
                f"🔧 RAG {action} — hash={query_hash[:8]}…, delta={delta:+.1f}"
            )
        except Exception as exc:
            logger.error(f"Erreur RAGReinforcer.reinforce : {exc}")

    # ------------------------------------------------------------------
    # Consultation
    # ------------------------------------------------------------------

    async def get_score(self, query: str) -> float:
        """
        Retourne le score cumulé pour une requête donnée.

        Args:
            query: requête à évaluer.

        Returns:
            delta cumulé (positif = bien noté, négatif = mal noté, 0.0 si inconnu).
        """
        await self._ensure_initialized()
        query_hash = _hash(query)
        try:
            async with aiosqlite.connect(str(self.db_path)) as db:
                async with db.execute(
                    "SELECT score_delta FROM rag_scores WHERE query_hash = ?",
                    (query_hash,),
                ) as cursor:
                    row = await cursor.fetchone()
            return float(row[0]) if row else 0.0
        except Exception as exc:
            logger.error(f"Erreur RAGReinforcer.get_score : {exc}")
            return 0.0

    async def get_top_negative(self, limit: int = 10) -> list[Any]:
        """
        Retourne les requêtes avec le score le plus négatif.

        Args:
            limit: nombre maximum de résultats.

        Returns:
            liste de tuples (query_hash, score_delta, total_negative).
        """
        await self._ensure_initialized()
        try:
            async with aiosqlite.connect(str(self.db_path)) as db:
                async with db.execute(
                    """
                    SELECT query_hash, score_delta, total_negative
                    FROM   rag_scores
                    ORDER  BY score_delta ASC
                    LIMIT  ?
                    """,
                    (limit,),
                ) as cursor:
                    rows = await cursor.fetchall()
            return list(rows)
        except Exception as exc:
            logger.error(f"Erreur RAGReinforcer.get_top_negative : {exc}")
            return []
