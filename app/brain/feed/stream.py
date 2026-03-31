"""
ThoughtStream — Ring buffer thread-safe pour le flux de pensées.
Capacité fixe, O(1) insertion, itération sans copie via index.
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional

from .models import ThoughtEntry, ThoughtPriority


class ThoughtStream:
    """
    Ring buffer lock-free en lecture (snapshot via _version),
    verrou uniquement en écriture.

    Capacité : 200 entrées (suffisant pour ~5 min d'activité intense).
    Au-delà, les plus anciennes sont écrasées.
    """

    def __init__(self, capacity: int = 200) -> None:
        self._capacity = capacity
        self._buffer: List[Optional[ThoughtEntry]] = [None] * capacity
        self._write_idx: int = 0
        self._count: int = 0
        self._version: int = 0
        self._lock = threading.Lock()
        self._listeners: List[Callable[[ThoughtEntry], None]] = []

    def push(self, entry: ThoughtEntry) -> None:
        """
        Ajoute une pensée au stream. O(1).
        Thread-safe via verrou court (pas de I/O dans le lock).
        """
        with self._lock:
            self._buffer[self._write_idx] = entry
            self._write_idx = (self._write_idx + 1) % self._capacity
            self._count += 1
            self._version += 1

        # Notification hors du lock
        for listener in self._listeners:
            try:
                listener(entry)
            except Exception:
                pass

    def snapshot(self, limit: int = 50,
                 min_priority: ThoughtPriority = ThoughtPriority.MURMUR
                 ) -> List[ThoughtEntry]:
        """
        Retourne les N dernières entrées filtrées par priorité.
        Lecture sans verrou — cohérence éventuelle acceptable pour l'UI.
        """
        result: List[ThoughtEntry] = []
        idx = (self._write_idx - 1) % self._capacity
        seen = 0
        max_scan = min(self._count, self._capacity)

        while seen < max_scan and len(result) < limit:
            entry = self._buffer[idx]
            if entry is not None and entry.priority.value >= min_priority.value:
                result.append(entry)
            idx = (idx - 1) % self._capacity
            seen += 1

        result.reverse()
        return result

    def add_listener(self, callback: Callable[[ThoughtEntry], None]) -> None:
        """Enregistre un callback appelé à chaque nouvelle pensée."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[ThoughtEntry], None]) -> None:
        """Retire un listener."""
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    @property
    def version(self) -> int:
        return self._version

    @property
    def count(self) -> int:
        return self._count

    @property
    def size(self) -> int:
        """Nombre d'entrées actuellement dans le buffer."""
        return min(self._count, self._capacity)
