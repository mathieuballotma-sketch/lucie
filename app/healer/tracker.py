"""
Tracker - Enregistre les menaces et les actions.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from app.utils.logger import logger

class ThreatTracker:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self):
        if self.db_path.exists():
            with open(self.db_path, "r") as f:
                self.data = json.load(f)
        else:
            self.data = {"threats": [], "attackers": {}}

    def _save(self):
        with open(self.db_path, "w") as f:
            json.dump(self.data, f, indent=2)

    def add_threat(self, file_path: str, threat_hash: str, source_ip: Optional[str] = None, metadata: Optional[Dict] = None):
        """Ajoute une menace détectée."""
        threat = {
            "timestamp": datetime.now().isoformat(),
            "file_path": file_path,
            "hash": threat_hash,
            "source_ip": source_ip,
            "metadata": metadata or {},
            "action": "quarantined"
        }
        self.data["threats"].append(threat)
        if source_ip:
            if source_ip not in self.data["attackers"]:
                self.data["attackers"][source_ip] = {
                    "first_seen": threat["timestamp"],
                    "last_seen": threat["timestamp"],
                    "threats": []
                }
            self.data["attackers"][source_ip]["last_seen"] = threat["timestamp"]
            self.data["attackers"][source_ip]["threats"].append(threat_hash)
        self._save()
        logger.info(f"Menace enregistrée : {threat_hash}")

    def get_stats(self) -> Dict[str, Any]:
        """Retourne des statistiques sur les menaces."""
        return {
            "total_threats": len(self.data["threats"]),
            "unique_attackers": len(self.data["attackers"]),
            "attackers": self.data["attackers"]
        }
