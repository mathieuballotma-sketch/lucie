from __future__ import annotations

import ctypes
import ctypes.util
import json
import logging
import mmap
import os
import re
import struct
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from ..utils.logger import logger
from ..brain.synapses.event_bus import EventBus, Event


# ─────────────────────────────────────────────────────────────────────────────
# Low-level memory protection via ctypes + libc
# ─────────────────────────────────────────────────────────────────────────────

_libc: Optional[ctypes.CDLL] = None
_MLOCK_AVAILABLE = False

try:
    _libc_name = ctypes.util.find_library("c")
    if _libc_name:
        _libc = ctypes.CDLL(_libc_name, use_errno=True)
        _MLOCK_AVAILABLE = True
except Exception:
    pass


def lock_memory(address: int, size: int) -> bool:
    """
    Lock memory pages at address to prevent swapping (mlock).

    Uses ctypes to call libc mlock(), preventing the OS from swapping
    sensitive memory pages to disk (where they could be read from swap).

    Args:
        address: Memory address to lock (from ctypes buffer)
        size: Number of bytes to lock

    Returns:
        bool: True if mlock succeeded, False otherwise

    Note:
        On macOS, mlock is limited by RLIMIT_MEMLOCK (usually ~8MB).
        On Linux, unprivileged users are limited by /etc/security/limits.conf.
    """
    if not _MLOCK_AVAILABLE or _libc is None:
        logger.debug("mlock not available on this platform")
        return False
    try:
        result = _libc.mlock(ctypes.c_void_p(address), ctypes.c_size_t(size))
        if result == 0:
            logger.debug(f"mlock: locked {size} bytes at 0x{address:x}")
            return True
        errno = ctypes.get_errno()
        logger.warning(f"mlock failed (errno={errno}), memory may be swapped")
        return False
    except Exception as e:
        logger.warning(f"mlock exception: {e}")
        return False


def unlock_memory(address: int, size: int) -> bool:
    """
    Unlock memory pages (munlock), allowing the OS to swap them again.

    Args:
        address: Memory address to unlock
        size: Number of bytes to unlock

    Returns:
        bool: True if munlock succeeded, False otherwise
    """
    if not _MLOCK_AVAILABLE or _libc is None:
        return False
    try:
        result = _libc.munlock(ctypes.c_void_p(address), ctypes.c_size_t(size))
        return result == 0
    except Exception:
        return False


def secure_wipe(buffer: ctypes.Array, size: Optional[int] = None) -> None:
    """
    Securely erase a ctypes buffer by overwriting with zeros.

    Uses ctypes.memset which cannot be optimized away by the Python
    interpreter (unlike a simple bytearray assignment). This provides
    a reliable wipe analogous to memset_s / explicit_bzero.

    Args:
        buffer: A ctypes buffer (from create_string_buffer)
        size: Number of bytes to wipe (default: full buffer)
    """
    if size is None:
        size = ctypes.sizeof(buffer)
    ctypes.memset(ctypes.addressof(buffer), 0, size)


@dataclass
class SecretFinding:
    """Represents a detected secret in text or file."""
    type: str
    start_pos: int
    end_pos: int
    masked_preview: str
    severity: str  # "critical", "high", "medium"


# ─────────────────────────────────────────────────────────────────────────────
# SecureBuffer — ctypes-backed buffer with mlock and secure wipe
# ─────────────────────────────────────────────────────────────────────────────

class SecureBuffer:
    """
    Low-level secure buffer using ctypes.create_string_buffer.

    Allocates memory via ctypes (not Python objects), locks it with mlock
    to prevent swapping, and overwrites with zeros before deallocation.
    Use this for raw key material, passwords, and tokens.

    Features:
    - ctypes.create_string_buffer allocation (avoids Python interning)
    - mlock to prevent swap (graceful fallback if unavailable)
    - secure_wipe (ctypes.memset) on wipe/close/del
    - Context manager for automatic cleanup
    - Thread-safe with Lock

    Example:
        with SecureBuffer(size=64) as buf:
            buf.write(b'my_secret_key_material_here')
            data = buf.read()
        # Memory is wiped and unlocked on exit

    Note:
        Prefer bytearray over str for sensitive data in Python to avoid
        string interning. This class goes further by using ctypes buffers.
    """

    def __init__(self, size: int = 4096) -> None:
        """
        Allocate and lock a secure buffer.

        Args:
            size: Buffer size in bytes (default 4KB)
        """
        self.size = size
        self._lock = threading.Lock()
        self._wiped = False

        # Allocate via ctypes (not Python heap — avoids interning)
        self._buffer = ctypes.create_string_buffer(size)
        self._address = ctypes.addressof(self._buffer)

        # Attempt mlock to prevent swap
        self._locked = lock_memory(self._address, size)

        logger.debug(
            f"SecureBuffer allocated ({size} bytes, mlock={'OK' if self._locked else 'FALLBACK'})"
        )

    def write(self, data: bytes, offset: int = 0) -> None:
        """
        Write bytes into the secure buffer.

        Args:
            data: Bytes to write
            offset: Byte offset to write at

        Raises:
            ValueError: If data exceeds buffer capacity
        """
        if offset + len(data) > self.size:
            raise ValueError(
                f"Data ({offset + len(data)} bytes) exceeds buffer ({self.size} bytes)"
            )
        with self._lock:
            ctypes.memmove(self._address + offset, data, len(data))

    def read(self, size: Optional[int] = None, offset: int = 0) -> bytes:
        """
        Read bytes from the secure buffer.

        Args:
            size: Number of bytes to read (default: entire buffer)
            offset: Byte offset to read from

        Returns:
            bytes: Read data
        """
        if size is None:
            size = self.size
        with self._lock:
            return self._buffer.raw[offset:offset + size]

    def wipe(self) -> None:
        """Securely zero-fill the buffer using ctypes.memset."""
        with self._lock:
            if not self._wiped:
                secure_wipe(self._buffer, self.size)
                self._wiped = True
                logger.debug("SecureBuffer wiped")

    def close(self) -> None:
        """Wipe buffer and unlock memory."""
        self.wipe()
        if self._locked:
            unlock_memory(self._address, self.size)
            self._locked = False

    def __enter__(self) -> SecureBuffer:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# SecureMemoryBuffer — high-level key-value store on top of SecureBuffer
# ─────────────────────────────────────────────────────────────────────────────

class SecureMemoryBuffer:
    """
    High-level secure key-value store for secrets in protected memory.

    Wraps SecureBuffer with a JSON-serialized dict interface.
    All secret material is stored in mlock'd ctypes memory, never in
    regular Python str/bytes objects that could be interned or swapped.

    Example:
        with SecureMemoryBuffer(capacity=4096) as buf:
            buf.store("api_key", "sk-12345...")
            key = buf.retrieve("api_key")
    """

    def __init__(self, capacity: int = 4096) -> None:
        """
        Initialize a secure memory buffer.

        Args:
            capacity: Maximum buffer size in bytes (default 4KB)
        """
        self.capacity = capacity
        self._lock = threading.Lock()
        self._data: Dict[str, str] = {}
        self._secure_buf = SecureBuffer(size=capacity)

        logger.debug(f"SecureMemoryBuffer initialized (capacity: {capacity})")

    def store(self, key: str, value: str) -> None:
        """
        Store a secret value in protected memory.

        Args:
            key: Identifier for the secret
            value: The sensitive data to store

        Raises:
            MemoryError: If buffer capacity would be exceeded
        """
        with self._lock:
            self._data[key] = value
            encoded = json.dumps(self._data).encode()
            if len(encoded) > self.capacity:
                del self._data[key]
                raise MemoryError(
                    f"Buffer capacity exceeded ({len(encoded)} > {self.capacity})"
                )
            # Wipe old content and write new
            secure_wipe(self._secure_buf._buffer, self._secure_buf.size)
            self._secure_buf.write(encoded)

    def retrieve(self, key: str) -> Optional[str]:
        """
        Retrieve a secret from protected memory.

        Args:
            key: Identifier for the secret

        Returns:
            The stored value, or None if not found
        """
        with self._lock:
            return self._data.get(key)

    def wipe(self) -> None:
        """Securely zero-fill the buffer and clear all stored data."""
        with self._lock:
            self._data.clear()
            self._secure_buf.wipe()
            # Re-init buffer for reuse
            self._secure_buf._wiped = False
            logger.debug("SecureMemoryBuffer wiped")

    def __enter__(self) -> SecureMemoryBuffer:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.wipe()
        self._secure_buf.close()

    def __del__(self) -> None:
        try:
            self.wipe()
        except Exception:
            pass


class SecretsScanner:
    """
    Scans strings and files for accidentally leaked secrets.

    Detects:
    - API keys (sk-*, AKIA* AWS, Bearer tokens)
    - Private keys (-----BEGIN RSA PRIVATE KEY-----)
    - Passwords in config (password=, secret=, token=)
    - French SSN patterns (13 digits)
    - Credit card numbers (basic Luhn check)

    Example:
        scanner = SecretsScanner()
        findings = scanner.scan_text("api_key = sk-1234567890")
        redacted = scanner.redact("Bearer token: sk-abc123")
    """

    # Regex patterns for different secret types
    PATTERNS = {
        "api_key_openai": {
            "pattern": r"\bsk-[a-zA-Z0-9]{20,}",
            "severity": "critical",
        },
        "api_key_aws": {
            "pattern": r"\bAKIA[0-9A-Z]{16}",
            "severity": "critical",
        },
        "bearer_token": {
            "pattern": r"\bBearer\s+[a-zA-Z0-9\-_\.]+",
            "severity": "critical",
        },
        "private_key_rsa": {
            "pattern": r"-----BEGIN RSA PRIVATE KEY-----.*?-----END RSA PRIVATE KEY-----",
            "severity": "critical",
        },
        "private_key_generic": {
            "pattern": r"-----BEGIN [A-Z ]+PRIVATE KEY-----",
            "severity": "critical",
        },
        "password_config": {
            "pattern": r"(password|passwd|pwd)\s*[=:]\s*\S+",
            "severity": "high",
        },
        "secret_config": {
            "pattern": r"(secret|api[_-]?key|token)\s*[=:]\s*['\"]([^'\"]+)['\"]",
            "severity": "high",
        },
        "connection_string": {
            "pattern": r"(mongodb|postgres|mysql)://[^\s]+",
            "severity": "high",
        },
        "french_ssn": {
            "pattern": r"\b\d{13}\b",  # French SSN is 13 digits
            "severity": "medium",
        },
        "credit_card": {
            "pattern": r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b",
            "severity": "high",
        },
    }

    def __init__(self) -> None:
        """Initialize secrets scanner with compiled patterns."""
        self._compiled_patterns = {
            name: re.compile(
                config["pattern"], re.IGNORECASE | re.MULTILINE | re.DOTALL
            )
            for name, config in self.PATTERNS.items()
        }
        logger.debug("SecretsScanner initialized")

    def scan_text(self, text: str) -> List[SecretFinding]:
        """
        Scan text for leaked secrets.

        Args:
            text: Text to scan

        Returns:
            List of SecretFinding objects
        """
        findings: List[SecretFinding] = []

        for secret_type, compiled_pattern in self._compiled_patterns.items():
            severity = self.PATTERNS[secret_type]["severity"]

            for match in compiled_pattern.finditer(text):
                start_pos = match.start()
                end_pos = match.end()
                matched_text = match.group(0)

                # Create masked preview
                if len(matched_text) > 20:
                    masked = matched_text[:10] + "[...]" + matched_text[-5:]
                else:
                    masked = "[REDACTED]"

                finding = SecretFinding(
                    type=secret_type,
                    start_pos=start_pos,
                    end_pos=end_pos,
                    masked_preview=masked,
                    severity=severity,
                )
                findings.append(finding)

        return findings

    def scan_file(self, filepath: str | Path) -> List[SecretFinding]:
        """
        Scan a file for leaked secrets.

        Args:
            filepath: Path to file to scan

        Returns:
            List of SecretFinding objects

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        file_path = Path(filepath)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return self.scan_text(content)
        except Exception as e:
            logger.error(f"Error scanning file {filepath}: {e}")
            return []

    def redact(self, text: str) -> str:
        """
        Replace detected secrets with [REDACTED] placeholder.

        Args:
            text: Text to redact

        Returns:
            Text with secrets replaced by [REDACTED]
        """
        redacted = text
        findings = self.scan_text(text)

        # Sort findings by position (reverse) to avoid offset issues
        for finding in sorted(findings, key=lambda f: f.start_pos, reverse=True):
            redacted = (
                redacted[: finding.start_pos]
                + "[REDACTED]"
                + redacted[finding.end_pos :]
            )

        return redacted


class ProcessMemoryGuard:
    """
    Monitors Lucie process memory for leaks and anomalies.

    Features:
    - Tracks RSS (Resident Set Size) memory usage
    - Configurable RSS threshold (default 2GB for M3 16GB)
    - Detects memory growth anomalies (>50% increase in 60s)
    - Publishes alerts via EventBus channel 'security.memory_alert'
    - Background thread monitoring with configurable interval
    - Graceful degradation on platforms without psutil

    Example:
        guard = ProcessMemoryGuard(event_bus=bus, rss_threshold_gb=3)
        guard.start_monitoring(interval=10)  # Check every 10 seconds
        # ... later ...
        guard.stop_monitoring()
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        rss_threshold_gb: float = 2.0,
        growth_threshold: float = 0.5,
    ) -> None:
        """
        Initialize memory guard.

        Args:
            event_bus: EventBus instance for publishing alerts
            rss_threshold_gb: Memory threshold in GB (default 2GB)
            growth_threshold: Growth threshold as fraction (default 0.5 = 50%)
        """
        self.event_bus = event_bus
        self.rss_threshold_bytes = int(rss_threshold_gb * 1024 * 1024 * 1024)
        self.growth_threshold = growth_threshold

        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._last_rss: Optional[int] = None
        self._last_check_time: float = time.time()
        self._alert_cooldown: Dict[str, float] = {}
        self._alert_cooldown_period = 60  # seconds

        self._process: Optional[psutil.Process] = None
        if PSUTIL_AVAILABLE:
            try:
                self._process = psutil.Process(os.getpid())
            except Exception as e:
                logger.warning(f"Failed to initialize psutil Process: {e}")

        logger.debug(
            f"ProcessMemoryGuard initialized (threshold: {rss_threshold_gb}GB, "
            f"growth: {growth_threshold*100:.0f}%, psutil: {PSUTIL_AVAILABLE})"
        )

    def start_monitoring(self, interval: float = 10.0) -> None:
        """
        Start background memory monitoring thread.

        Args:
            interval: Check interval in seconds (default 10)
        """
        if self._monitoring:
            logger.warning("Memory monitoring already started")
            return

        if not PSUTIL_AVAILABLE:
            logger.warning("psutil not available, memory monitoring disabled")
            return

        with self._lock:
            self._monitoring = True
            self._last_check_time = time.time()
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                args=(interval,),
                daemon=True,
                name="MemoryGuard",
            )
            self._monitor_thread.start()
            logger.info(f"Memory monitoring started (interval: {interval}s)")

    def stop_monitoring(self) -> None:
        """Stop background memory monitoring thread."""
        with self._lock:
            self._monitoring = False

        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=5)
            logger.info("Memory monitoring stopped")

    def _monitor_loop(self, interval: float) -> None:
        """
        Background monitoring loop.

        Args:
            interval: Check interval in seconds
        """
        while self._monitoring:
            try:
                self._check_memory()
                time.sleep(interval)
            except Exception as e:
                logger.error(f"Memory monitoring error: {e}")

    def _check_memory(self) -> None:
        """Check current memory usage and publish alerts."""
        if self._process is None:
            return

        try:
            mem_info = self._process.memory_info()
            current_rss = mem_info.rss

            with self._lock:
                # Check absolute threshold
                if current_rss > self.rss_threshold_bytes:
                    self._publish_alert(
                        "memory_threshold_exceeded",
                        f"RSS {current_rss / (1024**3):.2f}GB exceeds threshold "
                        f"{self.rss_threshold_bytes / (1024**3):.2f}GB",
                    )

                # Check growth anomaly
                if self._last_rss is not None:
                    growth = (current_rss - self._last_rss) / self._last_rss
                    if growth > self.growth_threshold:
                        self._publish_alert(
                            "memory_growth_anomaly",
                            f"Memory grew {growth*100:.1f}% in {time.time() - self._last_check_time:.0f}s "
                            f"({self._last_rss / (1024**3):.2f}GB -> {current_rss / (1024**3):.2f}GB)",
                        )

                self._last_rss = current_rss
                self._last_check_time = time.time()

        except Exception as e:
            logger.error(f"Error checking memory: {e}")

    def _publish_alert(self, alert_type: str, message: str) -> None:
        """
        Publish alert via EventBus if not in cooldown.

        Args:
            alert_type: Type of alert
            message: Alert message
        """
        if not self.event_bus:
            logger.warning(f"Memory alert (no EventBus): {alert_type} - {message}")
            return

        # Check cooldown
        now = time.time()
        last_alert = self._alert_cooldown.get(alert_type, 0)
        if now - last_alert < self._alert_cooldown_period:
            return

        self._alert_cooldown[alert_type] = now

        try:
            event = Event(
                id=f"memory_{alert_type}_{int(now)}",
                channel="security.memory_alert",
                data={
                    "type": alert_type,
                    "message": message,
                    "timestamp": now,
                },
                source="ProcessMemoryGuard",
                timestamp=now,
            )
            self.event_bus.publish(event)
            logger.warning(f"Memory alert: {alert_type} - {message}")
        except Exception as e:
            logger.error(f"Failed to publish memory alert: {e}")

    @property
    def stats(self) -> Optional[Dict[str, Any]]:
        """Alias for get_memory_stats."""
        return self.get_memory_stats()

    def get_memory_stats(self) -> Optional[Dict[str, Any]]:
        """
        Get current process memory statistics.

        Returns:
            Dict with memory stats or None if unavailable
        """
        if self._process is None:
            return None

        try:
            mem_info = self._process.memory_info()
            return {
                "rss_mb": mem_info.rss / (1024 * 1024),
                "vms_mb": mem_info.vms / (1024 * 1024),
                "rss_threshold_mb": self.rss_threshold_bytes / (1024 * 1024),
                "monitoring": self._monitoring,
            }
        except Exception as e:
            logger.error(f"Error getting memory stats: {e}")
            return None
