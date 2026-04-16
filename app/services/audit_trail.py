"""
AuditTrail v2 — Production-ready tamper-evident audit trail.

Features:
  - HMAC hash chain: each entry signs (sequence + timestamp + action + prev_hash + data)
  - PiiPseudonymizer: HMAC-SHA256 with per-installation salt file (chmod 600)
  - Async writing: asyncio.Queue + _writer_loop (non-blocking record())
  - Synchronous fallback: record_sync() for critical events
  - ReplayableAgent ABC + ReplayRegistry for event-driven replay
  - replay_sequence with shared replay_context, stop_on_mismatch, dry_run
  - export_paf_csv(): PAF format (Date;Action;Utilisateur;Justificatif;HashPrecedent;Signature;NumeroSequence)
  - cleanup_expired(): 6-year retention with anchor hash
  - AuditEventBusIntegration: auto-record EventBus events

Usage:
    trail = AuditTrail(db_path="audit.db")
    await trail.start()
    entry = await trail.record("invoice.approved", user="alice", justification="QC passed")
    await trail.stop()
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac as _hmac
import io
import json
import logging
import os
import secrets
import sqlite3
import threading
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_AUDIT_SECRET_ENV = "AUDIT_HMAC_SECRET"
_RETENTION_YEARS = 6
_SALT_FILE_MODE = 0o600


# ---------------------------------------------------------------------------
# PII Pseudonymizer
# ---------------------------------------------------------------------------

class PiiPseudonymizer:
    """
    Deterministic HMAC-SHA256 pseudonymization.

    The salt is stored in a file with chmod 600 to prevent accidental leakage.
    Pseudonyms are stable within an installation (same salt → same output).
    """

    def __init__(self, salt_path: str | Path = ".audit_salt") -> None:
        self._salt_path = Path(salt_path)
        self._salt = self._load_or_create_salt()

    def _load_or_create_salt(self) -> bytes:
        if self._salt_path.exists():
            current_mode = self._salt_path.stat().st_mode & 0o777
            if current_mode != _SALT_FILE_MODE:
                logger.warning(
                    "Salt file %s has insecure permissions %o — enforcing 600",
                    self._salt_path,
                    current_mode,
                )
                os.chmod(self._salt_path, _SALT_FILE_MODE)
            return self._salt_path.read_bytes()

        salt = secrets.token_bytes(32)
        self._salt_path.write_bytes(salt)
        os.chmod(self._salt_path, _SALT_FILE_MODE)
        return salt

    def pseudonymize(self, value: str) -> str:
        """Return a stable 16-char pseudonym for value."""
        mac = _hmac.new(self._salt, value.encode("utf-8"), hashlib.sha256)
        return "pii:" + mac.hexdigest()[:16]

    def pseudonymize_dict(
        self, data: dict[str, Any], pii_fields: set[str]
    ) -> dict[str, Any]:
        """Return a shallow copy of data with specified fields pseudonymized."""
        result = dict(data)
        for key in pii_fields:
            if key in result and result[key] is not None:
                result[key] = self.pseudonymize(str(result[key]))
        return result


# ---------------------------------------------------------------------------
# Audit entry
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    sequence: int
    timestamp: str
    action: str
    user: str
    justification: str
    data: dict[str, Any]
    prev_hash: str
    signature: str = field(default="", init=False)

    def compute_signature(self, secret: bytes) -> str:
        """HMAC-SHA256 over canonical payload."""
        payload = (
            f"{self.sequence}|{self.timestamp}|{self.action}"
            f"|{self.user}|{self.justification}"
            f"|{self.prev_hash}"
            f"|{json.dumps(self.data, sort_keys=True, ensure_ascii=False)}"
        )
        mac = _hmac.new(secret, payload.encode("utf-8"), hashlib.sha256)
        return mac.hexdigest()

    def to_csv_row(self) -> list[str]:
        """PAF CSV row: Date;Action;Utilisateur;Justificatif;HashPrecedent;Signature;NumeroSequence"""
        return [
            self.timestamp,
            self.action,
            self.user,
            self.justification,
            self.prev_hash,
            self.signature,
            str(self.sequence),
        ]


# ---------------------------------------------------------------------------
# Replay infrastructure
# ---------------------------------------------------------------------------

@dataclass
class ReplayResult:
    entry: AuditEntry
    replay_output: Any
    matched: bool
    dry_run: bool
    error: str = ""


class ReplayableAgent(ABC):
    """Abstract base for agents that can replay audit trail events."""

    @abstractmethod
    async def replay_action(
        self,
        entry: AuditEntry,
        replay_context: dict[str, Any],
        dry_run: bool = False,
    ) -> Any:
        """
        Replay a single audit entry.

        Args:
            entry: The audit entry to replay.
            replay_context: Shared mutable context across the replay sequence.
            dry_run: If True, simulate but do not apply side effects.

        Returns:
            The result of the replayed action.
        """
        ...

    @property
    @abstractmethod
    def supported_event_types(self) -> frozenset[str]:
        """Return the set of action names this agent can handle."""
        ...


class ReplayRegistry:
    """Maps event_type strings to ReplayableAgent instances."""

    def __init__(self) -> None:
        self._registry: dict[str, ReplayableAgent] = {}

    def register(self, agent: ReplayableAgent) -> None:
        """Register an agent for all of its supported event types."""
        for event_type in agent.supported_event_types:
            self._registry[event_type] = agent

    def get(self, event_type: str) -> ReplayableAgent | None:
        return self._registry.get(event_type)

    def registered_types(self) -> list[str]:
        return sorted(self._registry.keys())


# ---------------------------------------------------------------------------
# AuditTrail
# ---------------------------------------------------------------------------

class AuditTrail:
    """
    Tamper-evident audit trail with HMAC hash chain.

    Thread-safe write path via threading.Lock + SQLite WAL.
    Non-blocking async path via asyncio.Queue + _writer_loop.
    """

    _PAF_HEADER = [
        "Date",
        "Action",
        "Utilisateur",
        "Justificatif",
        "HashPrecedent",
        "Signature",
        "NumeroSequence",
    ]

    def __init__(
        self,
        db_path: str | Path = "audit.db",
        salt_path: str | Path = ".audit_salt",
        secret: bytes | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        env_secret = os.environ.get(_AUDIT_SECRET_ENV, "")
        if not env_secret and secret is None:
            logger.warning(
                "AUDIT_HMAC_SECRET non configuré — secret aléatoire utilisé "
                "(les HMAC ne seront pas reproductibles d'une session à l'autre). "
                "Définissez la variable d'environnement AUDIT_HMAC_SECRET pour "
                "une chaîne d'audit stable et vérifiable."
            )
        self._secret: bytes = secret or (
            env_secret.encode("utf-8") if env_secret else secrets.token_bytes(32)
        )
        self._pseudonymizer = PiiPseudonymizer(salt_path)
        self._event_bus = event_bus
        self._replay_registry = ReplayRegistry()
        self._lock = threading.Lock()
        self._queue: asyncio.Queue[AuditEntry | None] = asyncio.Queue(maxsize=10_000)
        self._writer_task: asyncio.Task | None = None

        self._init_db()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_entries (
                    sequence      INTEGER PRIMARY KEY,
                    timestamp     TEXT    NOT NULL,
                    action        TEXT    NOT NULL,
                    user          TEXT    NOT NULL,
                    justification TEXT    NOT NULL,
                    data_json     TEXT    NOT NULL,
                    prev_hash     TEXT    NOT NULL,
                    signature     TEXT    NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ts
                ON audit_entries (timestamp)
            """)
            conn.commit()

    async def start(self) -> None:
        """Start the background async writer loop."""
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def stop(self) -> None:
        """Drain the queue and shut down the writer loop."""
        await self._queue.put(None)  # sentinel
        if self._writer_task:
            await self._writer_task

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    async def record(
        self,
        action: str,
        user: str,
        justification: str = "",
        data: dict[str, Any] | None = None,
        pii_fields: set[str] | None = None,
    ) -> AuditEntry:
        """
        Enqueue an audit entry for async writing.
        Returns immediately after enqueueing.
        """
        entry = self._build_entry(action, user, justification, data, pii_fields)
        await self._queue.put(entry)
        return entry

    def record_sync(
        self,
        action: str,
        user: str,
        justification: str = "",
        data: dict[str, Any] | None = None,
        pii_fields: set[str] | None = None,
    ) -> AuditEntry:
        """
        Synchronous write — bypasses the queue.
        Use for critical events where confirmation is needed immediately.
        """
        entry = self._build_entry(action, user, justification, data, pii_fields)
        self._write_entry(entry)
        return entry

    def _build_entry(
        self,
        action: str,
        user: str,
        justification: str,
        data: dict[str, Any] | None,
        pii_fields: set[str] | None,
    ) -> AuditEntry:
        sanitized = dict(data or {})
        if pii_fields:
            sanitized = self._pseudonymizer.pseudonymize_dict(sanitized, pii_fields)

        sequence = self._next_sequence()
        prev_hash = self._get_prev_hash()
        timestamp = datetime.now(timezone.utc).isoformat()

        entry = AuditEntry(
            sequence=sequence,
            timestamp=timestamp,
            action=action,
            user=user,
            justification=justification,
            data=sanitized,
            prev_hash=prev_hash,
        )
        entry.signature = entry.compute_signature(self._secret)
        return entry

    async def _writer_loop(self) -> None:
        """Drain queue and persist entries until sentinel None is received."""
        while True:
            entry = await self._queue.get()
            if entry is None:
                self._queue.task_done()
                break
            try:
                self._write_entry(entry)
            except Exception as exc:
                logger.error(
                    "Audit write failed for sequence %d: %s", entry.sequence, exc
                )
            finally:
                self._queue.task_done()

    def _write_entry(self, entry: AuditEntry) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO audit_entries
                (sequence, timestamp, action, user, justification, data_json, prev_hash, signature)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.sequence,
                    entry.timestamp,
                    entry.action,
                    entry.user,
                    entry.justification,
                    json.dumps(entry.data, ensure_ascii=False, sort_keys=True),
                    entry.prev_hash,
                    entry.signature,
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Sequence + hash helpers (thread-safe)
    # ------------------------------------------------------------------

    def _next_sequence(self) -> int:
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                row = conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM audit_entries"
                ).fetchone()
                return int(row[0])

    def _get_prev_hash(self) -> str:
        with sqlite3.connect(str(self._db_path)) as conn:
            row = conn.execute(
                "SELECT signature FROM audit_entries ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else "GENESIS"

    # ------------------------------------------------------------------
    # Chain integrity verification
    # ------------------------------------------------------------------

    def verify_chain(self) -> tuple[bool, list[str]]:
        """
        Walk the hash chain and verify each HMAC signature.

        Returns:
            (valid: bool, errors: list[str])
        """
        errors: list[str] = []
        with sqlite3.connect(str(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT sequence, timestamp, action, user, justification, "
                "data_json, prev_hash, signature "
                "FROM audit_entries ORDER BY sequence"
            ).fetchall()

        prev_sig = "GENESIS"
        for row in rows:
            seq, ts, action, user, just, data_json, prev_hash, sig = row
            if prev_hash != prev_sig:
                errors.append(
                    f"Hash chain break at sequence {seq}: "
                    f"expected prev_hash={prev_sig!r}, got {prev_hash!r}"
                )
            data = json.loads(data_json)
            entry = AuditEntry(
                sequence=seq,
                timestamp=ts,
                action=action,
                user=user,
                justification=just,
                data=data,
                prev_hash=prev_hash,
            )
            expected = entry.compute_signature(self._secret)
            if sig != expected:
                errors.append(f"Signature mismatch at sequence {seq}")
            prev_sig = sig

        return len(errors) == 0, errors

    # ------------------------------------------------------------------
    # Replay
    # ------------------------------------------------------------------

    def register_replay_agent(self, agent: ReplayableAgent) -> None:
        """Register a ReplayableAgent with the internal ReplayRegistry."""
        self._replay_registry.register(agent)

    async def replay_sequence(
        self,
        from_seq: int,
        to_seq: int,
        stop_on_mismatch: bool = True,
        dry_run: bool = False,
    ) -> list[ReplayResult]:
        """
        Replay audit entries [from_seq..to_seq] using registered agents.

        Args:
            from_seq: First sequence number (inclusive).
            to_seq: Last sequence number (inclusive).
            stop_on_mismatch: Abort replay when an agent result mismatches.
            dry_run: Pass dry_run=True to all agents (no side effects).

        Returns:
            List of ReplayResult, one per processed entry.
        """
        entries = self._load_entries(from_seq, to_seq)
        results: list[ReplayResult] = []
        replay_context: dict[str, Any] = {}

        for entry in entries:
            agent = self._replay_registry.get(entry.action)
            if agent is None:
                results.append(ReplayResult(
                    entry=entry,
                    replay_output=None,
                    matched=False,
                    dry_run=dry_run,
                    error=f"No agent registered for action '{entry.action}'",
                ))
                if stop_on_mismatch:
                    break
                continue

            try:
                output = await agent.replay_action(entry, replay_context, dry_run)
                expected = entry.data.get("expected_output")
                matched = (expected is None) or (output == expected)
                results.append(ReplayResult(
                    entry=entry,
                    replay_output=output,
                    matched=matched,
                    dry_run=dry_run,
                ))
                if stop_on_mismatch and not matched:
                    break
            except Exception as exc:
                results.append(ReplayResult(
                    entry=entry,
                    replay_output=None,
                    matched=False,
                    dry_run=dry_run,
                    error=str(exc),
                ))
                if stop_on_mismatch:
                    break

        return results

    def _load_entries(self, from_seq: int, to_seq: int) -> list[AuditEntry]:
        with sqlite3.connect(str(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT sequence, timestamp, action, user, justification, "
                "data_json, prev_hash, signature "
                "FROM audit_entries "
                "WHERE sequence BETWEEN ? AND ? ORDER BY sequence",
                (from_seq, to_seq),
            ).fetchall()

        entries: list[AuditEntry] = []
        for seq, ts, action, user, just, data_json, prev_hash, sig in rows:
            e = AuditEntry(
                sequence=seq,
                timestamp=ts,
                action=action,
                user=user,
                justification=just,
                data=json.loads(data_json),
                prev_hash=prev_hash,
            )
            e.signature = sig
            entries.append(e)
        return entries

    # ------------------------------------------------------------------
    # PAF CSV export (Piste d'Audit Fiable — French legal format)
    # ------------------------------------------------------------------

    def export_paf_csv(
        self,
        output: str | Path | io.StringIO | None = None,
        from_seq: int | None = None,
        to_seq: int | None = None,
    ) -> str:
        """
        Export the audit trail in PAF (Piste d'Audit Fiable) CSV format.

        Column order: Date;Action;Utilisateur;Justificatif;HashPrecedent;Signature;NumeroSequence

        Args:
            output: File path or StringIO to write to. If None, returns the string only.
            from_seq: Optional start sequence filter.
            to_seq: Optional end sequence filter.

        Returns:
            CSV content as a string.
        """
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL)
        writer.writerow(self._PAF_HEADER)

        with sqlite3.connect(str(self._db_path)) as conn:
            query = (
                "SELECT sequence, timestamp, action, user, justification, "
                "data_json, prev_hash, signature FROM audit_entries"
            )
            params: list[Any] = []
            conditions: list[str] = []
            if from_seq is not None:
                conditions.append("sequence >= ?")
                params.append(from_seq)
            if to_seq is not None:
                conditions.append("sequence <= ?")
                params.append(to_seq)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY sequence"
            rows = conn.execute(query, params).fetchall()

        for seq, ts, action, user, just, data_json, prev_hash, sig in rows:
            e = AuditEntry(
                sequence=seq,
                timestamp=ts,
                action=action,
                user=user,
                justification=just,
                data=json.loads(data_json),
                prev_hash=prev_hash,
            )
            e.signature = sig
            writer.writerow(e.to_csv_row())

        csv_content = buf.getvalue()

        if output is not None:
            if isinstance(output, (str, Path)):
                Path(output).write_text(csv_content, encoding="utf-8")
            else:
                output.write(csv_content)

        return csv_content

    # ------------------------------------------------------------------
    # Retention cleanup (6-year legal minimum)
    # ------------------------------------------------------------------

    def cleanup_expired(self, anchor: bool = True) -> int:
        """
        Delete audit entries older than 6 years.

        If anchor=True (default), inserts an anchor entry recording the last
        deleted sequence and signature before deletion — preserving chain
        integrity evidence without storing the deleted data.

        Returns:
            Number of entries deleted.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=_RETENTION_YEARS * 365)
        ).isoformat()

        with sqlite3.connect(str(self._db_path)) as conn:
            last_row = conn.execute(
                "SELECT sequence, signature FROM audit_entries "
                "WHERE timestamp < ? ORDER BY sequence DESC LIMIT 1",
                (cutoff,),
            ).fetchone()

            if last_row is None:
                return 0

            if anchor:
                anchor_entry = self._build_entry(
                    action="CLEANUP_ANCHOR",
                    user="system",
                    justification=(
                        f"Retention cleanup: entries before {cutoff}. "
                        f"Last deleted sequence={last_row[0]}, "
                        f"last deleted signature={last_row[1]}"
                    ),
                    data={
                        "cutoff_iso": cutoff,
                        "last_expired_sequence": last_row[0],
                        "last_expired_signature": last_row[1],
                    },
                    pii_fields=None,
                )
                self._write_entry(anchor_entry)

            cursor = conn.execute(
                "DELETE FROM audit_entries WHERE timestamp < ?", (cutoff,)
            )
            deleted = cursor.rowcount
            conn.commit()

        return deleted


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------

class AuditEventBusIntegration:
    """
    Subscribes to EventBus channels and records matching events as audit entries.

    Usage:
        integration = AuditEventBusIntegration(trail, bus, channels=["invoice.*"])
        await integration.start()
    """

    def __init__(
        self,
        audit_trail: AuditTrail,
        event_bus: Any,
        channels: list[str] | None = None,
        pii_fields: set[str] | None = None,
    ) -> None:
        self._audit = audit_trail
        self._bus = event_bus
        self._channels = channels or ["*"]
        self._pii_fields = pii_fields or set()

    async def start(self) -> None:
        """Subscribe to all configured channels."""
        for channel in self._channels:
            await self._bus.subscribe(
                channel=channel,
                callback=self._on_event,
                subscriber_id=f"audit_trail:{channel}",
            )

    async def _on_event(self, event: Any) -> None:
        """Record a received EventBus event into the audit trail."""
        try:
            await self._audit.record(
                action=getattr(event, "channel", "unknown"),
                user=getattr(event, "source", "system"),
                justification="EventBus auto-record",
                data=dict(getattr(event, "data", {}) or {}),
                pii_fields=self._pii_fields,
            )
        except Exception as exc:
            logger.error("AuditEventBusIntegration._on_event failed: %s", exc)
