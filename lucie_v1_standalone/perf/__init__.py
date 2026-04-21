"""Perf utilities : profilage, instrumentation, bench harness.

Tout le code de ce sous-paquet est activable via env flags (`LUCIE_PROFILE=1`).
Aucun impact runtime quand désactivé (no-op).
"""

from .profiling import (
    ProfileBucket,
    ProfileStep,
    current_bucket,
    is_profiling_enabled,
    profile_bucket,
    profile_step,
)

__all__ = [
    "ProfileBucket",
    "ProfileStep",
    "current_bucket",
    "is_profiling_enabled",
    "profile_bucket",
    "profile_step",
]
