"""Perf utilities : profilage, instrumentation, bench harness.

Tout le code de ce sous-paquet est activable via env flags (`BEAUME_PROFILE=1`,
ancien `LUCIE_PROFILE` accepté en alias deprecated).
Aucun impact runtime quand désactivé (no-op).
"""

from .events import (
    PipelineEvent,
    bind_event_queue,
    current_queue,
    drain_nowait,
    emit,
    event_stage,
)
from .profiling import (
    ProfileBucket,
    ProfileStep,
    current_bucket,
    is_profiling_enabled,
    profile_bucket,
    profile_step,
)

__all__ = [
    "PipelineEvent",
    "ProfileBucket",
    "ProfileStep",
    "bind_event_queue",
    "current_bucket",
    "current_queue",
    "drain_nowait",
    "emit",
    "event_stage",
    "is_profiling_enabled",
    "profile_bucket",
    "profile_step",
]
