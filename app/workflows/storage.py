"""
WorkflowStorage — Stockage SQLite des workflows.

Gère la persistance des workflows via SQLite avec sérialisation JSON.
Thread-safe via threading.Lock.
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import List, Optional

from ..utils.logger import logger
from .schemas import Workflow


_DEFAULT_DB_DIR = os.path.join(os.path.expanduser("~"), ".lucie", "data")
_DEFAULT_DB_PATH = os.path.join(_DEFAULT_DB_DIR, "workflows.db")


class WorkflowStorage:
    """Persistance SQLite pour les workflows."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._lock = threading.Lock()
        self._ensure_dir()
        self._init_db()

    def _ensure_dir(self) -> None:
        """Crée le répertoire parent si nécessaire."""
        parent = os.path.dirname(self._db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _init_db(self) -> None:
        """Crée la table workflows si elle n'existe pas."""
        with self._lock:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflows (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT DEFAULT '',
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def save(self, workflow: Workflow) -> str:
        """
        Sauvegarde ou met à jour un workflow.

        Retourne l'ID du workflow.
        """
        now = datetime.now(timezone.utc).isoformat()
        data = workflow.json()

        with self._lock:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                conn.execute(
                    """
                    INSERT INTO workflows (id, name, description, data, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        description = excluded.description,
                        data = excluded.data,
                        updated_at = excluded.updated_at
                    """,
                    (workflow.id, workflow.name, workflow.description, data, now, now),
                )
                conn.commit()
            finally:
                conn.close()

        logger.debug(f"WorkflowStorage: sauvegardé '{workflow.id}' ({workflow.name})")
        return workflow.id

    def load(self, workflow_id: str) -> Optional[Workflow]:
        """Charge un workflow par son ID. Retourne None si introuvable."""
        with self._lock:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                cursor = conn.execute(
                    "SELECT data FROM workflows WHERE id = ?", (workflow_id,)
                )
                row = cursor.fetchone()
            finally:
                conn.close()

        if row is None:
            return None

        try:
            return Workflow.parse_raw(row[0])
        except Exception as exc:
            logger.error(f"WorkflowStorage: erreur parsing workflow '{workflow_id}': {exc}")
            return None

    def list_all(self) -> List[Workflow]:
        """Liste tous les workflows stockés (triés par updated_at desc)."""
        with self._lock:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                cursor = conn.execute(
                    "SELECT data FROM workflows ORDER BY updated_at DESC"
                )
                rows = cursor.fetchall()
            finally:
                conn.close()

        result: List[Workflow] = []
        for row in rows:
            try:
                result.append(Workflow.parse_raw(row[0]))
            except Exception as exc:
                logger.debug(f"WorkflowStorage: skip workflow corrompu: {exc}")

        return result

    def delete(self, workflow_id: str) -> bool:
        """Supprime un workflow. Retourne True si supprimé."""
        with self._lock:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                cursor = conn.execute(
                    "DELETE FROM workflows WHERE id = ?", (workflow_id,)
                )
                conn.commit()
                deleted = cursor.rowcount > 0
            finally:
                conn.close()

        if deleted:
            logger.debug(f"WorkflowStorage: supprimé '{workflow_id}'")
        return deleted

    def count(self) -> int:
        """Retourne le nombre de workflows stockés."""
        with self._lock:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM workflows")
                return cursor.fetchone()[0]
            finally:
                conn.close()
