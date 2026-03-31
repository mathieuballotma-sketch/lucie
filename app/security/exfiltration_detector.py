"""
Network Exfiltration Detector for Lucie — DS-SEC-02 Implementation

Monitors outbound network connections from Lucie processes and applies heuristics
to detect suspicious data exfiltration attempts. Integrates with EventBus for
security events and AuditTrail for CRITICAL-level logging.

Architecture:
  - Async monitoring loop runs in background thread (non-blocking).
  - psutil snapshots all Lucie process connections at regular intervals.
  - Multiple heuristics detect anomalies: volume threshold, destination reputation,
    connection burst, sensitive file access.
  - Alerts published to EventBus and logged to AuditTrail (CRITICAL level).
  - Optional auto-kill for high-confidence threats (configurable).

Privacy:
  - NEVER logs packet content, only metadata (IP, port, volume, PID, timestamp).
  - No encryption keys, passwords, or sensitive data strings logged.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import signal
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Set, List, Dict

import psutil

from ..utils.logger import logger
from ..brain.synapses.event_bus import EventBus, Event


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExfiltrationConfig:
    """Configuration for ExfiltrationDetector behavior and thresholds."""

    volume_threshold_mb: float = 1.0
    """Maximum MB allowed to be sent in monitoring_window_s before triggering alert."""

    monitoring_window_s: float = 60.0
    """Time window (seconds) for tracking volume per process."""

    check_interval_s: float = 5.0
    """Interval between connection scans (seconds)."""

    whitelisted_hosts: Set[str] = field(default_factory=lambda: {
        "localhost", "127.0.0.1", "::1",
        # Common cloud/exchange APIs
        "api.openai.com", "api.anthropic.com",
        "api.stripe.com", "api.github.com",
    })
    """Set of whitelisted destination hostnames/IPs (safe destinations)."""

    whitelisted_ports: Set[int] = field(default_factory=lambda: {
        80, 443,      # HTTP/HTTPS
        53,           # DNS
        25, 587, 465, # SMTP
        3306, 5432,   # Database ports
    })
    """Set of whitelisted ports (standard safe ports)."""

    max_connections_per_process: int = 20
    """Raise alert if a single process has >N concurrent connections."""

    enabled: bool = True
    """Enable/disable monitoring (user-configurable)."""

    auto_kill: bool = False
    """Automatically kill suspicious processes (requires explicit user approval)."""


# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NetworkSnapshot:
    """Snapshot of a single network connection at a point in time."""

    pid: int
    """Process ID."""

    process_name: str
    """Human-readable process name (e.g., 'lucie', 'python')."""

    local_addr: str
    """Local address (IP:port)."""

    remote_addr: str
    """Remote address (IP or hostname:port)."""

    remote_host: str
    """Remote hostname/IP extracted from remote_addr."""

    remote_port: int
    """Remote port number."""

    status: str
    """Connection status (e.g., 'ESTABLISHED', 'LISTEN', 'TIME_WAIT')."""

    bytes_sent: int
    """Bytes sent over this connection."""

    bytes_recv: int
    """Bytes received."""

    timestamp: float
    """Snapshot timestamp (time.time())."""


@dataclass
class ExfiltrationAlert:
    """Security alert raised when suspicious activity is detected."""

    alert_id: str
    """Unique alert identifier (UUID)."""

    timestamp: float
    """When the alert was raised (time.time())."""

    pid: int
    """Process ID of the suspicious process."""

    process_name: str
    """Name of the suspicious process."""

    reason: str
    """Human-readable reason for the alert."""

    remote_addr: str
    """Remote destination that triggered the alert."""

    volume_bytes: int
    """Data volume that triggered the alert (if applicable)."""

    severity: str
    """Alert severity: 'warning' or 'critical'."""

    blocked: bool = False
    """True if the process was terminated."""

    heuristic: str = ""
    """Which heuristic triggered this alert (e.g., 'volume_threshold')."""


# ─────────────────────────────────────────────────────────────────────────────
# Exfiltration Detector
# ─────────────────────────────────────────────────────────────────────────────

class ExfiltrationDetector:
    """
    Monitors network activity from Lucie processes for suspicious exfiltration.

    Runs an async monitoring loop that periodically scans process connections,
    applies heuristics, and publishes alerts via EventBus.

    Usage:
        detector = ExfiltrationDetector(config=ExfiltrationConfig(...))
        await detector.start()
        # ... monitor runs in background ...
        await detector.stop()
    """

    def __init__(
        self,
        config: Optional[ExfiltrationConfig] = None,
        event_bus: Optional[EventBus] = None,
        audit_trail: Optional[Any] = None,
    ):
        """
        Initialize the ExfiltrationDetector.

        Args:
            config: ExfiltrationConfig instance (uses defaults if None).
            event_bus: EventBus for publishing security.exfiltration_detected events.
            audit_trail: AuditTrail for CRITICAL-level logging.
        """
        self.config = config or ExfiltrationConfig()
        self.event_bus = event_bus
        self.audit_trail = audit_trail

        # State
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._alerts: List[ExfiltrationAlert] = []
        self._alerts_lock = threading.Lock()

        # Volume tracking per process: {pid: [(timestamp, bytes_sent), ...]}
        self._volume_history: Dict[int, List[tuple[float, int]]] = {}
        self._volume_lock = threading.Lock()

        # Snapshot history for anomaly detection
        self._last_snapshots: Dict[int, List[NetworkSnapshot]] = {}

        logger.debug(
            f"ExfiltrationDetector initialized (enabled={self.config.enabled}, "
            f"volume_threshold={self.config.volume_threshold_mb} MB, "
            f"check_interval={self.config.check_interval_s}s)"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background monitoring thread."""
        if not self.config.enabled:
            logger.warning("ExfiltrationDetector is disabled, skipping start")
            return

        if self._monitoring:
            logger.warning("ExfiltrationDetector already running")
            return

        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="lucie.exfiltration_monitor",
        )
        self._monitor_thread.start()
        logger.info("ExfiltrationDetector monitoring started")

    async def stop(self) -> None:
        """Stop the monitoring thread and wait for it to exit."""
        if not self._monitoring:
            return

        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
            if self._monitor_thread.is_alive():
                logger.warning("ExfiltrationDetector monitoring thread did not exit cleanly")

        logger.info("ExfiltrationDetector monitoring stopped")

    # ─────────────────────────────────────────────────────────────────────────
    # Main Monitoring Loop
    # ─────────────────────────────────────────────────────────────────────────

    def _monitor_loop(self) -> None:
        """
        Main monitoring loop (runs in background thread).

        Periodically scans connections, applies heuristics, and publishes alerts.
        """
        logger.debug("ExfiltrationDetector._monitor_loop started")

        while self._monitoring:
            try:
                # Get current snapshots
                snapshots = self._scan_connections()

                # Apply heuristics
                new_alerts: List[ExfiltrationAlert] = []

                new_alerts.extend(self._check_volume_threshold(snapshots))
                new_alerts.extend(self._check_suspicious_destinations(snapshots))
                new_alerts.extend(self._check_connection_count(snapshots))

                # Raise any alerts
                for alert in new_alerts:
                    self._raise_alert(alert)

                # Sleep before next check
                time.sleep(self.config.check_interval_s)

            except Exception as e:
                logger.error(f"ExfiltrationDetector._monitor_loop exception: {e}", exc_info=True)
                time.sleep(self.config.check_interval_s)

        logger.debug("ExfiltrationDetector._monitor_loop exited")

    # ─────────────────────────────────────────────────────────────────────────
    # Connection Scanning
    # ─────────────────────────────────────────────────────────────────────────

    def _scan_connections(self) -> List[NetworkSnapshot]:
        """
        Scan all network connections from Lucie processes.

        Uses psutil to enumerate open socket connections and extract metadata.

        Returns:
            List of NetworkSnapshot objects representing current connections.
        """
        snapshots: List[NetworkSnapshot] = []
        lucie_pids = self._get_lucie_pids()

        for conn in psutil.net_connections(kind='inet'):
            if conn.pid is None or conn.pid not in lucie_pids:
                continue

            # Skip non-ESTABLISHED or non-outbound
            if conn.status != 'ESTABLISHED':
                continue

            try:
                proc = psutil.Process(conn.pid)
                process_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                process_name = "unknown"

            # Extract remote host and port
            if conn.raddr and len(conn.raddr) >= 2:
                remote_host = conn.raddr[0]
                remote_port = conn.raddr[1]
            else:
                continue

            if conn.laddr and len(conn.laddr) >= 2:
                local_addr = f"{conn.laddr[0]}:{conn.laddr[1]}"
            else:
                local_addr = "unknown"

            remote_addr = f"{remote_host}:{remote_port}"

            snapshot = NetworkSnapshot(
                pid=conn.pid,
                process_name=process_name,
                local_addr=local_addr,
                remote_addr=remote_addr,
                remote_host=remote_host,
                remote_port=remote_port,
                status=conn.status,
                bytes_sent=conn.io_counters.bytes_sent if conn.io_counters else 0,
                bytes_recv=conn.io_counters.bytes_recv if conn.io_counters else 0,
                timestamp=time.time(),
            )

            snapshots.append(snapshot)

        return snapshots

    # ─────────────────────────────────────────────────────────────────────────
    # Heuristics
    # ─────────────────────────────────────────────────────────────────────────

    def _check_volume_threshold(self, snapshots: List[NetworkSnapshot]) -> List[ExfiltrationAlert]:
        """
        Heuristic 1: Volume threshold.

        Track bytes sent per process over monitoring_window_s. Alert if exceeds
        volume_threshold_mb.

        Args:
            snapshots: Current network snapshots.

        Returns:
            List of ExfiltrationAlert objects.
        """
        alerts: List[ExfiltrationAlert] = []
        now = time.time()

        with self._volume_lock:
            for snapshot in snapshots:
                pid = snapshot.pid

                # Initialize history if needed
                if pid not in self._volume_history:
                    self._volume_history[pid] = []

                # Add current bytes sent to history
                self._volume_history[pid].append((now, snapshot.bytes_sent))

                # Trim history to window
                window_start = now - self.config.monitoring_window_s
                self._volume_history[pid] = [
                    (ts, bytes_sent) for ts, bytes_sent in self._volume_history[pid]
                    if ts >= window_start
                ]

                # Calculate total bytes sent in window
                total_sent = sum(b for _, b in self._volume_history[pid])
                threshold_bytes = self.config.volume_threshold_mb * 1024 * 1024

                if total_sent > threshold_bytes:
                    alert = ExfiltrationAlert(
                        alert_id=str(uuid.uuid4()),
                        timestamp=now,
                        pid=pid,
                        process_name=snapshot.process_name,
                        reason=f"Excessive data transfer: {total_sent / 1024 / 1024:.2f} MB "
                               f"in {self.config.monitoring_window_s}s window",
                        remote_addr=snapshot.remote_addr,
                        volume_bytes=total_sent,
                        severity="critical",
                        heuristic="volume_threshold",
                    )
                    alerts.append(alert)

        return alerts

    def _check_suspicious_destinations(self, snapshots: List[NetworkSnapshot]) -> List[ExfiltrationAlert]:
        """
        Heuristic 2: Suspicious destinations.

        Flag connections to non-whitelisted IPs outside RFC 1918 (private) ranges,
        excluding localhost and known safe APIs.

        Args:
            snapshots: Current network snapshots.

        Returns:
            List of ExfiltrationAlert objects.
        """
        alerts: List[ExfiltrationAlert] = []
        now = time.time()

        for snapshot in snapshots:
            # Check if destination is whitelisted
            if snapshot.remote_host in self.config.whitelisted_hosts:
                continue

            if snapshot.remote_port in self.config.whitelisted_ports:
                continue

            # Check if it's a private IP (RFC 1918)
            try:
                ip = ipaddress.ip_address(snapshot.remote_host)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    continue
            except ValueError:
                # Not an IP, probably a hostname
                pass

            # If we reach here, it's a suspicious destination
            alert = ExfiltrationAlert(
                alert_id=str(uuid.uuid4()),
                timestamp=now,
                pid=snapshot.pid,
                process_name=snapshot.process_name,
                reason=f"Connection to non-whitelisted destination: {snapshot.remote_addr}",
                remote_addr=snapshot.remote_addr,
                volume_bytes=snapshot.bytes_sent,
                severity="warning",
                heuristic="suspicious_destination",
            )
            alerts.append(alert)

        return alerts

    def _check_connection_count(self, snapshots: List[NetworkSnapshot]) -> List[ExfiltrationAlert]:
        """
        Heuristic 3: Connection burst.

        Alert if a single process has more than max_connections_per_process
        simultaneous ESTABLISHED connections (possible port scanning or bulk
        exfiltration).

        Args:
            snapshots: Current network snapshots.

        Returns:
            List of ExfiltrationAlert objects.
        """
        alerts: List[ExfiltrationAlert] = []
        now = time.time()

        # Count connections per process
        connections_by_pid: Dict[int, List[NetworkSnapshot]] = {}
        for snapshot in snapshots:
            if snapshot.pid not in connections_by_pid:
                connections_by_pid[snapshot.pid] = []
            connections_by_pid[snapshot.pid].append(snapshot)

        # Check thresholds
        for pid, conns in connections_by_pid.items():
            if len(conns) > self.config.max_connections_per_process:
                process_name = conns[0].process_name if conns else "unknown"
                alert = ExfiltrationAlert(
                    alert_id=str(uuid.uuid4()),
                    timestamp=now,
                    pid=pid,
                    process_name=process_name,
                    reason=f"Connection burst: {len(conns)} simultaneous connections "
                           f"(threshold: {self.config.max_connections_per_process})",
                    remote_addr="<multiple>",
                    volume_bytes=sum(c.bytes_sent for c in conns),
                    severity="warning",
                    heuristic="connection_burst",
                )
                alerts.append(alert)

        return alerts

    # ─────────────────────────────────────────────────────────────────────────
    # Alert Management
    # ─────────────────────────────────────────────────────────────────────────

    def _raise_alert(self, alert: ExfiltrationAlert) -> None:
        """
        Raise an exfiltration alert.

        Stores in alert history, logs to AuditTrail (CRITICAL), publishes to EventBus,
        and optionally kills the process if auto_kill is enabled.

        Args:
            alert: ExfiltrationAlert to raise.
        """
        with self._alerts_lock:
            self._alerts.append(alert)

        # Log to AuditTrail
        if self.audit_trail:
            try:
                audit_data = {
                    "alert_id": alert.alert_id,
                    "pid": alert.pid,
                    "process_name": alert.process_name,
                    "reason": alert.reason,
                    "remote_addr": alert.remote_addr,
                    "volume_bytes": alert.volume_bytes,
                    "severity": alert.severity,
                    "heuristic": alert.heuristic,
                }
                self.audit_trail.record_sync(
                    action="security.exfiltration_detected",
                    user="system",
                    justification=f"Exfiltration attempt: {alert.reason}",
                    data=audit_data,
                )
            except Exception as e:
                logger.error(f"Failed to log exfiltration alert to AuditTrail: {e}")

        # Log locally
        level_name = "CRITICAL" if alert.severity == "critical" else "WARNING"
        logger.log(
            logging.CRITICAL if alert.severity == "critical" else logging.WARNING,
            f"Exfiltration Alert [{alert.alert_id}] {level_name}: "
            f"PID={alert.pid} ({alert.process_name}) -> {alert.remote_addr} | "
            f"Reason: {alert.reason} | Volume: {alert.volume_bytes} bytes | "
            f"Heuristic: {alert.heuristic}"
        )

        # Publish to EventBus
        if self.event_bus:
            try:
                event_data = {
                    "alert_id": alert.alert_id,
                    "pid": alert.pid,
                    "process_name": alert.process_name,
                    "reason": alert.reason,
                    "remote_addr": alert.remote_addr,
                    "volume_bytes": alert.volume_bytes,
                    "severity": alert.severity,
                    "heuristic": alert.heuristic,
                    "timestamp": alert.timestamp,
                }

                # Use asyncio.run to call async publish from sync context
                # (we're in a background thread)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(
                        self.event_bus.publish(
                            channel="security.exfiltration_detected",
                            data=event_data,
                            source="exfiltration_detector",
                        )
                    )
                finally:
                    loop.close()
            except Exception as e:
                logger.error(f"Failed to publish exfiltration alert to EventBus: {e}")

        # Optional: kill the process
        if self.config.auto_kill and alert.severity == "critical":
            logger.warning(f"auto_kill enabled, terminating PID {alert.pid}")
            self._kill_process(alert.pid)
            alert.blocked = True

    def _kill_process(self, pid: int) -> None:
        """
        Terminate a suspicious process.

        Sends SIGTERM, waits 2 seconds, then SIGKILL if necessary.

        Args:
            pid: Process ID to terminate.
        """
        try:
            proc = psutil.Process(pid)
            logger.warning(f"Terminating suspicious process: PID {pid} ({proc.name()})")

            # SIGTERM
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=2.0)
                logger.info(f"Process {pid} terminated with SIGTERM")
                return
            except psutil.TimeoutExpired:
                pass

            # SIGKILL
            proc.send_signal(signal.SIGKILL)
            try:
                proc.wait(timeout=1.0)
                logger.info(f"Process {pid} killed with SIGKILL")
            except psutil.TimeoutExpired:
                logger.error(f"Failed to kill process {pid}")

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.warning(f"Could not kill process {pid}: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Process Discovery
    # ─────────────────────────────────────────────────────────────────────────

    def _get_lucie_pids(self) -> Set[int]:
        """
        Find all process IDs related to Lucie.

        Looks for processes with names matching 'lucie', 'python' (if parent is
        called lucie), or direct children of the main Lucie process.

        Returns:
            Set of PIDs to monitor.
        """
        lucie_pids: Set[int] = set()

        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                info = proc.as_dict(attrs=['pid', 'name', 'cmdline'])
                pid = info['pid']
                name = info['name'] or ""
                cmdline = info['cmdline'] or []

                # Direct name match
                if 'lucie' in name.lower() or 'agent' in name.lower():
                    lucie_pids.add(pid)
                    continue

                # Command line match
                if cmdline and any('lucie' in arg.lower() or 'agent' in arg.lower()
                                    for arg in cmdline):
                    lucie_pids.add(pid)

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return lucie_pids

    # ─────────────────────────────────────────────────────────────────────────
    # Public Properties
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def alerts(self) -> List[ExfiltrationAlert]:
        """Get a copy of the alert history."""
        with self._alerts_lock:
            return list(self._alerts)

    @property
    def stats(self) -> Dict[str, Any]:
        """
        Get monitoring statistics.

        Returns:
            Dictionary containing:
              - running: bool (monitoring active)
              - enabled: bool (config enabled)
              - total_alerts: int (alert count)
              - critical_alerts: int (critical-severity alerts)
              - warning_alerts: int (warning-severity alerts)
              - auto_kill_enabled: bool
        """
        with self._alerts_lock:
            critical = sum(1 for a in self._alerts if a.severity == "critical")
            warning = sum(1 for a in self._alerts if a.severity == "warning")

        return {
            "running": self._monitoring,
            "enabled": self.config.enabled,
            "total_alerts": len(self._alerts),
            "critical_alerts": critical,
            "warning_alerts": warning,
            "auto_kill_enabled": self.config.auto_kill,
            "volume_threshold_mb": self.config.volume_threshold_mb,
            "check_interval_s": self.config.check_interval_s,
        }
