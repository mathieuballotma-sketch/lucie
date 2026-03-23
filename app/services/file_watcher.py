"""
Surveillance automatique des dossiers pour indexation incrementale.
Utilise du polling simple (compatible cross-platform, pas de dependance FSEvents).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, List, Optional

from ..utils.logger import get_logger

if TYPE_CHECKING:
    from .search_engine import LocalSearchEngine

logger = get_logger(__name__)


class FileWatcher:
    """Surveille les modifications de fichiers via polling."""

    def __init__(self, search_engine: LocalSearchEngine, check_interval: int = 60) -> None:
        self._engine = search_engine
        self._check_interval = check_interval
        self._running = False
        self._watched_dirs: List[str] = []
        self._task: Optional[asyncio.Task[None]] = None

    async def watch(self, directory: str) -> None:
        """Ajoute un dossier a la surveillance."""
        if directory not in self._watched_dirs:
            self._watched_dirs.append(directory)
            logger.info(f"FileWatcher: surveillance de {directory}")

    async def start(self) -> None:
        """Lance la boucle de surveillance."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            f"FileWatcher demarre (intervalle={self._check_interval}s, "
            f"dossiers={len(self._watched_dirs)})"
        )

    async def stop(self) -> None:
        """Arrete la surveillance."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("FileWatcher arrete")

    async def _poll_loop(self) -> None:
        """Boucle de surveillance periodique."""
        while self._running:
            try:
                changed = await self._engine.reindex_changed()
                stale = await self._engine.remove_stale()
                if changed > 0 or stale > 0:
                    logger.info(
                        f"FileWatcher: {changed} re-indexes, {stale} supprimes"
                    )
            except Exception as e:
                logger.error(f"FileWatcher poll error: {e}")
            await asyncio.sleep(self._check_interval)

    @property
    def watched_dirs(self) -> List[str]:
        """Retourne la liste des dossiers surveilles."""
        return list(self._watched_dirs)
