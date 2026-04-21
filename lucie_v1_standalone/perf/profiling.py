"""Profilage du pipeline Lucie v1.

Instrumentation par context manager async + ContextVar — aucun code appelant
ne passe le bucket explicitement. Activé via `LUCIE_PROFILE=1`, no-op sinon.

Usage :
    async with profile_bucket() as bucket:
        async with profile_step("retriever"):
            ...
        async with profile_step("redacteur"):
            ...
    print(bucket.format_table())
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Optional

logger = logging.getLogger("lucie.profiling")


def is_profiling_enabled() -> bool:
    return os.environ.get("LUCIE_PROFILE", "0") == "1"


@dataclass
class ProfileStep:
    name: str
    duration_ms: float
    meta: dict = field(default_factory=dict)


@dataclass
class ProfileBucket:
    steps: List[ProfileStep] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)

    def add(self, name: str, duration_ms: float, **meta) -> None:
        self.steps.append(ProfileStep(name=name, duration_ms=duration_ms, meta=meta))

    def total_ms(self) -> float:
        return (time.perf_counter() - self.started_at) * 1000

    def format_table(self) -> str:
        """Retourne un tableau Markdown des étapes mesurées."""
        if not self.steps:
            return "(profilage vide)"
        total = self.total_ms() or 1.0
        lines = [
            "| Étape | Durée (ms) | % total |",
            "|---|---:|---:|",
        ]
        for s in self.steps:
            pct = 100.0 * s.duration_ms / total
            meta_str = ""
            if s.meta:
                kvs = ", ".join(f"{k}={v}" for k, v in s.meta.items())
                meta_str = f" _{kvs}_"
            lines.append(f"| {s.name}{meta_str} | {s.duration_ms:.1f} | {pct:.1f}% |")
        lines.append(f"| **total** | **{total:.1f}** | 100% |")
        return "\n".join(lines)


_current_bucket: ContextVar[Optional[ProfileBucket]] = ContextVar(
    "lucie_profile_bucket", default=None
)


@asynccontextmanager
async def profile_bucket() -> AsyncIterator[Optional[ProfileBucket]]:
    """Crée un bucket pour la durée du bloc. No-op si profilage désactivé.

    Réentrant : si un bucket est déjà actif (ex: harness de bench qui englobe
    l'appel pipeline), on yield celui-là plutôt que d'en créer un nouveau.
    Évite les buckets emboîtés qui perdent les steps internes.
    """
    if not is_profiling_enabled():
        yield None
        return
    existing = _current_bucket.get()
    if existing is not None:
        yield existing
        return
    bucket = ProfileBucket()
    token = _current_bucket.set(bucket)
    try:
        yield bucket
    finally:
        _current_bucket.reset(token)
        if bucket.steps:
            logger.info("profilage pipeline:\n%s", bucket.format_table())


@asynccontextmanager
async def profile_step(name: str, **meta) -> AsyncIterator[None]:
    """Mesure la durée du bloc et l'ajoute au bucket courant.

    No-op si profilage désactivé OU aucun bucket actif — pas de coût runtime.
    """
    bucket = _current_bucket.get()
    if bucket is None:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000
        bucket.add(name, dt_ms, **meta)


def current_bucket() -> Optional[ProfileBucket]:
    """Accès direct au bucket pour instrumentation custom (ex: ollama_client)."""
    return _current_bucket.get()
