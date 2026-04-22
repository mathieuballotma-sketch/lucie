"""Événements temps-réel du pipeline Lucie v1.

Pattern jumeau de `profiling.py` : ContextVar + asyncio.Queue. Les events sont
poussés par les étapes (Lecteur, Retriever, Rédacteur, Vérificateur, cache) et
consommés par `run_stream` qui les yield vers le HUD. Toujours activable — pas
de flag d'env, contrairement au profilage.

Le contenu des events utilise les **noms techniques internes** (stage = "lecteur",
"retriever", etc.). La traduction vers un libellé utilisateur (protection IP +
UX) se fait côté HUD via `lucie_v1_standalone.stage_labels.user_label`.

Usage côté pipeline :
    async with bind_event_queue() as queue:
        async with event_stage("retriever"):
            sources = await retriever.handle(...)
        # -> emit (retriever, started) puis (retriever, completed, duration_ms)

Usage côté consommateur (run_stream) :
    async with bind_event_queue() as queue:
        # ... lancer la pipeline en tâche ...
        while not done:
            ev = queue.get_nowait()  # ou await queue.get()
            yield ev
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Literal, Optional

logger = logging.getLogger("lucie.events")

Stage = Literal[
    "router",
    "lecteur",
    "retriever",
    "redacteur",
    "verificateur",
    "cache",
    "finalizing",
]

Status = Literal["started", "completed", "skipped", "cached", "error"]


@dataclass
class PipelineEvent:
    """Événement émis par une étape du pipeline.

    `stage` utilise le nom technique interne — le HUD le traduit via
    `stage_labels.user_label()` pour l'affichage utilisateur.
    """

    stage: Stage
    status: Status
    message: str = ""
    duration_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


_event_queue: ContextVar[Optional[asyncio.Queue]] = ContextVar(
    "lucie_event_queue", default=None
)


def emit(
    stage: Stage,
    status: Status,
    message: str = "",
    duration_ms: float = 0.0,
    **details: Any,
) -> None:
    """Push un event dans la queue courante. No-op si aucune queue liée.

    Non-bloquant : `put_nowait` avec drop silencieux sur QueueFull. Les events
    sont des indices UI, pas un contrat — mieux vaut perdre un indice que
    bloquer le pipeline.
    """
    q = _event_queue.get()
    if q is None:
        return
    try:
        q.put_nowait(
            PipelineEvent(
                stage=stage,
                status=status,
                message=message,
                duration_ms=duration_ms,
                details=dict(details),
            )
        )
    except asyncio.QueueFull:
        logger.debug("event queue full, dropped %s.%s", stage, status)


@asynccontextmanager
async def event_stage(
    stage: Stage, message: str = "", **details: Any
) -> AsyncIterator[None]:
    """Context manager : émet `started` à l'entrée, `completed` (avec durée) ou
    `error` (avec message d'exception) à la sortie.

    Usage :
        async with event_stage("retriever"):
            sources = await retriever.handle(...)
    """
    emit(stage, "started", message, **details)
    t0 = time.perf_counter()
    try:
        yield
    except Exception as exc:
        dt = (time.perf_counter() - t0) * 1000
        emit(stage, "error", str(exc) or type(exc).__name__, duration_ms=dt, **details)
        raise
    else:
        dt = (time.perf_counter() - t0) * 1000
        emit(stage, "completed", message, duration_ms=dt, **details)


@asynccontextmanager
async def bind_event_queue(
    maxsize: int = 128,
) -> AsyncIterator[asyncio.Queue]:
    """Crée et lie une queue pour la durée du bloc. Réentrant : si une queue
    est déjà liée (ex: appel imbriqué `run_stream` → `run`), on yield celle-là
    pour que les events remontent à l'iterator externe.
    """
    existing = _event_queue.get()
    if existing is not None:
        yield existing
        return
    queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    token = _event_queue.set(queue)
    try:
        yield queue
    finally:
        _event_queue.reset(token)


def current_queue() -> Optional[asyncio.Queue]:
    """Accès direct à la queue courante. Utile pour le drain manuel dans
    `run_stream` (Level 3 en particulier)."""
    return _event_queue.get()


def drain_nowait(queue: asyncio.Queue) -> list:
    """Vide la queue sans bloquer. Retourne la liste des events récupérés."""
    out = []
    while True:
        try:
            out.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return out


__all__ = [
    "PipelineEvent",
    "Stage",
    "Status",
    "emit",
    "event_stage",
    "bind_event_queue",
    "current_queue",
    "drain_nowait",
]
