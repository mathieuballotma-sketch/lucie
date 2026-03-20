"""
Traqueur de leurres - Surveille les interactions avec les leurres.
"""

import sqlite3
import time
import json
from pathlib import Path
from typing import List, Dict, Optional
import threading

from app.utils.logger import logger


class LureTracker:
    """
    Enregistre et surveille les leurres déployés.
    Utilise une base SQLite pour persister les informations.
    """

    def __init__(self, config: dict, db_path: Path):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self):
        """Retourne une connexion SQLite pour le thread courant."""
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        """Crée la table des leurres si elle n'existe pas."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lures (
                id TEXT PRIMARY KEY,
                path TEXT UNIQUE,
                type TEXT,
                deployed_at REAL,
                threat_data TEXT,
                triggered INTEGER DEFAULT 0,
                trigger_count INTEGER DEFAULT 0,
                last_trigger REAL
            )
        """)
        conn.commit()

    def register_lure(self, path: str, lure_type: str, threat_data: Optional[Dict] = None):
        """Enregistre un nouveau leurre."""
        lure_id = path.split('/')[-1].split('.')[0] + '_' + str(int(time.time()))
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO lures (id, path, type, deployed_at, threat_data)
            VALUES (?, ?, ?, ?, ?)
        """, (lure_id, path, lure_type, time.time(), json.dumps(threat_data) if threat_data else None))
        conn.commit()
        logger.debug(f"Leurre enregistré: {path} (ID: {lure_id})")

    def mark_triggered(self, path: str, attacker_info: Optional[Dict] = None):
        """Marque un leurre comme déclenché."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE lures
            SET triggered = 1,
                trigger_count = trigger_count + 1,
                last_trigger = ?
            WHERE path = ?
        """, (time.time(), path))
        conn.commit()

        # Optionnel: enregistrer les infos de l'attaquant dans une table séparée
        if attacker_info:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS triggers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lure_id TEXT,
                    timestamp REAL,
                    attacker_ip TEXT,
                    attacker_info TEXT
                )
            """)
            # Récupérer l'ID du leurre
            cursor.execute("SELECT id FROM lures WHERE path = ?", (path,))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    INSERT INTO triggers (lure_id, timestamp, attacker_ip, attacker_info)
                    VALUES (?, ?, ?, ?)
                """, (row[0], time.time(), attacker_info.get('ip'), json.dumps(attacker_info)))
                conn.commit()

    def get_active_lures(self) -> List[Dict]:
        """Retourne la liste des leurres actifs (non déclenchés)."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM lures WHERE triggered = 0")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
