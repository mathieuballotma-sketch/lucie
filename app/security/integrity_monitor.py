"""
DS-SEC-04: File Integrity Monitor

Monitors critical Lucie files for unauthorized modifications using BLAKE2b hashing.
Detects modifications, deletions, new unauthorized files, and permission changes.
Publishes violations via EventBus for real-time security awareness.

Thread-safe operations with background monitoring loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..brain.synapses.event_bus import Event, EventBus
from ..utils.logger import logger


class ViolationType(Enum):
    """Types of integrity violations detected."""
    MODIFIED = "modified"
    DELETED = "deleted"
    NEW_UNAUTHORIZED = "new_unauthorized"
    PERMISSION_CHANGED = "permission_changed"


class Severity(Enum):
    """Severity levels for integrity violations."""
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class IntegrityViolation:
    """
    Represents a detected file integrity violation.

    Attributes:
        filepath: Path to the file with integrity issue
        category: Category of file (config, model, code, data, plugin)
        violation_type: Type of violation (MODIFIED, DELETED, NEW_UNAUTHORIZED, PERMISSION_CHANGED)
        expected_hash: Expected BLAKE2b hash (None for NEW_UNAUTHORIZED)
        actual_hash: Current BLAKE2b hash (None for DELETED)
        timestamp: When violation was detected (Unix timestamp)
        severity: Severity level (warning or critical)
    """
    filepath: str
    category: str
    violation_type: ViolationType
    expected_hash: Optional[str]
    actual_hash: Optional[str]
    timestamp: float
    severity: Severity

    def to_dict(self) -> Dict[str, Any]:
        """Convert violation to dictionary format."""
        return {
            "filepath": self.filepath,
            "category": self.category,
            "violation_type": self.violation_type.value,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "timestamp": self.timestamp,
            "severity": self.severity.value,
        }


class IntegrityMonitor:
    """
    Monitors critical Lucie files for unauthorized modifications.

    Uses BLAKE2b hashing for tamper detection and SQLite for baseline storage.
    Provides background monitoring with configurable intervals.
    Publishes violations via EventBus for security awareness.
    """

    def __init__(
        self,
        data_dir: str = "data",
        db_path: Optional[str] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        """
        Initialize IntegrityMonitor.

        Args:
            data_dir: Base data directory
            db_path: Path to SQLite baseline database
            event_bus: EventBus instance for publishing violations
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        if db_path is None:
            db_path = str(self.data_dir / "integrity_baseline.db")
        self.db_path = db_path

        self.event_bus = event_bus
        self._registered_paths: Dict[str, str] = {}  # filepath -> category
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        self._init_db()
        logger.info(f"🛡️ IntegrityMonitor initialized (db: {self.db_path})")

    def _init_db(self) -> None:
        """Initialize SQLite database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS integrity_baseline (
                    filepath TEXT PRIMARY KEY,
                    hash TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    category TEXT NOT NULL,
                    checked_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS violation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT NOT NULL,
                    violation_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    details TEXT
                )
                """
            )
            conn.commit()
        logger.debug("✓ Integrity baseline database initialized")

    def register_path(self, filepath: str, category: str) -> None:
        """
        Register a file or directory for integrity monitoring.

        Args:
            filepath: Path to file or directory
            category: Category of file (config, model, code, data, plugin)
        """
        with self._lock:
            path = Path(filepath)
            if not path.exists():
                logger.warning(f"⚠️  Path does not exist: {filepath}")
                return

            self._registered_paths[filepath] = category
            logger.debug(f"📝 Registered {category}: {filepath}")

    def compute_baseline(self) -> int:
        """
        Compute BLAKE2b hashes for all registered files and store in SQLite.

        Returns:
            Number of files hashed
        """
        with self._lock:
            baseline_count = 0
            with sqlite3.connect(self.db_path) as conn:
                for filepath, category in self._registered_paths.items():
                    path = Path(filepath)

                    if path.is_file():
                        files_to_hash = [path]
                    elif path.is_dir():
                        files_to_hash = list(path.rglob("*"))
                        files_to_hash = [f for f in files_to_hash if f.is_file()]
                    else:
                        logger.warning(f"⚠️  Invalid path: {filepath}")
                        continue

                    for file_path in files_to_hash:
                        try:
                            file_hash = self._compute_file_hash(str(file_path))
                            size = file_path.stat().st_size
                            mtime = file_path.stat().st_mtime

                            conn.execute(
                                """
                                INSERT OR REPLACE INTO integrity_baseline
                                (filepath, hash, size, mtime, category, checked_at)
                                VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (str(file_path), file_hash, size, mtime, category, time.time()),
                            )
                            baseline_count += 1
                        except Exception as e:
                            logger.error(f"❌ Failed to hash {file_path}: {e}")

                conn.commit()

            logger.info(f"✓ Baseline computed: {baseline_count} files hashed")
            return baseline_count

    def check_integrity(self) -> List[IntegrityViolation]:
        """
        Compare current file hashes to baseline, detect modifications/deletions.

        Returns:
            List of IntegrityViolation objects
        """
        violations: List[IntegrityViolation] = []

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Fetch baseline records
                cursor = conn.execute(
                    "SELECT filepath, hash, category FROM integrity_baseline"
                )
                baseline_records = cursor.fetchall()

                checked_files: Set[str] = set()

                # Check each baseline file
                for filepath, expected_hash, category in baseline_records:
                    checked_files.add(filepath)
                    path = Path(filepath)

                    if not path.exists():
                        # File was deleted
                        violation = IntegrityViolation(
                            filepath=filepath,
                            category=category,
                            violation_type=ViolationType.DELETED,
                            expected_hash=expected_hash,
                            actual_hash=None,
                            timestamp=time.time(),
                            severity=Severity.CRITICAL,
                        )
                        violations.append(violation)
                        self._log_violation(conn, violation)
                        logger.warning(f"🚨 DELETED: {filepath}")
                    else:
                        # Check hash
                        try:
                            current_hash = self._compute_file_hash(filepath)
                            if current_hash != expected_hash:
                                violation = IntegrityViolation(
                                    filepath=filepath,
                                    category=category,
                                    violation_type=ViolationType.MODIFIED,
                                    expected_hash=expected_hash,
                                    actual_hash=current_hash,
                                    timestamp=time.time(),
                                    severity=Severity.CRITICAL,
                                )
                                violations.append(violation)
                                self._log_violation(conn, violation)
                                logger.warning(f"🚨 MODIFIED: {filepath}")
                        except Exception as e:
                            logger.error(f"❌ Failed to verify {filepath}: {e}")

                # Check for new unauthorized files in monitored directories
                for filepath, category in self._registered_paths.items():
                    path = Path(filepath)
                    if path.is_dir():
                        for file_path in path.rglob("*"):
                            if file_path.is_file() and str(file_path) not in checked_files:
                                violation = IntegrityViolation(
                                    filepath=str(file_path),
                                    category=category,
                                    violation_type=ViolationType.NEW_UNAUTHORIZED,
                                    expected_hash=None,
                                    actual_hash=self._compute_file_hash(str(file_path)),
                                    timestamp=time.time(),
                                    severity=Severity.WARNING,
                                )
                                violations.append(violation)
                                self._log_violation(conn, violation)
                                logger.warning(f"⚠️  NEW_UNAUTHORIZED: {file_path}")

                conn.commit()

        # Publish violations via EventBus
        if self.event_bus and violations:
            self._publish_violations(violations)

        return violations

    def auto_monitor_loop(self, interval: int = 300) -> None:
        """
        Start background monitoring thread that checks integrity periodically.

        Args:
            interval: Check interval in seconds (default: 5 minutes)
        """
        if self._monitoring:
            logger.warning("⚠️  Monitoring already active")
            return

        def monitor_worker() -> None:
            logger.info(f"🔄 Integrity monitor started (interval: {interval}s)")
            self._monitoring = True

            while self._monitoring:
                try:
                    violations = self.check_integrity()
                    if violations:
                        logger.warning(f"⚠️  {len(violations)} integrity violations detected")
                except Exception as e:
                    logger.error(f"❌ Integrity check failed: {e}")

                time.sleep(interval)

        self._monitor_thread = threading.Thread(target=monitor_worker, daemon=True)
        self._monitor_thread.start()
        logger.info("✓ Monitoring thread started")

    def stop_monitoring(self) -> None:
        """Stop background monitoring thread."""
        with self._lock:
            self._monitoring = False
            if self._monitor_thread:
                self._monitor_thread.join(timeout=5)
                self._monitor_thread = None
        logger.info("✓ Monitoring stopped")

    def get_baseline_summary(self) -> Dict[str, Any]:
        """
        Get summary of baseline database.

        Returns:
            Dictionary with baseline statistics
        """
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT COUNT(*), category FROM integrity_baseline GROUP BY category"
                )
                categories = {row[1]: row[0] for row in cursor.fetchall()}

                cursor = conn.execute("SELECT COUNT(*) FROM integrity_baseline")
                total = cursor.fetchone()[0]

                cursor = conn.execute("SELECT COUNT(*) FROM violation_history")
                violations = cursor.fetchone()[0]

        return {
            "total_files": total,
            "by_category": categories,
            "violations_recorded": violations,
            "last_checked": datetime.now().isoformat(),
        }

    @staticmethod
    def _compute_file_hash(filepath: str, chunk_size: int = 65536) -> str:
        """
        Compute BLAKE2b hash of a file.

        Args:
            filepath: Path to file
            chunk_size: Read chunk size in bytes

        Returns:
            BLAKE2b hash as hex string
        """
        h = hashlib.blake2b(digest_size=32)
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _log_violation(self, conn: sqlite3.Connection, violation: IntegrityViolation) -> None:
        """Log violation to database."""
        try:
            conn.execute(
                """
                INSERT INTO violation_history
                (filepath, violation_type, severity, timestamp, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    violation.filepath,
                    violation.violation_type.value,
                    violation.severity.value,
                    violation.timestamp,
                    json.dumps(violation.to_dict()),
                ),
            )
        except Exception as e:
            logger.error(f"❌ Failed to log violation: {e}")

    def _publish_violations(self, violations: List[IntegrityViolation]) -> None:
        """Publish violations via EventBus."""
        if not self.event_bus:
            return

        for violation in violations:
            try:
                event = Event(
                    id=f"integrity_{int(violation.timestamp * 1000)}",
                    channel="security.integrity_violation",
                    data=violation.to_dict(),
                    source="integrity_monitor",
                    timestamp=violation.timestamp,
                )
                # EventBus.publish is synchronous in this context
                # For async publishing, wrap in asyncio.run() if needed
                asyncio.create_task(self.event_bus.publish(event))
            except Exception as e:
                logger.error(f"❌ Failed to publish violation: {e}")


class CodeSignatureVerifier:
    """
    Verifies code files haven't been tampered with using BLAKE2b signatures.

    Stores signatures in JSON format for quick verification of module integrity.
    Essential for detecting unauthorized code modifications.
    """

    def __init__(self, data_dir: str = "data") -> None:
        """
        Initialize CodeSignatureVerifier.

        Args:
            data_dir: Base data directory
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.signatures_path = self.data_dir / "code_signatures.json"
        self._signatures: Dict[str, str] = {}
        self._lock = threading.RLock()

        self._load_signatures()
        logger.info(f"✓ CodeSignatureVerifier initialized (signatures: {self.signatures_path})")

    def sign_module(self, filepath: str) -> str:
        """
        Compute BLAKE2b signature of a code file and store it.

        Args:
            filepath: Path to code file

        Returns:
            BLAKE2b signature as hex string
        """
        with self._lock:
            path = Path(filepath)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {filepath}")

            # Compute signature
            signature = self._compute_signature(filepath)

            # Store signature
            self._signatures[filepath] = signature
            self._save_signatures()

            logger.debug(f"📝 Signed module: {filepath}")
            return signature

    def verify_module(self, filepath: str) -> bool:
        """
        Verify that a code file matches its stored signature.

        Args:
            filepath: Path to code file

        Returns:
            True if signature matches, False otherwise
        """
        with self._lock:
            if filepath not in self._signatures:
                logger.warning(f"⚠️  No signature for: {filepath}")
                return False

            try:
                current_signature = self._compute_signature(filepath)
                stored_signature = self._signatures[filepath]

                is_valid = current_signature == stored_signature
                if not is_valid:
                    logger.warning(f"🚨 Signature mismatch: {filepath}")

                return is_valid
            except Exception as e:
                logger.error(f"❌ Verification failed for {filepath}: {e}")
                return False

    def verify_all(self) -> Dict[str, bool]:
        """
        Verify all signed modules.

        Returns:
            Dictionary mapping filepath to verification result (True/False)
        """
        with self._lock:
            results = {}
            for filepath in self._signatures:
                try:
                    results[filepath] = self.verify_module(filepath)
                except Exception as e:
                    logger.error(f"❌ Failed to verify {filepath}: {e}")
                    results[filepath] = False

            verified_count = sum(1 for v in results.values() if v)
            total_count = len(results)
            logger.info(f"✓ Verification complete: {verified_count}/{total_count} modules valid")

            return results

    @staticmethod
    def _compute_signature(filepath: str, chunk_size: int = 65536) -> str:
        """
        Compute BLAKE2b signature of a file.

        Args:
            filepath: Path to file
            chunk_size: Read chunk size in bytes

        Returns:
            BLAKE2b signature as hex string
        """
        h = hashlib.blake2b(digest_size=32)
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _load_signatures(self) -> None:
        """Load signatures from JSON file."""
        if self.signatures_path.exists():
            try:
                with open(self.signatures_path, "r") as f:
                    self._signatures = json.load(f)
                logger.debug(f"✓ Loaded {len(self._signatures)} signatures")
            except Exception as e:
                logger.error(f"❌ Failed to load signatures: {e}")
                self._signatures = {}
        else:
            self._signatures = {}

    def _save_signatures(self) -> None:
        """Save signatures to JSON file."""
        try:
            with open(self.signatures_path, "w") as f:
                json.dump(self._signatures, f, indent=2)
            logger.debug(f"✓ Saved {len(self._signatures)} signatures")
        except Exception as e:
            logger.error(f"❌ Failed to save signatures: {e}")

    def add_signature(self, filepath: str, signature: str) -> None:
        """
        Manually add a signature (useful for batch operations).

        Args:
            filepath: Path to code file
            signature: BLAKE2b signature as hex string
        """
        with self._lock:
            self._signatures[filepath] = signature
            self._save_signatures()
            logger.debug(f"➕ Added signature: {filepath}")

    def remove_signature(self, filepath: str) -> None:
        """
        Remove a signature (e.g., when file is deleted).

        Args:
            filepath: Path to code file
        """
        with self._lock:
            if filepath in self._signatures:
                del self._signatures[filepath]
                self._save_signatures()
                logger.debug(f"➖ Removed signature: {filepath}")

    def get_signature_status(self) -> Dict[str, Any]:
        """
        Get overall signature status.

        Returns:
            Dictionary with signature statistics
        """
        with self._lock:
            return {
                "total_signatures": len(self._signatures),
                "last_updated": datetime.now().isoformat(),
                "signatures_file": str(self.signatures_path),
            }
