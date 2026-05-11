"""Cache LRU pour les réponses pipeline Beaume v1 (P5).

Clé = SHA1 de (query normalisée | version base Légifrance).
Valeur = n'importe quel objet (typiquement PipelineResponse).

TTL 1h par défaut, capacité 256 entrées (plus ancien évincé).

Invalidation : la clé intègre la mtime de `legi.sqlite`. Un sync
Légifrance change la mtime → clés anciennes inaccessibles (évincées
naturellement au TTL).

Activation (anciens noms `LUCIE_*` acceptés en alias deprecated) :
    BEAUME_CACHE=1 (défaut)        active le cache
    BEAUME_CACHE_DRY_RUN=1         mesure hits/misses sans servir la réponse cachée
    BEAUME_CACHE_MAXSIZE=256       capacité LRU
    BEAUME_CACHE_TTL_SECONDS=3600  TTL des entrées

Pas thread-safe mais coroutine-safe (asyncio.Lock par instance).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from cachetools import TTLCache

from ..config import env_legacy
from ..perf.events import emit

logger = logging.getLogger("lucie.cache")


def cache_enabled() -> bool:
    return env_legacy("CACHE", "1") == "1"


def cache_dry_run_enabled() -> bool:
    return env_legacy("CACHE_DRY_RUN", "0") == "1"


def normalize_query(query: str) -> str:
    """Normalise pour clés stables : NFKD, lower, strip, espaces compressés."""
    norm = unicodedata.normalize("NFKD", query).encode("ascii", "ignore").decode("ascii")
    norm = " ".join(norm.lower().strip().split())
    return norm


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    dry_run_hits: int = 0
    evictions: int = 0

    def as_dict(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "dry_run_hits": self.dry_run_hits,
            "evictions": self.evictions,
            "hit_rate": (
                self.hits / (self.hits + self.misses)
                if (self.hits + self.misses) > 0
                else 0.0
            ),
        }


class QueryCache:
    """Cache TTL + LRU protégé par asyncio.Lock.

    Utilisation :
        cache = QueryCache(maxsize=256, ttl_seconds=3600)
        key = cache.make_key("Délai de préavis", index_version=1234567890)
        resp = await cache.get_or_compute(key, lambda: pipeline.run(q), dry_run=False)
    """

    def __init__(self, maxsize: int = 256, ttl_seconds: int = 3600):
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._lock = asyncio.Lock()
        self.stats = CacheStats()

    def make_key(
        self,
        query: str,
        index_version: int | str = 0,
        theme: Optional[str] = None,
        top_k_ids: Optional[list[str]] = None,
    ) -> str:
        norm = normalize_query(query)
        top_k_part = ",".join(sorted(top_k_ids)) if top_k_ids else "_"
        payload = f"{norm}|{theme or '_'}|{top_k_part}|v{index_version}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    async def get_or_compute(
        self,
        key: str,
        coro_factory: Callable[[], Awaitable[Any]],
        dry_run: bool = False,
    ) -> Any:
        """Retourne la valeur cachée ou l'appelle via coro_factory si miss.

        - En mode normal : hit sert la valeur cachée, miss calcule puis stocke.
        - En mode dry_run : mesure hits/misses mais recalcule **toujours** la valeur
          (utile pour mesurer le taux de hit sans se fier au cache).

        Lock par instance : sur hits concurrents, pas de double compute.
        """
        async with self._lock:
            if key in self._cache:
                cached = self._cache[key]
                if dry_run:
                    self.stats.dry_run_hits += 1
                    logger.debug("cache dry_run HIT key=%s — recompute forcé", key[:12])
                else:
                    self.stats.hits += 1
                    logger.debug("cache HIT key=%s", key[:12])
                    # Signal au HUD : réponse servie en < 5 ms, skip la zone
                    # d'étapes entière (pas de temps de réflexion à afficher).
                    emit("cache", "cached")
                    return cached
            else:
                self.stats.misses += 1
                logger.debug("cache MISS key=%s", key[:12])

        # Calcul hors lock (le coro peut être long)
        value = await coro_factory()

        async with self._lock:
            self._cache[key] = value
        return value

    def clear(self) -> None:
        self._cache.clear()

    def size(self) -> int:
        return len(self._cache)


# Instance singleton process-local
_GLOBAL_CACHE: Optional[QueryCache] = None


def get_query_cache() -> QueryCache:
    """Retourne le singleton global (créé au premier appel)."""
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None:
        maxsize = int(env_legacy("CACHE_MAXSIZE", "256") or "256")
        ttl = int(env_legacy("CACHE_TTL_SECONDS", "3600") or "3600")
        _GLOBAL_CACHE = QueryCache(maxsize=maxsize, ttl_seconds=ttl)
    return _GLOBAL_CACHE
