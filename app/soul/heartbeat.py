"""
Gestion des routines périodiques (Heartbeat).
Lit les routines depuis HEARTBEAT.md et les programme.
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Callable

class HeartbeatManager:
    def __init__(self, heartbeat_path: str = "~/AgentLucide/HEARTBEAT.md", scheduler=None):
        self.heartbeat_path = Path(heartbeat_path).expanduser()
        self.scheduler = scheduler
        self.routines = []

    def load_routines(self) -> List[Dict[str, Any]]:
        if not self.heartbeat_path.exists():
            # Créer un exemple
            example = """# Routines automatiques d'Agent Lucie

## Toutes les 30 minutes
- Vérifier les nouveaux emails
- Résumer l'activité récente

## Toutes les heures
- Sauvegarder la mémoire
- Nettoyer les fichiers temporaires

## Chaque jour à 8h
- Rappeler les tâches du jour
- Proposer un résumé des actualités
"""
            self.heartbeat_path.write_text(example)
            content = example
        else:
            content = self.heartbeat_path.read_text()

        routines = []
        current_interval = None
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('## '):
                current_interval = line[3:].strip()
            elif line.startswith('- ') and current_interval:
                task = line[2:].strip()
                routines.append({
                    'interval': current_interval,
                    'task': task
                })
        return routines

    async def schedule_all(self, execute_task: Callable):
        """Programme toutes les routines dans le scheduler."""
        routines = self.load_routines()
        for r in routines:
            interval = r['interval']
            task_desc = r['task']
            # Convertir l'intervalle en cron ou en secondes
            if 'minutes' in interval:
                match = re.search(r'(\d+)\s*minutes?', interval)
                if match:
                    minutes = int(match.group(1))
                    # Ajouter au scheduler toutes les minutes
                    self.scheduler.add_interval_job(
                        func=lambda: execute_task(task_desc),
                        minutes=minutes,
                        job_id=f"heartbeat_{task_desc[:20]}"
                    )
            elif 'heures' in interval:
                match = re.search(r'(\d+)\s*heures?', interval)
                if match:
                    hours = int(match.group(1))
                    self.scheduler.add_interval_job(
                        func=lambda: execute_task(task_desc),
                        hours=hours,
                        job_id=f"heartbeat_{task_desc[:20]}"
                    )
            elif 'jour' in interval or 'jours' in interval:
                # Format "Chaque jour à 8h"
                match = re.search(r'à\s*(\d+)h', interval)
                if match:
                    hour = int(match.group(1))
                    self.scheduler.add_cron_job(
                        func=lambda: execute_task(task_desc),
                        cron_expr=f"0 {hour} * * *",
                        job_id=f"heartbeat_{task_desc[:20]}"
                    )
            else:
                # Par défaut, interpréter comme expression cron
                self.scheduler.add_cron_job(
                    func=lambda: execute_task(task_desc),
                    cron_expr=interval,
                    job_id=f"heartbeat_{task_desc[:20]}"
                )
