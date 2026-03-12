import sqlite3
import json
import time
from pathlib import Path
from typing import Optional, Dict, List

class SignatureDB:
    """
    Base de données locale des signatures de menaces.
    Utilise SQLite pour stocker :
    - signature_id (hash)
    - pattern (message normalisé)
    - first_seen, last_seen, count
    - affected_agents (JSON)
    - severity (float)
    - resolved (bool)
    - solution (str)
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path.home() / ".agent_lucide" / "signatures.db"
        self.db_path = db_path
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signatures (
                    id TEXT PRIMARY KEY,
                    pattern TEXT NOT NULL,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    count INTEGER DEFAULT 1,
                    affected_agents TEXT, -- JSON array
                    severity REAL DEFAULT 0.1,
                    resolved INTEGER DEFAULT 0,
                    solution TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS threats_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    signature_id TEXT,
                    agent TEXT,
                    tool TEXT,
                    error TEXT,
                    metadata TEXT, -- JSON
                    FOREIGN KEY(signature_id) REFERENCES signatures(id)
                )
            """)
    
    def add_or_update_signature(self, signature_id: str, pattern: str, agent: str, tool: str, error: str, severity: float = 0.1):
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            # Vérifier si la signature existe déjà
            cur = conn.execute("SELECT count, affected_agents FROM signatures WHERE id = ?", (signature_id,))
            row = cur.fetchone()
            if row:
                count, affected_agents_json = row
                affected = json.loads(affected_agents_json) if affected_agents_json else []
                if agent not in affected:
                    affected.append(agent)
                conn.execute("""
                    UPDATE signatures SET
                        last_seen = ?,
                        count = count + 1,
                        affected_agents = ?
                    WHERE id = ?
                """, (now, json.dumps(affected), signature_id))
            else:
                affected = [agent]
                conn.execute("""
                    INSERT INTO signatures (id, pattern, first_seen, last_seen, count, affected_agents, severity)
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                """, (signature_id, pattern, now, now, json.dumps(affected), severity))
    
    def log_threat(self, signature_id: Optional[str], agent: str, tool: str, error: str, metadata: Optional[Dict] = None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO threats_log (timestamp, signature_id, agent, tool, error, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (time.time(), signature_id, agent, tool, error, json.dumps(metadata) if metadata else None))
    
    def get_signature(self, signature_id: str) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM signatures WHERE id = ?", (signature_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
        return None
    
    def get_recent_threats(self, limit: int = 100) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM threats_log ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]