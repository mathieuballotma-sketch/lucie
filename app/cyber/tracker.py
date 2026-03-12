import json
import time
from pathlib import Path
from typing import Optional, Dict, Any

class ThreatTracker:
    """
    Enregistre les événements suspects dans un fichier journal et peut les exporter.
    """
    
    def __init__(self, log_path: Optional[Path] = None):
        if log_path is None:
            log_path = Path.home() / ".agent_lucide" / "threats.jsonl"
        self.log_path = log_path
        self.log_path.parent.mkdir(exist_ok=True)
    
    def log_event(self, event_type: str, data: Dict[str, Any]):
        """Enregistre un événement avec horodatage."""
        entry = {
            "timestamp": time.time(),
            "type": event_type,
            "data": data
        }
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    
    def get_recent_events(self, limit: int = 100) -> list:
        """Récupère les derniers événements."""
        events = []
        try:
            with open(self.log_path, "r") as f:
                for line in f:
                    events.append(json.loads(line))
                    if len(events) > limit:
                        break
        except FileNotFoundError:
            pass
        return events