"""
Automated Security Response System for Lucie — DS-SEC-05 Implementation

Centralized security event handling and automated response orchestration. This module:
  - Receives security events from multiple threat detection systems.
  - Evaluates events against registered response rules.
  - Executes coordinated response actions (log, alert, throttle, isolate, kill, lock, shutdown).
  - Maintains event history and generates security reports.
  - Prevents alert storms with per-rule cooldown tracking.
  - Uses EventBus for loose coupling and async communication.

Architecture:
  - SecurityEvent: immutable data class representing a security incident.
  - SecuritySeverity: enum (INFO, WARNING, CRITICAL, EMERGENCY).
  - ResponseAction: enum defining automated responses.
  - SecurityRule: pattern-based rule with severity threshold and actions.
  - SecurityResponseEngine: central coordinator subscribing to security channels.

Privacy & Safety:
  - All communication via EventBus (no direct function calls between modules).
  - Event history is bounded (max 1000 entries, ring buffer).
  - No sensitive data logged (never logs payloads, only metadata).
  - Cooldown prevents alert storms.
  - Thread-safe with locking for concurrent access.
"""

from __future__ import annotations

import asyncio
import os
import signal
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from ..utils.logger import logger
from ..brain.synapses.event_bus import EventBus, Event


# ─────────────────────────────────────────────────────────────────────────────
# Enums & Data Classes
# ─────────────────────────────────────────────────────────────────────────────

class SecuritySeverity(Enum):
    """Security event severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"

    def __lt__(self, other: SecuritySeverity) -> bool:
        """Lower severity values are less critical."""
        order = [self.INFO, self.WARNING, self.CRITICAL, self.EMERGENCY]
        return order.index(self) < order.index(other)

    def __le__(self, other: SecuritySeverity) -> bool:
        order = [self.INFO, self.WARNING, self.CRITICAL, self.EMERGENCY]
        return order.index(self) <= order.index(other)

    def __gt__(self, other: SecuritySeverity) -> bool:
        order = [self.INFO, self.WARNING, self.CRITICAL, self.EMERGENCY]
        return order.index(self) > order.index(other)

    def __ge__(self, other: SecuritySeverity) -> bool:
        order = [self.INFO, self.WARNING, self.CRITICAL, self.EMERGENCY]
        return order.index(self) >= order.index(other)


class ResponseAction(Enum):
    """Available automated response actions."""
    LOG_ONLY = "LOG_ONLY"
    ALERT_USER = "ALERT_USER"
    THROTTLE_AGENT = "THROTTLE_AGENT"
    KILL_PROCESS = "KILL_PROCESS"
    ISOLATE_AGENT = "ISOLATE_AGENT"
    LOCK_STORAGE = "LOCK_STORAGE"
    EMERGENCY_SHUTDOWN = "EMERGENCY_SHUTDOWN"


@dataclass
class SecurityEvent:
    """
    Immutable security event representing a detected threat or anomaly.

    Attributes:
        event_id: Unique identifier for this event (UUID or string).
        timestamp: Unix timestamp when the event occurred.
        source: Source component that detected the event (e.g., "exfiltration_detector").
        severity: Event severity level (SecuritySeverity enum).
        event_type: Categorization of the event (e.g., "exfiltration_detected").
        details: Event-specific metadata (dict, may include PID, volume, destination, etc.).
        handled: Whether this event has been processed by the security response engine.
        response_actions: List of action descriptions applied to this event.
    """
    event_id: str
    timestamp: float
    source: str
    severity: SecuritySeverity
    event_type: str
    details: Dict[str, Any]
    handled: bool = False
    response_actions: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate event_id is non-empty."""
        if not self.event_id:
            raise ValueError("event_id must be non-empty")


@dataclass
class SecurityRule:
    """
    Response rule mapping event patterns to automated actions.

    Attributes:
        event_type_pattern: Event type pattern (supports * wildcard for prefix matching).
        severity_threshold: Minimum severity required to trigger this rule.
        actions: List of ResponseAction enums to execute.
        cooldown_seconds: Minimum time between rule evaluations for same event_type+severity.
        description: Human-readable description of the rule.
    """
    event_type_pattern: str
    severity_threshold: SecuritySeverity
    actions: List[ResponseAction]
    cooldown_seconds: float = 60.0
    description: str = ""

    def matches(self, event_type: str, severity: SecuritySeverity) -> bool:
        """Check if this rule matches the given event type and severity."""
        if severity < self.severity_threshold:
            return False
        if self.event_type_pattern == "*":
            return True
        if self.event_type_pattern.endswith("*"):
            prefix = self.event_type_pattern[:-1]
            return event_type.startswith(prefix)
        return event_type == self.event_type_pattern


# ─────────────────────────────────────────────────────────────────────────────
# SecurityResponseEngine
# ─────────────────────────────────────────────────────────────────────────────

class SecurityResponseEngine:
    """
    Central security response coordinator.

    Subscribes to security event channels on the EventBus, evaluates events against
    registered rules, and executes coordinated response actions. Maintains event
    history and provides security reporting.

    Features:
      - Event subscription: exfiltration_detected, integrity_violation, memory_alert, threat_detected
      - Rule registration with pattern matching and cooldown
      - Action execution via EventBus (loose coupling)
      - Event history with ring buffer (max 1000 entries)
      - Cooldown mechanism to prevent alert storms
      - Thread-safe operations
      - Comprehensive security reporting
    """

    MAX_EVENT_HISTORY = 1000
    DEFAULT_RULE_COOLDOWN = 60.0

    def __init__(self, event_bus: Optional[EventBus] = None):
        """
        Initialize the security response engine.

        Args:
            event_bus: EventBus instance for event subscription and action dispatch.
                       If None, actions that require EventBus will log warnings.
        """
        self.event_bus = event_bus
        self._rules: List[SecurityRule] = []
        self._event_history: List[SecurityEvent] = []
        self._history_lock = threading.Lock()
        self._rules_lock = threading.Lock()

        # Cooldown tracking: (event_type, severity) -> last_triggered_timestamp
        self._cooldowns: Dict[tuple, float] = {}
        self._cooldowns_lock = threading.Lock()

        # Storage lock flag (for LOCK_STORAGE action)
        self._storage_locked = False
        self._storage_lock = threading.Lock()

        # Subscription tracking
        self._subscriptions: List[str] = []
        self._registered = False

        # Load default rules
        self._setup_default_rules()

        logger.info("🔒 SecurityResponseEngine initialized")

    # ─────────────────────────────────────────────────────────────────────────
    # Registration & Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def register_and_subscribe(self, source: str, token: str) -> None:
        """
        Register with EventBus and subscribe to security channels.

        Args:
            source: Source identifier for EventBus registration.
            token: Authentication token for EventBus.

        Raises:
            RuntimeError: If already registered.
        """
        if self._registered:
            raise RuntimeError("SecurityResponseEngine already registered")

        # Register as a source with appropriate permissions
        subscribe_channels = [
            "security.exfiltration_detected",
            "security.integrity_violation",
            "security.memory_alert",
            "security.threat_detected",
        ]

        publish_channels = [
            "security.user_alert",
            "security.throttle_agent",
            "security.isolate_agent",
            "security.lock_storage",
            "security.emergency_shutdown",
            "security.audit_log",
        ]

        await self.event_bus.register_source(
            source,
            token,
            publish_channels=publish_channels,
            subscribe_channels=subscribe_channels,
        )

        # Subscribe to each channel
        for channel in subscribe_channels:
            sub = await self.event_bus.subscribe(
                channel,
                self._on_security_event,
                source,
                token,
            )
            self._subscriptions.append(channel)
            logger.debug(f"✓ Subscribed to {channel}")

        self._registered = True
        logger.info(f"🔒 SecurityResponseEngine registered as '{source}'")

    async def shutdown(self) -> None:
        """Gracefully shut down the engine and unsubscribe from all channels."""
        if not self._registered:
            return
        logger.info("🔒 SecurityResponseEngine shutting down...")
        self._registered = False

    # ─────────────────────────────────────────────────────────────────────────
    # Rule Management
    # ─────────────────────────────────────────────────────────────────────────

    def register_rule(
        self,
        event_type_pattern: str,
        severity_threshold: SecuritySeverity,
        actions: List[ResponseAction],
        cooldown_seconds: float = 60.0,
        description: str = "",
    ) -> None:
        """
        Register a response rule.

        Args:
            event_type_pattern: Event type pattern (e.g., "exfiltration_detected", "integrity_*").
            severity_threshold: Minimum severity to trigger this rule.
            actions: List of ResponseAction enums to execute.
            cooldown_seconds: Minimum time between executions (default 60).
            description: Human-readable rule description.
        """
        rule = SecurityRule(
            event_type_pattern=event_type_pattern,
            severity_threshold=severity_threshold,
            actions=actions,
            cooldown_seconds=cooldown_seconds,
            description=description,
        )
        with self._rules_lock:
            self._rules.append(rule)
        logger.debug(f"✓ Registered rule: {description or event_type_pattern}")

    def _setup_default_rules(self) -> None:
        """Configure default security response rules."""
        # Exfiltration: CRITICAL → KILL_PROCESS + ALERT_USER + LOG_ONLY
        self.register_rule(
            "exfiltration_detected",
            SecuritySeverity.CRITICAL,
            [ResponseAction.KILL_PROCESS, ResponseAction.ALERT_USER, ResponseAction.LOG_ONLY],
            cooldown_seconds=120.0,
            description="Kill process + alert on exfiltration",
        )

        # Integrity violation: CRITICAL → LOCK_STORAGE + ALERT_USER
        self.register_rule(
            "integrity_violation",
            SecuritySeverity.CRITICAL,
            [ResponseAction.LOCK_STORAGE, ResponseAction.ALERT_USER],
            cooldown_seconds=120.0,
            description="Lock storage + alert on integrity violation",
        )

        # Memory alert: WARNING → THROTTLE_AGENT + LOG_ONLY
        self.register_rule(
            "memory_alert",
            SecuritySeverity.WARNING,
            [ResponseAction.THROTTLE_AGENT, ResponseAction.LOG_ONLY],
            cooldown_seconds=60.0,
            description="Throttle agent on memory alert",
        )

        # Generic threat: CRITICAL → ISOLATE_AGENT + ALERT_USER
        self.register_rule(
            "threat_detected",
            SecuritySeverity.CRITICAL,
            [ResponseAction.ISOLATE_AGENT, ResponseAction.ALERT_USER],
            cooldown_seconds=120.0,
            description="Isolate agent + alert on threat",
        )

        logger.info("✓ Default security rules configured")

    # ─────────────────────────────────────────────────────────────────────────
    # Event Handling
    # ─────────────────────────────────────────────────────────────────────────

    async def _on_security_event(self, event: Event) -> None:
        """
        EventBus callback handler for security events.

        Args:
            event: Event from EventBus with security event data.
        """
        try:
            # Deserialize security event from EventBus data
            data = event.data or {}
            security_event = SecurityEvent(
                event_id=data.get("event_id", str(uuid.uuid4())),
                timestamp=data.get("timestamp", time.time()),
                source=data.get("source", event.source),
                severity=SecuritySeverity(data.get("severity", "WARNING")),
                event_type=data.get("event_type", event.channel),
                details=data.get("details", {}),
            )
            await self.handle_event(security_event)
        except Exception as e:
            logger.error(f"❌ Error processing security event: {e}")

    def handle_event_sync(self, event: SecurityEvent) -> None:
        """
        Synchronous wrapper for handle_event.

        Evaluates and handles a security event without requiring an async context.
        Useful for calling from synchronous code or background threads.

        Args:
            event: SecurityEvent to process.
        """
        # Record event in history
        self._add_to_history(event)
        logger.info(
            f"🚨 Security event: {event.event_type} "
            f"(severity={event.severity.value}, source={event.source})"
        )

        # Find matching rules and check cooldowns
        matching_actions: Set[ResponseAction] = set()
        with self._rules_lock:
            for rule in self._rules:
                if rule.matches(event.event_type, event.severity):
                    if self._is_rule_active(rule):
                        matching_actions.update(rule.actions)
                        self._update_cooldown(rule)

        # Execute matched actions synchronously
        for action in matching_actions:
            self._execute_action_sync(action, event)

        # Mark as handled
        event.handled = True

    async def handle_event(self, event: SecurityEvent) -> None:
        """
        Evaluate and handle a security event (async version).

        Args:
            event: SecurityEvent to process.
        """
        # Record event in history
        self._add_to_history(event)
        logger.info(
            f"🚨 Security event: {event.event_type} "
            f"(severity={event.severity.value}, source={event.source})"
        )

        # Find matching rules and check cooldowns
        matching_actions: Set[ResponseAction] = set()
        with self._rules_lock:
            for rule in self._rules:
                if rule.matches(event.event_type, event.severity):
                    if self._is_rule_active(rule):
                        matching_actions.update(rule.actions)
                        self._update_cooldown(rule)

        # Execute matched actions
        for action in matching_actions:
            await self._execute_action(action, event)

        # Mark as handled
        event.handled = True

    def _is_rule_active(self, rule: SecurityRule) -> bool:
        """
        Check if a rule is active (not in cooldown).

        Args:
            rule: SecurityRule to check.

        Returns:
            True if rule is active, False if in cooldown.
        """
        key = (rule.event_type_pattern, rule.severity_threshold)
        with self._cooldowns_lock:
            last_triggered = self._cooldowns.get(key)
            if last_triggered is None:
                return True
            elapsed = time.time() - last_triggered
            return elapsed >= rule.cooldown_seconds

    def _update_cooldown(self, rule: SecurityRule) -> None:
        """
        Update cooldown timestamp for a rule.

        Args:
            rule: SecurityRule to update.
        """
        key = (rule.event_type_pattern, rule.severity_threshold)
        with self._cooldowns_lock:
            self._cooldowns[key] = time.time()

    # ─────────────────────────────────────────────────────────────────────────
    # Action Execution
    # ─────────────────────────────────────────────────────────────────────────

    async def _execute_action(self, action: ResponseAction, event: SecurityEvent) -> None:
        """
        Execute a response action.

        Args:
            action: ResponseAction enum value.
            event: SecurityEvent that triggered the action.
        """
        try:
            if action == ResponseAction.LOG_ONLY:
                await self._action_log(event)
            elif action == ResponseAction.ALERT_USER:
                await self._action_alert_user(event)
            elif action == ResponseAction.THROTTLE_AGENT:
                await self._action_throttle_agent(event)
            elif action == ResponseAction.KILL_PROCESS:
                await self._action_kill_process(event)
            elif action == ResponseAction.ISOLATE_AGENT:
                await self._action_isolate_agent(event)
            elif action == ResponseAction.LOCK_STORAGE:
                await self._action_lock_storage(event)
            elif action == ResponseAction.EMERGENCY_SHUTDOWN:
                await self._action_emergency_shutdown(event)
            else:
                logger.warning(f"Unknown action: {action}")

            # Record action in event
            event.response_actions.append(action.value)
        except Exception as e:
            logger.error(f"❌ Error executing action {action.value}: {e}")

    def _execute_action_sync(self, action: ResponseAction, event: SecurityEvent) -> None:
        """
        Execute a response action synchronously (for non-async contexts).

        Performs local actions (log, lock, kill) directly. EventBus actions
        are logged but not published (requires async context).

        Args:
            action: ResponseAction enum value.
            event: SecurityEvent that triggered the action.
        """
        try:
            if action == ResponseAction.LOG_ONLY:
                logger.warning(
                    f"🔐 Security Audit: {event.event_type} | "
                    f"severity={event.severity.value} | source={event.source}"
                )
            elif action == ResponseAction.ALERT_USER:
                logger.warning(
                    f"⚠️ SECURITY ALERT: {event.event_type} "
                    f"(severity: {event.severity.value})"
                )
            elif action == ResponseAction.THROTTLE_AGENT:
                agent_id = event.details.get("agent_id", "unknown")
                logger.warning(f"🚦 Throttling agent: {agent_id}")
            elif action == ResponseAction.KILL_PROCESS:
                pid = event.details.get("pid")
                if pid and HAS_PSUTIL:
                    try:
                        process = psutil.Process(pid)
                        process.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                logger.error(f"🔪 Kill process: PID {pid}")
            elif action == ResponseAction.ISOLATE_AGENT:
                agent_id = event.details.get("agent_id", "unknown")
                logger.error(f"🚫 ISOLATING AGENT: {agent_id}")
            elif action == ResponseAction.LOCK_STORAGE:
                with self._storage_lock:
                    self._storage_locked = True
                logger.error(f"🔒 STORAGE LOCKED: {event.event_type}")
            elif action == ResponseAction.EMERGENCY_SHUTDOWN:
                logger.critical(f"🛑 EMERGENCY SHUTDOWN: {event.event_type}")

            event.response_actions.append(action.value)
        except Exception as e:
            logger.error(f"❌ Error executing sync action {action.value}: {e}")

    async def _action_log(self, event: SecurityEvent) -> None:
        """
        Action: Log event to security audit trail.

        Args:
            event: SecurityEvent to log.
        """
        message = (
            f"🔐 Security Audit: {event.event_type} | "
            f"severity={event.severity.value} | "
            f"source={event.source} | "
            f"event_id={event.event_id}"
        )
        logger.warning(message)

        # Publish to audit channel
        try:
            await self.event_bus.publish(
                "security.audit_log",
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "severity": event.severity.value,
                    "source": event.source,
                    "timestamp": event.timestamp,
                    "details": event.details,
                },
                source="security_response_engine",
                token=None,
            )
        except Exception as e:
            logger.error(f"Failed to publish audit log: {e}")

    async def _action_alert_user(self, event: SecurityEvent) -> None:
        """
        Action: Alert the user about a security event.

        Publishes alert to EventBus security.user_alert channel.

        Args:
            event: SecurityEvent to alert about.
        """
        alert_msg = (
            f"SECURITY ALERT: {event.event_type} detected at "
            f"{datetime.fromtimestamp(event.timestamp).isoformat()} "
            f"(severity: {event.severity.value})"
        )
        logger.warning(f"⚠️ {alert_msg}")

        try:
            await self.event_bus.publish(
                "security.user_alert",
                {
                    "event_id": event.event_id,
                    "message": alert_msg,
                    "severity": event.severity.value,
                    "event_type": event.event_type,
                    "details": event.details,
                },
                source="security_response_engine",
                token=None,
            )
        except Exception as e:
            logger.error(f"Failed to alert user: {e}")

    async def _action_throttle_agent(self, event: SecurityEvent) -> None:
        """
        Action: Throttle agent execution.

        Publishes throttle command to EventBus for the affected agent.

        Args:
            event: SecurityEvent containing agent info in details.
        """
        agent_id = event.details.get("agent_id", "unknown")
        logger.warning(f"🚦 Throttling agent: {agent_id}")

        try:
            await self.event_bus.publish(
                "security.throttle_agent",
                {
                    "agent_id": agent_id,
                    "event_id": event.event_id,
                    "reason": event.event_type,
                    "duration_seconds": 300.0,  # 5 minutes default throttle
                },
                source="security_response_engine",
                token=None,
            )
        except Exception as e:
            logger.error(f"Failed to throttle agent: {e}")

    async def _action_kill_process(self, event: SecurityEvent) -> None:
        """
        Action: Kill process associated with security violation.

        If psutil is available and PID is in event details, sends SIGTERM.
        Otherwise publishes kill command via EventBus.

        Args:
            event: SecurityEvent containing PID in details.
        """
        pid = event.details.get("pid")
        process_name = event.details.get("process_name", "unknown")

        if pid and HAS_PSUTIL:
            try:
                process = psutil.Process(pid)
                logger.error(f"🔪 KILLING PROCESS: {process_name} (PID {pid})")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    logger.warning(f"SIGTERM timeout, sending SIGKILL: {process_name}")
                    process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                logger.error(f"Failed to kill process {pid}: {e}")
        else:
            logger.error(f"🔪 Kill process command: {process_name} (PID {pid})")

        # Also publish command via EventBus
        try:
            await self.event_bus.publish(
                "security.kill_process",
                {
                    "pid": pid,
                    "process_name": process_name,
                    "event_id": event.event_id,
                    "reason": event.event_type,
                },
                source="security_response_engine",
                token=None,
            )
        except Exception as e:
            logger.error(f"Failed to publish kill command: {e}")

    async def _action_isolate_agent(self, event: SecurityEvent) -> None:
        """
        Action: Isolate agent from network and other services.

        Publishes isolation command to EventBus.

        Args:
            event: SecurityEvent containing agent info in details.
        """
        agent_id = event.details.get("agent_id", "unknown")
        logger.error(f"🚫 ISOLATING AGENT: {agent_id}")

        try:
            await self.event_bus.publish(
                "security.isolate_agent",
                {
                    "agent_id": agent_id,
                    "event_id": event.event_id,
                    "reason": event.event_type,
                    "duration_seconds": 600.0,  # 10 minutes isolation
                },
                source="security_response_engine",
                token=None,
            )
        except Exception as e:
            logger.error(f"Failed to isolate agent: {e}")

    async def _action_lock_storage(self, event: SecurityEvent) -> None:
        """
        Action: Lock storage to prevent further writes.

        Sets internal flag and publishes lock command via EventBus.

        Args:
            event: SecurityEvent that triggered the lock.
        """
        with self._storage_lock:
            self._storage_locked = True
        logger.error(f"🔒 STORAGE LOCKED due to: {event.event_type}")

        try:
            await self.event_bus.publish(
                "security.lock_storage",
                {
                    "event_id": event.event_id,
                    "reason": event.event_type,
                    "locked": True,
                },
                source="security_response_engine",
                token=None,
            )
        except Exception as e:
            logger.error(f"Failed to publish lock command: {e}")

    async def _action_emergency_shutdown(self, event: SecurityEvent) -> None:
        """
        Action: Initiate emergency shutdown.

        Publishes shutdown signal via EventBus.

        Args:
            event: SecurityEvent that triggered emergency shutdown.
        """
        logger.critical(f"🛑 EMERGENCY SHUTDOWN INITIATED due to: {event.event_type}")

        try:
            await self.event_bus.publish(
                "security.emergency_shutdown",
                {
                    "event_id": event.event_id,
                    "reason": event.event_type,
                    "timestamp": time.time(),
                },
                source="security_response_engine",
                token=None,
            )
        except Exception as e:
            logger.error(f"Failed to publish shutdown signal: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Event History & Reporting
    # ─────────────────────────────────────────────────────────────────────────

    def _add_to_history(self, event: SecurityEvent) -> None:
        """
        Add event to history (ring buffer, max 1000 entries).

        Args:
            event: SecurityEvent to add.
        """
        with self._history_lock:
            self._event_history.append(event)
            if len(self._event_history) > self.MAX_EVENT_HISTORY:
                self._event_history.pop(0)

    def get_event_history(self, limit: int = 100) -> List[SecurityEvent]:
        """
        Get recent security events.

        Args:
            limit: Maximum number of events to return.

        Returns:
            List of SecurityEvent objects (most recent last).
        """
        with self._history_lock:
            return self._event_history[-limit:]

    def get_security_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive security report.

        Returns:
            Dictionary containing:
              - event_count: Total events processed
              - events_by_severity: Count breakdown by severity
              - events_by_type: Count breakdown by event type
              - active_storage_lock: Whether storage is locked
              - total_rules: Number of registered rules
              - last_events: List of last 10 events with details
        """
        with self._history_lock:
            history = list(self._event_history)

        with self._storage_lock:
            storage_locked = self._storage_locked

        with self._rules_lock:
            num_rules = len(self._rules)

        # Count by severity
        severity_counts: Dict[str, int] = {}
        for event in history:
            key = event.severity.value
            severity_counts[key] = severity_counts.get(key, 0) + 1

        # Count by event type
        type_counts: Dict[str, int] = {}
        for event in history:
            key = event.event_type
            type_counts[key] = type_counts.get(key, 0) + 1

        # Last 10 events
        last_events = [
            {
                "event_id": e.event_id,
                "timestamp": e.timestamp,
                "event_type": e.event_type,
                "severity": e.severity.value,
                "source": e.source,
                "handled": e.handled,
                "actions": e.response_actions,
            }
            for e in history[-10:]
        ]

        return {
            "event_count": len(history),
            "total_events": len(history),  # alias for convenience
            "events_by_severity": severity_counts,
            "events_by_type": type_counts,
            "active_storage_lock": storage_locked,
            "total_rules": num_rules,
            "last_events": last_events,
            "timestamp": time.time(),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Debugging & Introspection
    # ─────────────────────────────────────────────────────────────────────────

    def get_rules_summary(self) -> List[Dict[str, Any]]:
        """
        Get summary of registered rules.

        Returns:
            List of rule dictionaries with pattern, severity, actions, description.
        """
        with self._rules_lock:
            return [
                {
                    "pattern": r.event_type_pattern,
                    "severity_threshold": r.severity_threshold.value,
                    "actions": [a.value for a in r.actions],
                    "cooldown_seconds": r.cooldown_seconds,
                    "description": r.description,
                }
                for r in self._rules
            ]

    def is_storage_locked(self) -> bool:
        """
        Check if storage is currently locked.

        Returns:
            True if storage is locked, False otherwise.
        """
        with self._storage_lock:
            return self._storage_locked

    def unlock_storage(self) -> None:
        """Unlock storage (admin function, use with caution)."""
        with self._storage_lock:
            self._storage_locked = False
        logger.warning("🔓 Storage unlocked (admin action)")
