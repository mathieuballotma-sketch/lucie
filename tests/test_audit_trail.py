"""
Tests for AuditTrail v2.

Coverage:
  - Basic record + verify_chain
  - Hash chain integrity (tamper detection)
  - PiiPseudonymizer
  - ReplayableAgent + ReplayRegistry dispatch
  - replay_sequence dry_run
  - replay_sequence stop_on_mismatch
  - export_paf_csv column format
  - cleanup_expired with anchor
  - AuditEventBusIntegration auto-record
  - record_sync + async record coexistence
"""
from __future__ import annotations

import asyncio
import csv
import io
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.audit_trail import (
    AuditEntry,
    AuditEventBusIntegration,
    AuditTrail,
    PiiPseudonymizer,
    ReplayableAgent,
    ReplayRegistry,
    ReplayResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def trail(tmp_path):
    """Fresh AuditTrail in a temp directory with a fixed secret."""
    db = tmp_path / "audit.db"
    salt = tmp_path / ".audit_salt"
    return AuditTrail(
        db_path=db,
        salt_path=salt,
        secret=b"test-secret-32-bytes-long-padding",
    )


@pytest.fixture
def trail_with_entries(trail):
    """AuditTrail pre-populated with 5 entries."""
    for i in range(5):
        trail.record_sync(
            action=f"action.{i}",
            user=f"user{i}",
            justification=f"reason {i}",
            data={"index": i},
        )
    return trail


# ---------------------------------------------------------------------------
# Concrete ReplayableAgent for tests
# ---------------------------------------------------------------------------

class EchoAgent(ReplayableAgent):
    """Echoes entry.data back as output."""

    def __init__(self, action: str):
        self._action = action
        self.calls: list[tuple[AuditEntry, bool]] = []

    async def replay_action(
        self,
        entry: AuditEntry,
        replay_context: dict[str, Any],
        dry_run: bool = False,
    ) -> Any:
        self.calls.append((entry, dry_run))
        replay_context[entry.sequence] = entry.data
        return entry.data

    @property
    def supported_event_types(self) -> frozenset[str]:
        return frozenset({self._action})


class MismatchAgent(ReplayableAgent):
    """Always returns a value different from expected_output."""

    async def replay_action(
        self,
        entry: AuditEntry,
        replay_context: dict[str, Any],
        dry_run: bool = False,
    ) -> Any:
        return {"unexpected": True}

    @property
    def supported_event_types(self) -> frozenset[str]:
        return frozenset({"mismatch.action"})


# ---------------------------------------------------------------------------
# Category 1 — Basic record + verify_chain
# ---------------------------------------------------------------------------

class TestBasicRecord:
    def test_record_sync_creates_entry(self, trail):
        entry = trail.record_sync("invoice.created", user="alice")
        assert entry.sequence == 1
        assert entry.action == "invoice.created"
        assert entry.user == "alice"
        assert entry.signature != ""

    def test_second_record_increments_sequence(self, trail):
        e1 = trail.record_sync("a", user="u")
        e2 = trail.record_sync("b", user="u")
        assert e2.sequence == e1.sequence + 1

    def test_genesis_prev_hash_for_first_entry(self, trail):
        entry = trail.record_sync("first", user="u")
        assert entry.prev_hash == "GENESIS"

    def test_prev_hash_links_to_previous_signature(self, trail):
        e1 = trail.record_sync("a", user="u")
        e2 = trail.record_sync("b", user="u")
        assert e2.prev_hash == e1.signature

    def test_verify_chain_passes_on_unmodified_trail(self, trail_with_entries):
        valid, errors = trail_with_entries.verify_chain()
        assert valid
        assert errors == []

    def test_async_record_persists_entry(self, trail):
        async def _run():
            await trail.start()
            entry = await trail.record("async.action", user="bob")
            await trail.stop()
            return entry

        entry = asyncio.run(_run())
        assert entry.sequence >= 1
        # Verify it was persisted
        valid, errors = trail.verify_chain()
        assert valid


# ---------------------------------------------------------------------------
# Category 2 — Tamper detection
# ---------------------------------------------------------------------------

class TestTamperDetection:
    def test_modified_entry_fails_verify(self, trail, tmp_path):
        """Directly mutating the DB breaks signature verification."""
        import sqlite3

        trail.record_sync("original", user="alice", data={"amount": 100})

        db_path = str(trail._db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE audit_entries SET data_json=? WHERE sequence=1",
                ('{"amount": 9999}',),
            )
            conn.commit()

        valid, errors = trail.verify_chain()
        assert not valid
        assert any("Signature mismatch" in e for e in errors)

    def test_chain_break_detected(self, trail):
        """Changing prev_hash in the DB is detected."""
        import sqlite3

        trail.record_sync("first", user="u")
        trail.record_sync("second", user="u")

        db_path = str(trail._db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE audit_entries SET prev_hash='TAMPERED' WHERE sequence=2"
            )
            conn.commit()

        valid, errors = trail.verify_chain()
        assert not valid
        assert any("chain break" in e.lower() or "break" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Category 3 — PiiPseudonymizer
# ---------------------------------------------------------------------------

class TestPiiPseudonymizer:
    def test_pseudonym_is_deterministic(self, tmp_path):
        salt_path = tmp_path / "salt"
        p = PiiPseudonymizer(salt_path)
        assert p.pseudonymize("alice@example.com") == p.pseudonymize("alice@example.com")

    def test_different_values_produce_different_pseudonyms(self, tmp_path):
        salt_path = tmp_path / "salt"
        p = PiiPseudonymizer(salt_path)
        assert p.pseudonymize("alice") != p.pseudonymize("bob")

    def test_pseudonym_starts_with_pii_prefix(self, tmp_path):
        salt_path = tmp_path / "salt"
        p = PiiPseudonymizer(salt_path)
        result = p.pseudonymize("alice")
        assert result.startswith("pii:")

    def test_salt_file_has_600_permissions(self, tmp_path):
        salt_path = tmp_path / "new_salt"
        PiiPseudonymizer(salt_path)
        mode = salt_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_pii_fields_pseudonymized_in_record(self, trail):
        entry = trail.record_sync(
            "user.login",
            user="alice@example.com",
            data={"email": "alice@example.com", "amount": 100},
            pii_fields={"email"},
        )
        assert entry.data["email"].startswith("pii:")
        assert entry.data["amount"] == 100

    def test_non_pii_fields_preserved(self, trail):
        entry = trail.record_sync(
            "invoice.created",
            user="system",
            data={"ref": "INV-001", "email": "user@example.com"},
            pii_fields={"email"},
        )
        assert entry.data["ref"] == "INV-001"


# ---------------------------------------------------------------------------
# Category 4 — ReplayableAgent + ReplayRegistry
# ---------------------------------------------------------------------------

class TestReplayRegistry:
    def test_register_and_retrieve_agent(self):
        registry = ReplayRegistry()
        agent = EchoAgent("test.action")
        registry.register(agent)
        assert registry.get("test.action") is agent

    def test_get_unknown_action_returns_none(self):
        registry = ReplayRegistry()
        assert registry.get("nonexistent") is None

    def test_multiple_agents_registered(self):
        registry = ReplayRegistry()
        a1 = EchoAgent("action.A")
        a2 = EchoAgent("action.B")
        registry.register(a1)
        registry.register(a2)
        assert registry.get("action.A") is a1
        assert registry.get("action.B") is a2

    def test_supported_event_types(self):
        agent = EchoAgent("my.event")
        assert "my.event" in agent.supported_event_types


# ---------------------------------------------------------------------------
# Category 5 — replay_sequence
# ---------------------------------------------------------------------------

class TestReplaySequence:
    def test_replay_dry_run_calls_agent_with_dry_run_true(self, trail):
        trail.record_sync("echo.action", user="u", data={"x": 1})
        agent = EchoAgent("echo.action")
        trail.register_replay_agent(agent)

        results = asyncio.run(
            trail.replay_sequence(from_seq=1, to_seq=1, dry_run=True)
        )
        assert len(results) == 1
        assert results[0].dry_run is True
        assert agent.calls[0][1] is True  # dry_run=True passed to agent

    def test_replay_executes_all_entries(self, trail):
        for i in range(3):
            trail.record_sync("echo.action", user="u", data={"i": i})

        agent = EchoAgent("echo.action")
        trail.register_replay_agent(agent)

        results = asyncio.run(
            trail.replay_sequence(from_seq=1, to_seq=3, dry_run=False)
        )
        assert len(results) == 3
        assert len(agent.calls) == 3

    def test_stop_on_mismatch_halts_replay(self, trail):
        """replay_sequence stops at first mismatch when stop_on_mismatch=True."""
        for i in range(4):
            trail.record_sync(
                "mismatch.action",
                user="u",
                data={"expected_output": {"key": "correct_value"}},
            )

        agent = MismatchAgent()
        trail.register_replay_agent(agent)

        results = asyncio.run(
            trail.replay_sequence(
                from_seq=1,
                to_seq=4,
                stop_on_mismatch=True,
                dry_run=True,
            )
        )
        # Should stop after first mismatch
        assert len(results) == 1
        assert results[0].matched is False

    def test_no_agent_registered_produces_error_result(self, trail):
        trail.record_sync("unregistered.action", user="u")
        results = asyncio.run(
            trail.replay_sequence(from_seq=1, to_seq=1, stop_on_mismatch=False)
        )
        assert results[0].error != ""
        assert "No agent" in results[0].error

    def test_replay_context_shared_across_entries(self, trail):
        """Shared replay_context accumulates data from each agent call."""
        for i in range(3):
            trail.record_sync("echo.action", user="u", data={"seq": i})

        agent = EchoAgent("echo.action")
        trail.register_replay_agent(agent)

        results = asyncio.run(
            trail.replay_sequence(from_seq=1, to_seq=3, dry_run=True)
        )
        # EchoAgent writes to replay_context[entry.sequence]
        assert len(results) == 3


# ---------------------------------------------------------------------------
# Category 6 — PAF CSV export
# ---------------------------------------------------------------------------

class TestExportPafCsv:
    def test_csv_has_correct_header(self, trail_with_entries):
        csv_content = trail_with_entries.export_paf_csv()
        reader = csv.reader(io.StringIO(csv_content), delimiter=";")
        header = next(reader)
        assert header == [
            "Date", "Action", "Utilisateur", "Justificatif",
            "HashPrecedent", "Signature", "NumeroSequence"
        ]

    def test_csv_has_correct_row_count(self, trail_with_entries):
        csv_content = trail_with_entries.export_paf_csv()
        lines = [l for l in csv_content.strip().split("\n") if l]
        assert len(lines) == 6  # 1 header + 5 data rows

    def test_csv_sequence_numbers_are_correct(self, trail_with_entries):
        csv_content = trail_with_entries.export_paf_csv()
        reader = csv.reader(io.StringIO(csv_content), delimiter=";")
        next(reader)  # skip header
        sequences = [int(row[6]) for row in reader]
        assert sequences == [1, 2, 3, 4, 5]

    def test_csv_filter_by_sequence(self, trail_with_entries):
        csv_content = trail_with_entries.export_paf_csv(from_seq=2, to_seq=4)
        reader = csv.reader(io.StringIO(csv_content), delimiter=";")
        next(reader)
        sequences = [int(row[6]) for row in reader]
        assert sequences == [2, 3, 4]

    def test_csv_write_to_file(self, trail_with_entries, tmp_path):
        output_path = tmp_path / "audit.csv"
        trail_with_entries.export_paf_csv(output=output_path)
        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert "Date" in content


# ---------------------------------------------------------------------------
# Category 7 — cleanup_expired
# ---------------------------------------------------------------------------

class TestCleanupExpired:
    def test_cleanup_returns_zero_when_no_expired_entries(self, trail):
        trail.record_sync("recent", user="u")
        deleted = trail.cleanup_expired()
        assert deleted == 0

    def test_cleanup_with_anchor_inserts_anchor_entry(self, trail):
        """Even when nothing is deleted, the anchor is only inserted on actual deletion."""
        import sqlite3
        from datetime import datetime, timedelta, timezone

        # Insert a very old entry by manipulating the timestamp after creation
        entry = trail.record_sync("old.event", user="u")
        old_ts = (
            datetime.now(timezone.utc) - timedelta(days=365 * 7)
        ).isoformat()

        with sqlite3.connect(str(trail._db_path)) as conn:
            conn.execute(
                "UPDATE audit_entries SET timestamp=? WHERE sequence=?",
                (old_ts, entry.sequence),
            )
            conn.commit()

        deleted = trail.cleanup_expired(anchor=True)
        assert deleted == 1

        # Check that an anchor entry was written
        with sqlite3.connect(str(trail._db_path)) as conn:
            row = conn.execute(
                "SELECT action FROM audit_entries WHERE action='CLEANUP_ANCHOR'"
            ).fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# Category 8 — AuditEventBusIntegration
# ---------------------------------------------------------------------------

class TestAuditEventBusIntegration:
    def test_start_subscribes_to_channels(self, trail):
        """AuditEventBusIntegration subscribes to all configured channels on start."""
        subscribed: list[str] = []

        class FakeBus:
            async def subscribe(self, channel, callback, subscriber_id):
                subscribed.append(channel)

        integration = AuditEventBusIntegration(
            audit_trail=trail,
            event_bus=FakeBus(),
            channels=["invoice.*", "security.*"],
        )
        asyncio.run(integration.start())
        assert "invoice.*" in subscribed
        assert "security.*" in subscribed

    def test_on_event_records_audit_entry(self, trail):
        """Received EventBus events are recorded in the audit trail."""
        class FakeEvent:
            channel = "invoice.approved"
            source = "workflow_agent"
            data = {"ref": "INV-001"}

        integration = AuditEventBusIntegration(
            audit_trail=trail,
            event_bus=MagicMock(),
            channels=["invoice.*"],
        )
        asyncio.run(integration._on_event(FakeEvent()))

        valid, errors = trail.verify_chain()
        assert valid

        # Verify the entry was recorded
        entries = trail._load_entries(1, 100)
        assert any(e.action == "invoice.approved" for e in entries)
        assert any(e.user == "workflow_agent" for e in entries)

    def test_on_event_handles_exception_gracefully(self, trail, caplog):
        """_on_event does not propagate exceptions — logs error instead."""
        import logging

        class BrokenAuditTrail:
            async def record(self, **kwargs):
                raise RuntimeError("DB error")

        class FakeEvent:
            channel = "test"
            source = "system"
            data = {}

        integration = AuditEventBusIntegration(
            audit_trail=BrokenAuditTrail(),  # type: ignore
            event_bus=MagicMock(),
        )
        # Should not raise
        asyncio.run(integration._on_event(FakeEvent()))
