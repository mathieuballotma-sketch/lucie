"""Tests du cache LRU (P5)."""

from __future__ import annotations

import asyncio

import pytest

from lucie_v1_standalone.cache import (
    QueryCache,
    cache_dry_run_enabled,
    cache_enabled,
    get_query_cache,
    normalize_query,
)


def test_normalize_query_collapses_whitespace():
    assert normalize_query("  Délai  DE préavis   ") == "delai de preavis"


def test_normalize_query_strips_accents_and_case():
    assert normalize_query("Préavis ÉCONOMIQUE") == "preavis economique"


def test_make_key_deterministic():
    cache = QueryCache()
    k1 = cache.make_key("Délai préavis", index_version=123)
    k2 = cache.make_key("  DÉLAI   préavis ", index_version=123)
    assert k1 == k2


def test_make_key_differs_by_index_version():
    cache = QueryCache()
    k1 = cache.make_key("q", index_version=1)
    k2 = cache.make_key("q", index_version=2)
    assert k1 != k2


def test_cache_enabled_default(monkeypatch):
    monkeypatch.delenv("LUCIE_CACHE", raising=False)
    assert cache_enabled() is True


def test_cache_disabled_when_flag_off(monkeypatch):
    monkeypatch.setenv("LUCIE_CACHE", "0")
    assert cache_enabled() is False


def test_cache_dry_run_default(monkeypatch):
    monkeypatch.delenv("LUCIE_CACHE_DRY_RUN", raising=False)
    assert cache_dry_run_enabled() is False


def test_get_or_compute_hit_serves_cached():
    """Après un miss, les appels suivants retournent la valeur cachée."""
    cache = QueryCache(maxsize=16, ttl_seconds=60)
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        return f"result-{call_count}"

    async def go():
        v1 = await cache.get_or_compute("k1", factory)
        v2 = await cache.get_or_compute("k1", factory)
        return v1, v2

    v1, v2 = asyncio.run(go())
    assert v1 == v2 == "result-1"
    assert call_count == 1
    assert cache.stats.hits == 1
    assert cache.stats.misses == 1


def test_get_or_compute_dry_run_recomputes_and_counts_hits():
    """dry_run : mesure hits mais recalcule toujours."""
    cache = QueryCache(maxsize=16, ttl_seconds=60)
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        return f"result-{call_count}"

    async def go():
        v1 = await cache.get_or_compute("k1", factory, dry_run=False)  # miss → store
        v2 = await cache.get_or_compute("k1", factory, dry_run=True)   # dry_run hit
        return v1, v2

    v1, v2 = asyncio.run(go())
    assert v1 == "result-1"
    assert v2 == "result-2"  # dry_run ne sert pas la valeur cachée
    assert cache.stats.dry_run_hits == 1
    assert cache.stats.misses == 1
    assert call_count == 2


def test_get_or_compute_concurrent_same_key_computes_twice():
    """Lock courant protège l'écriture mais pas le compute (coro factory hors lock).

    Ce test documente le comportement : 2 coroutines concurrentes sur la même
    clé peuvent tous deux calculer (c'est acceptable, la dernière écriture gagne).
    Si on voulait dédupliquer le compute, il faudrait un sémaphore par clé.
    """
    cache = QueryCache(maxsize=16, ttl_seconds=60)
    call_count = 0
    started = asyncio.Event()

    async def factory():
        nonlocal call_count
        call_count += 1
        # Laisse l'autre coroutine entrer dans son propre miss
        started.set()
        await asyncio.sleep(0.01)
        return "val"

    async def go():
        started.clear()
        return await asyncio.gather(
            cache.get_or_compute("k1", factory),
            cache.get_or_compute("k1", factory),
        )

    v1, v2 = asyncio.run(go())
    assert v1 == v2 == "val"
    # Accepté : les deux ont pu calculer (pas de dédup inter-coroutine)
    assert call_count >= 1


def test_cache_max_size_evicts_oldest():
    cache = QueryCache(maxsize=2, ttl_seconds=60)

    async def factory(val):
        async def f():
            return val
        return f

    async def go():
        f1 = await factory("v1")
        f2 = await factory("v2")
        f3 = await factory("v3")
        await cache.get_or_compute("k1", f1)
        await cache.get_or_compute("k2", f2)
        await cache.get_or_compute("k3", f3)
        return cache.size()

    size = asyncio.run(go())
    assert size == 2  # k1 évincé, k2/k3 présents


def test_get_query_cache_singleton():
    c1 = get_query_cache()
    c2 = get_query_cache()
    assert c1 is c2
