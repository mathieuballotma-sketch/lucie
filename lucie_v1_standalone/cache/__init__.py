"""Module cache pour Lucie v1 — P5 Perf Phase 1."""

from .query_cache import (
    QueryCache,
    cache_enabled,
    cache_dry_run_enabled,
    get_query_cache,
    normalize_query,
)

__all__ = [
    "QueryCache",
    "cache_enabled",
    "cache_dry_run_enabled",
    "get_query_cache",
    "normalize_query",
]
