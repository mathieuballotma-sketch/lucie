"""
Base de données des attaquants - Stocke les informations sur les attaquants identifiés.
"""

import sqlite3
import time
import json
from pathlib import Path
from typing import List, Dict, Optional
import threading

from app.utils.logger import logger


class AttackerDatabase:
    """
    Stocke les informations sur les attaquants (IP, signature, etc.).
    """

    def __init__(self, config: dict):
        db_path = Path(config.get("attacker_db", "~/.agent_lucide/attackers.db")).expanduser()
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self):
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attackers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT,
                signature TEXT,
                first_seen REAL,
                last_seen REAL,
                count INTEGER DEFAULT 1,
                metadata TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ip ON attackers(ip)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signature ON attackers(signature)")
        conn.commit()

    def add_attacker(self, attacker_info: Dict):
        """Ajoute ou met à jour un attaquant."""
        ip = attacker_info.get('ip', 'unknown')
        signature = attacker_info.get('signature', 'unknown')
        metadata = json.dumps(attacker_info)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, count FROM attackers WHERE ip = ? AND signature = ?
        """, (ip, signature))
        row = cursor.fetchone()

        if row:
            # Mettre à jour
            cursor.execute("""
                UPDATE attackers
                SET last_seen = ?, count = count + 1, metadata = ?
                WHERE id = ?
            """, (time.time(), metadata, row[0]))
        else:
            # Insérer
            cursor.execute("""
                INSERT INTO attackers (ip, signature, first_seen, last_seen, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (ip, signature, time.time(), time.time(), metadata))
        conn.commit()

    def get_attackers(self) -> List[Dict]:
        """Retourne la liste des attaquants."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM attackers ORDER BY last_seen DESC")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]