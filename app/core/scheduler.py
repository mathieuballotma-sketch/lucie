"""
Scheduler - Exécute des tâches planifiées (cron-like) de manière asynchrone.
"""

import asyncio
import time
from typing import Callable, Dict, Optional
from croniter import croniter
from app.utils.logger import logger


class ScheduledJob:
    def __init__(self, job_id: str, func: Callable, cron_expr: str, kwargs: Optional[Dict] = None):
        self.job_id = job_id
        self.func = func
        self.cron_expr = cron_expr
        self.kwargs = kwargs or {}
        self.next_run = self._get_next_run()

    def _get_next_run(self, base: float = time.time()) -> float:
        cron = croniter(self.cron_expr, base)
        return cron.get_next(float)


class Scheduler:
    """
    Service de planification asynchrone.
    """

    def __init__(self):
        self._jobs: Dict[str, ScheduledJob] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def add_job(self, job_id: str, func: Callable, cron_expr: str, kwargs: Optional[Dict] = None):
        """Ajoute un job planifié."""
        job = ScheduledJob(job_id, func, cron_expr, kwargs)
        self._jobs[job_id] = job
        logger.info(f"📅 Job '{job_id}' ajouté avec cron '{cron_expr}'")

    def remove_job(self, job_id: str):
        """Supprime un job."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            logger.info(f"📅 Job '{job_id}' supprimé")

    async def start(self):
        """Démarre la boucle de planification."""
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("⏰ Scheduler démarré")

    async def stop(self):
        """Arrête la boucle."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("⏰ Scheduler arrêté")

    async def _run(self):
        while self._running:
            now = time.time()
            next_run = None
            for job in self._jobs.values():
                if job.next_run <= now:
                    # Exécuter le job dans une tâche séparée
                    asyncio.create_task(self._execute_job(job))
                    job.next_run = job._get_next_run(now)
                if next_run is None or job.next_run < next_run:
                    next_run = job.next_run
            if next_run is None:
                await asyncio.sleep(60)  # Attente par défaut
            else:
                sleep_time = max(0, next_run - time.time())
                await asyncio.sleep(sleep_time)

    async def _execute_job(self, job: ScheduledJob):
        try:
            logger.info(f"⏰ Exécution du job '{job.job_id}'")
            if asyncio.iscoroutinefunction(job.func):
                await job.func(**job.kwargs)
            else:
                job.func(**job.kwargs)
        except Exception as e:
            logger.error(f"Erreur lors de l'exécution du job '{job.job_id}': {e}")
