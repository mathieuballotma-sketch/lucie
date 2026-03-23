"""
AgentScheduler — Ordonnanceur MLFQ (Multi-Level Feedback Queue) pour les agents.

Remplace le sémaphore aveugle threading.Semaphore(3) du manager.py par un
système de priorité intelligent : CRITICAL > NORMAL > BACKGROUND.

Un slot BACKGROUND peut être préempté si une requête CRITICAL attend.
"""

import asyncio
import heapq
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, Dict, List
from ..utils.logger import logger


# ---------------------------------------------------------------------------
# Niveaux de priorité
# ---------------------------------------------------------------------------

class Priority(IntEnum):
    """
    Niveaux de priorité MLFQ.

    Valeur entière plus basse = priorité plus haute (convention heapq).
    """
    CRITICAL = 0    # Requête utilisateur directe — passe toujours en tête
    NORMAL = 1      # Agents secondaires — traitement standard
    BACKGROUND = 2  # DefaultModeNetwork, maintenance — préemptable


# ---------------------------------------------------------------------------
# Ticket de requête
# ---------------------------------------------------------------------------

@dataclass(order=True)
class SchedulerTicket:
    """
    Représente une requête en attente dans la file de priorité.

    Le tri est effectué par (priority, sequence) pour assurer un ordre
    FIFO au sein d'un même niveau de priorité.
    """
    priority: Priority
    sequence: int = field(compare=True)   # numéro d'ordre d'arrivée
    agent_id: str = field(compare=False)
    enqueued_at: float = field(compare=False, default_factory=time.monotonic)
    # Future interne signalée quand le ticket obtient un slot
    _ready: asyncio.Future[bool] = field(compare=False, repr=False, init=False)

    def __post_init__(self) -> None:
        loop = asyncio.get_event_loop()
        self._ready = loop.create_future()


# ---------------------------------------------------------------------------
# AgentScheduler
# ---------------------------------------------------------------------------

class AgentScheduler:
    """
    Ordonnanceur MLFQ asynchrone pour 28 agents.

    Garantit que les requêtes CRITICAL obtiennent un slot avant les requêtes
    NORMAL ou BACKGROUND, et que les slots BACKGROUND peuvent être préemptés
    par une requête CRITICAL en attente.

    Usage typique
    -------------
    scheduler = AgentScheduler(max_slots=3)
    await scheduler.start()

    ticket = await scheduler.acquire("my_agent", Priority.CRITICAL)
    try:
        await do_work()
    finally:
        await scheduler.release(ticket)
    """

    def __init__(self, max_slots: int = 3) -> None:
        """
        Initialise le scheduler.

        Parameters
        ----------
        max_slots:
            Nombre de slots d'exécution simultanés (correspond au degré de
            parallélisme précédemment contrôlé par threading.Semaphore(3)).
        """
        self._max_slots = max_slots

        # File de priorité : heap de (priority, sequence, ticket)
        self._queue: List[SchedulerTicket] = []
        self._sequence: int = 0

        # Slots actuellement occupés : agent_id → ticket
        self._active: Dict[str, SchedulerTicket] = {}

        # Lock de protection pour les structures partagées
        self._lock: asyncio.Lock = asyncio.Lock()

        # Métriques
        self._metrics: Dict[str, _PriorityMetrics] = {
            p.name: _PriorityMetrics() for p in Priority
        }
        self._preemptions: int = 0

        self._running: bool = False

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Démarre le scheduler (idempotent)."""
        self._running = True
        logger.info(f"AgentScheduler démarré — {self._max_slots} slots")

    async def stop(self) -> None:
        """Arrête le scheduler et annule toutes les requêtes en attente."""
        self._running = False
        async with self._lock:
            for ticket in self._queue:
                if not ticket._ready.done():
                    ticket._ready.cancel()
            self._queue.clear()
        logger.info("AgentScheduler arrêté")

    # ------------------------------------------------------------------
    # Interface principale
    # ------------------------------------------------------------------

    async def acquire(self, agent_id: str, priority: Priority = Priority.NORMAL) -> "SchedulerTicket":
        """
        Demande un slot d'exécution avec le niveau de priorité indiqué.

        Bloque jusqu'à ce qu'un slot soit disponible (ou préempté).

        Parameters
        ----------
        agent_id:
            Identifiant unique de l'agent demandeur.
        priority:
            Niveau de priorité de la requête.

        Returns
        -------
        SchedulerTicket
            Le ticket actif — à passer à release() quand le travail est terminé.
        """
        ticket = await self._enqueue(agent_id, priority)
        # Attendre que le ticket soit signalé (le dispatcher l'active)
        await ticket._ready
        return ticket

    async def release(self, ticket: "SchedulerTicket") -> None:
        """
        Libère le slot occupé par ce ticket.

        Parameters
        ----------
        ticket:
            Le ticket retourné par acquire().
        """
        async with self._lock:
            self._active.pop(ticket.agent_id, None)
            duration = time.monotonic() - ticket.enqueued_at
            m = self._metrics[ticket.priority.name]
            m.total_duration += duration
            m.completed += 1
            logger.debug(
                f"[{ticket.priority.name}] slot libéré par {ticket.agent_id} "
                f"(durée totale depuis acquire : {duration:.3f}s)"
            )

        # Dispatcher le prochain ticket en attente
        await self._dispatch()

    # ------------------------------------------------------------------
    # Mécanique interne
    # ------------------------------------------------------------------

    async def _enqueue(self, agent_id: str, priority: Priority) -> SchedulerTicket:
        """Ajoute un ticket dans la file et tente un dispatch immédiat."""
        async with self._lock:
            self._sequence += 1
            ticket = SchedulerTicket(
                priority=priority,
                sequence=self._sequence,
                agent_id=agent_id,
            )
            heapq.heappush(self._queue, ticket)
            m = self._metrics[priority.name]
            m.enqueued += 1
            logger.debug(
                f"[{priority.name}] {agent_id} en file (seq={self._sequence}, "
                f"file={len(self._queue)}, actifs={len(self._active)})"
            )

        # Tenter immédiatement : s'il y a un slot libre ou préemptable
        await self._dispatch()
        return ticket

    async def _dispatch(self) -> None:
        """
        Distribue les slots disponibles aux tickets en tête de file.

        Algorithme MLFQ :
        1. Slot libre disponible → activer le ticket le plus prioritaire.
        2. Tous les slots occupés par BACKGROUND et un ticket CRITICAL attend
           → préempter le BACKGROUND le plus récent.
        """
        async with self._lock:
            self._try_dispatch_locked()

    def _try_dispatch_locked(self) -> None:
        """Logique de dispatch (appelée sous _lock)."""
        while self._queue:
            slots_libres = self._max_slots - len(self._active)

            if slots_libres > 0:
                # Cas 1 : slot libre — activer le ticket le plus prioritaire
                ticket = heapq.heappop(self._queue)
                self._activate(ticket)

            else:
                # Cas 2 : vérifier si préemption possible
                next_ticket = self._queue[0]  # meilleure priorité en attente
                if next_ticket.priority == Priority.CRITICAL:
                    # Chercher un slot BACKGROUND actif à préempter
                    bg_target = self._find_preemptable_background()
                    if bg_target is not None:
                        self._preempt(bg_target)
                        ticket = heapq.heappop(self._queue)
                        self._activate(ticket)
                        continue
                # Pas de slot libre ni de préemption possible → arrêt
                break

    def _activate(self, ticket: SchedulerTicket) -> None:
        """Marque un ticket comme actif et signal sa future."""
        wait_time = time.monotonic() - ticket.enqueued_at
        self._active[ticket.agent_id] = ticket
        m = self._metrics[ticket.priority.name]
        m.total_wait += wait_time
        m.activated += 1
        if not ticket._ready.done():
            ticket._ready.set_result(True)
        logger.debug(
            f"[{ticket.priority.name}] {ticket.agent_id} activé "
            f"(attente : {wait_time:.3f}s)"
        )

    def _find_preemptable_background(self) -> Optional[SchedulerTicket]:
        """
        Retourne le ticket BACKGROUND actif le plus récent (dernier entré),
        candidat à la préemption.
        """
        bg_tickets = [
            t for t in self._active.values()
            if t.priority == Priority.BACKGROUND
        ]
        if not bg_tickets:
            return None
        # Préempter le plus récent (sequence la plus haute)
        return max(bg_tickets, key=lambda t: t.sequence)

    def _preempt(self, ticket: SchedulerTicket) -> None:
        """
        Préempte un ticket actif BACKGROUND.

        Le ticket retourne en file de priorité pour être réactivé ensuite.
        Note : l'agent concerné n'est PAS interrompu de force — la préemption
        est coopérative. L'agent doit surveiller son ticket ou une Future de
        cancel injectée par l'appelant (extensible).
        """
        self._active.pop(ticket.agent_id, None)
        # Remettre en file avec le même sequence pour conserver l'ordre relatif
        heapq.heappush(self._queue, ticket)
        self._preemptions += 1
        m = self._metrics[ticket.priority.name]
        m.preempted += 1
        logger.warning(
            f"[PREEMPTION] {ticket.agent_id} (BACKGROUND) préempté "
            f"au profit d'un CRITICAL (total préemptions : {self._preemptions})"
        )

    # ------------------------------------------------------------------
    # Métriques
    # ------------------------------------------------------------------

    def get_metrics(self) -> Dict[str, object]:
        """
        Retourne les métriques de performance du scheduler.

        Returns
        -------
        dict
            {
              "preemptions": int,
              "CRITICAL": {"enqueued": int, "activated": int, "avg_wait_s": float, ...},
              "NORMAL":   {...},
              "BACKGROUND": {...},
            }
        """
        result: Dict[str, object] = {"preemptions": self._preemptions}
        for name, m in self._metrics.items():
            result[name] = {
                "enqueued": m.enqueued,
                "activated": m.activated,
                "completed": m.completed,
                "preempted": m.preempted,
                "avg_wait_s": (m.total_wait / m.activated) if m.activated else 0.0,
                "avg_duration_s": (m.total_duration / m.completed) if m.completed else 0.0,
            }
        return result

    def log_metrics(self) -> None:
        """Affiche un résumé des métriques dans le logger."""
        metrics = self.get_metrics()
        logger.info(f"AgentScheduler métriques : {metrics}")


# ---------------------------------------------------------------------------
# Métriques internes par niveau de priorité
# ---------------------------------------------------------------------------

class _PriorityMetrics:
    """Compteurs internes — non exposés directement."""

    __slots__ = (
        "enqueued", "activated", "completed", "preempted",
        "total_wait", "total_duration",
    )

    def __init__(self) -> None:
        self.enqueued: int = 0
        self.activated: int = 0
        self.completed: int = 0
        self.preempted: int = 0
        self.total_wait: float = 0.0
        self.total_duration: float = 0.0
