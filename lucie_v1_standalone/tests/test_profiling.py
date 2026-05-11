"""Tests profiling module (P0)."""

from __future__ import annotations

import asyncio
import os

import pytest

from lucie_v1_standalone.perf import (
    ProfileBucket,
    current_bucket,
    is_profiling_enabled,
    profile_bucket,
    profile_step,
)


@pytest.fixture(autouse=True)
def enable_profiling(monkeypatch):
    monkeypatch.setenv("BEAUME_PROFILE", "1")
    yield


def test_is_profiling_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("BEAUME_PROFILE", "1")
    assert is_profiling_enabled() is True
    monkeypatch.setenv("BEAUME_PROFILE", "0")
    assert is_profiling_enabled() is False


def test_profile_bucket_collects_steps():
    async def run():
        async with profile_bucket() as bucket:
            async with profile_step("step_a"):
                await asyncio.sleep(0.005)
            async with profile_step("step_b"):
                await asyncio.sleep(0.01)
            return bucket

        return None

    bucket = asyncio.run(run())
    assert bucket is not None
    assert len(bucket.steps) == 2
    assert bucket.steps[0].name == "step_a"
    assert bucket.steps[0].duration_ms >= 4.5  # marge tolérante
    assert bucket.steps[1].name == "step_b"
    assert bucket.steps[1].duration_ms >= 9


def test_profile_step_is_noop_without_bucket():
    """Sans `profile_bucket()`, `profile_step` doit être un no-op silencieux."""
    async def run():
        async with profile_step("standalone"):
            await asyncio.sleep(0.001)
        assert current_bucket() is None

    asyncio.run(run())


def test_profile_step_is_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("BEAUME_PROFILE", "0")

    async def run():
        async with profile_bucket() as bucket:
            async with profile_step("ignored"):
                await asyncio.sleep(0.001)
            return bucket

    bucket = asyncio.run(run())
    # bucket None car profilage désactivé → pas de collecte
    assert bucket is None


def test_format_table_produces_markdown():
    bucket = ProfileBucket()
    bucket.add("a", 10.0)
    bucket.add("b", 20.0)
    table = bucket.format_table()
    assert "| Étape" in table
    assert "| a " in table
    assert "| b " in table
    assert "total" in table


def test_meta_fields_in_output():
    bucket = ProfileBucket()
    bucket.add("ollama.gemma", 1500.0, prompt_tokens=120, out_tokens=300)
    table = bucket.format_table()
    assert "prompt_tokens=120" in table
    assert "out_tokens=300" in table
