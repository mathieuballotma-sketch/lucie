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
import uuid
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
    "cerveau_oiseau",
]

Status = Literal["started", "completed", "skipped", "cached", "error"]


def _new_event_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class PipelineEvent:
    """Événement émis par une étape du pipeline.

    `stage` utilise le nom technique interne — le HUD le traduit via
    `stage_labels.user_label()` pour l'affichage utilisateur.

    `event_id`, `parent_id`, `hook_name` sont ajoutés en Phase 1ter pour
    matérialiser un arbre d'exécution (parent → enfants) dont la Phase 2 Perf
    (parallélisation) se servira. Pour les events racine, `parent_id=None`.
    """

    stage: Stage
    status: Status
    message: str = ""
    duration_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=_new_event_id)
    parent_id: Optional[str] = None
    hook_name: Optional[str] = None


_event_queue: ContextVar[Optional[asyncio.Queue]] = ContextVar(
    "lucie_event_queue", default=None
)

# Contexte parent courant — set par `event_stage` pendant son `yield`. Lu par
# `emit()` et `child_event_stage()` pour propager le lien parent/enfant sans
# passer l'ID explicitement à chaque appel. ContextVar = compatible asyncio.Task.
_current_parent_id: ContextVar[Optional[str]] = ContextVar(
    "lucie_current_parent_id", default=None
)
_current_parent_stage: ContextVar[Optional[Stage]] = ContextVar(
    "lucie_current_parent_stage", default=None
)


def emit(
    stage: Stage,
    status: Status,
    message: str = "",
    duration_ms: float = 0.0,
    *,
    event_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    hook_name: Optional[str] = None,
    **details: Any,
) -> Optional[str]:
    """Push un event dans la queue courante. No-op si aucune queue liée.

    Non-bloquant : `put_nowait` avec drop silencieux sur QueueFull. Les events
    sont des indices UI, pas un contrat — mieux vaut perdre un indice que
    bloquer le pipeline.

    Retourne l'`event_id` de l'event émis (utile pour s'en servir comme
    parent_id d'enfants émis manuellement).
    """
    q = _event_queue.get()
    if q is None:
        return None
    eid = event_id or _new_event_id()
    # Si parent_id n'est pas explicitement fourni, on hérite du contexte courant.
    pid = parent_id if parent_id is not None else _current_parent_id.get()
    try:
        q.put_nowait(
            PipelineEvent(
                stage=stage,
                status=status,
                message=message,
                duration_ms=duration_ms,
                details=dict(details),
                event_id=eid,
                parent_id=pid,
                hook_name=hook_name,
            )
        )
    except asyncio.QueueFull:
        logger.debug("event queue full, dropped %s.%s", stage, status)
    return eid


@asynccontextmanager
async def event_stage(
    stage: Stage, message: str = "", **details: Any
) -> AsyncIterator[None]:
    """Context manager : émet `started` à l'entrée, `completed` (avec durée) ou
    `error` (avec message d'exception) à la sortie.

    Pendant le `yield`, set `_current_parent_id` avec l'event_id de l'event
    `started` — les enfants (`child_event_stage`, `emit` sans parent_id) qui
    s'émettent dans le bloc hériteront automatiquement du parent.

    Usage :
        async with event_stage("retriever"):
            sources = await retriever.handle(...)
    """
    eid = _new_event_id()
    emit(stage, "started", message, event_id=eid, **details)
    t0 = time.perf_counter()
    token_pid = _current_parent_id.set(eid)
    token_stage = _current_parent_stage.set(stage)
    try:
        yield
    except Exception as exc:
        dt = (time.perf_counter() - t0) * 1000
        _current_parent_id.reset(token_pid)
        _current_parent_stage.reset(token_stage)
        emit(
            stage,
            "error",
            str(exc) or type(exc).__name__,
            duration_ms=dt,
            **details,
        )
        raise
    else:
        dt = (time.perf_counter() - t0) * 1000
        _current_parent_id.reset(token_pid)
        _current_parent_stage.reset(token_stage)
        emit(
            stage,
            "completed",
            message,
            duration_ms=dt,
            event_id=eid,
            **details,
        )


@asynccontextmanager
async def child_event_stage(
    hook_name: str,
    stage: Optional[Stage] = None,
    message: str = "",
    **details: Any,
) -> AsyncIterator[None]:
    """Context manager pour une sous-action à l'intérieur d'un `event_stage`.

    - `hook_name` identifie l'action (« lit_article », « verifie_citation »).
    - `stage` hérite du stage parent courant si non fourni — un sous-event d'un
      retriever a `stage="retriever"`.
    - `parent_id` hérité automatiquement de la ContextVar courante.

    Usage :
        async with event_stage("retriever"):
            for ref in refs:
                async with child_event_stage("lit_article", article=ref):
                    ...
    """
    resolved_stage: Stage
    if stage is not None:
        resolved_stage = stage
    else:
        parent_stage = _current_parent_stage.get()
        resolved_stage = parent_stage if parent_stage is not None else "retriever"

    eid = _new_event_id()
    emit(
        resolved_stage,
        "started",
        message,
        event_id=eid,
        hook_name=hook_name,
        **details,
    )
    t0 = time.perf_counter()
    # Le sous-event devient lui-même parent des éventuels petits-enfants.
    token_pid = _current_parent_id.set(eid)
    token_stage = _current_parent_stage.set(resolved_stage)
    try:
        yield
    except Exception as exc:
        dt = (time.perf_counter() - t0) * 1000
        _current_parent_id.reset(token_pid)
        _current_parent_stage.reset(token_stage)
        emit(
            resolved_stage,
            "error",
            str(exc) or type(exc).__name__,
            duration_ms=dt,
            hook_name=hook_name,
            **details,
        )
        raise
    else:
        dt = (time.perf_counter() - t0) * 1000
        _current_parent_id.reset(token_pid)
        _current_parent_stage.reset(token_stage)
        emit(
            resolved_stage,
            "completed",
            message,
            duration_ms=dt,
            event_id=eid,
            hook_name=hook_name,
            **details,
        )


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
    "child_event_stage",
    "bind_event_queue",
    "current_queue",
    "drain_nowait",
]
