"""
BrainFeedService — Orchestrateur du flux de pensées de Lucie.

Connecte :
- EventBus (événements internes) → ThoughtStream → NotificationBridge
- AccessibilityMonitor (contexte utilisateur)
- InputActivityMonitor (état d'activité)

Single Responsibility : transformer les événements bruts en
pensées structurées et les publier vers l'UI.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from .models import ThoughtEntry, ThoughtType, ThoughtPriority
from .stream import ThoughtStream
from .bridge import NotificationBridge
from .accessibility import AccessibilityMonitor, FocusContext
from .input_monitor import InputActivityMonitor, ActivityState

from ...brain.synapses.event_bus import EventBus, Event
from ...utils.logger import logger


class BrainFeedService:
    """
    Service central du Brain Feed.

    Lifecycle :
    1. __init__() — crée les composants
    2. start(event_bus) — connecte à l'EventBus et démarre les monitors
    3. ... fonctionne en continu ...
    4. stop() — arrêt propre

    Throttling intelligent :
    - Si utilisateur en TYPING_BURST → réduit les pensées NORMAL à WHISPER
    - Si utilisateur AWAY → accumule et résume au retour
    - Si utilisateur ACTIVE → flux normal
    """

    _CHANNELS = [
        "routing.decision",
        "agent.start",
        "agent.step",
        "agent.done",
        "agent.error",
        "thinking.start",
        "thinking.done",
        "system.energy",
        "system.memory",
    ]

    def __init__(self) -> None:
        self._stream = ThoughtStream(capacity=200)
        self._bridge = NotificationBridge(max_rate=30)
        self._ax_monitor = AccessibilityMonitor()
        self._input_monitor = InputActivityMonitor()
        self._event_bus: Optional[EventBus] = None
        self._running = False
        self._source_token: Optional[str] = None

        self._stream.add_listener(self._on_new_thought)

    async def start(self, event_bus: EventBus) -> None:
        """Connecte le service à l'EventBus et démarre les monitors."""
        if self._running:
            return

        self._event_bus = event_bus
        self._running = True

        # S'abonner aux canaux
        for channel in self._CHANNELS:
            try:
                await event_bus.subscribe(channel, self._on_event)
            except Exception as e:
                logger.debug(f"BrainFeed subscribe {channel}: {e}")

        # Démarrer les monitors natifs
        self._ax_monitor.start()
        self._input_monitor.start()

        self._ax_monitor.add_listener(self._on_focus_change)
        self._input_monitor.add_listener(self._on_activity_change)

        self._emit(ThoughtEntry(
            thought_type=ThoughtType.SYSTEM,
            priority=ThoughtPriority.NORMAL,
            text="Brain Feed actif — je partage mes pensées en temps réel",
            agent="system",
        ))

        logger.info("BrainFeedService démarré")

    async def stop(self) -> None:
        """Arrêt propre de tous les composants."""
        if not self._running:
            return
        self._running = False

        self._ax_monitor.stop()
        self._input_monitor.stop()
        self._bridge.shutdown()

        logger.info("BrainFeedService arrêté")

    # ── Transformation EventBus → ThoughtEntry ──────────────────

    async def _on_event(self, event: Event) -> None:
        """Callback EventBus — transforme un Event en ThoughtEntry."""
        if not self._running:
            return

        try:
            thought = self._transform_event(event)
            if thought:
                thought = self._adjust_priority(thought)
                self._emit(thought)
        except Exception as e:
            logger.debug(f"BrainFeed event transform error: {e}")

    def _transform_event(self, event: Event) -> Optional[ThoughtEntry]:
        """Transforme un Event brut en ThoughtEntry lisible."""
        channel = event.channel
        data = event.data if isinstance(event.data, dict) else {}

        if channel == "routing.decision":
            agent = data.get("agent", "?")
            confidence = data.get("confidence", 0)
            via_fast = data.get("via_fast_path", False)
            path_type = "Fast Path" if via_fast else "LLM"
            return ThoughtEntry(
                thought_type=ThoughtType.ROUTING,
                priority=ThoughtPriority.NORMAL,
                agent="router",
                text=f"Routage → {agent} ({path_type})",
                detail=f"Confiance: {confidence:.1%}",
                confidence=confidence,
                latency_ms=data.get("latency_ms", 0),
            )

        if channel == "agent.start":
            agent = data.get("agent", "?")
            return ThoughtEntry(
                thought_type=ThoughtType.AGENT_START,
                priority=ThoughtPriority.NORMAL,
                agent=agent,
                text=f"Agent {agent} activé",
                detail=data.get("reason", ""),
            )

        if channel == "agent.step":
            agent = data.get("agent", "?")
            step = data.get("step", "")
            return ThoughtEntry(
                thought_type=ThoughtType.AGENT_STEP,
                priority=ThoughtPriority.MURMUR,
                agent=agent,
                text=f"{agent}: {step}",
            )

        if channel == "agent.done":
            agent = data.get("agent", "?")
            latency = data.get("latency_ms", 0)
            return ThoughtEntry(
                thought_type=ThoughtType.AGENT_DONE,
                priority=ThoughtPriority.NORMAL,
                agent=agent,
                text=f"Agent {agent} terminé",
                latency_ms=latency,
                detail=f"Durée: {latency:.0f}ms",
            )

        if channel == "agent.error":
            agent = data.get("agent", "?")
            error = data.get("error", "erreur inconnue")
            return ThoughtEntry(
                thought_type=ThoughtType.ERROR,
                priority=ThoughtPriority.IMPORTANT,
                agent=agent,
                text=f"{agent}: {error[:80]}",
                detail=data.get("traceback", ""),
            )

        if channel == "thinking.start":
            return ThoughtEntry(
                thought_type=ThoughtType.THINKING,
                priority=ThoughtPriority.MURMUR,
                agent="llm",
                text="Réflexion en cours...",
            )

        if channel == "thinking.done":
            tokens = data.get("tokens", 0)
            latency = data.get("latency_ms", 0)
            return ThoughtEntry(
                thought_type=ThoughtType.THINKING,
                priority=ThoughtPriority.NORMAL,
                agent="llm",
                text=f"Réflexion terminée ({tokens} tokens)",
                latency_ms=latency,
            )

        if channel.startswith("system."):
            return ThoughtEntry(
                thought_type=ThoughtType.SYSTEM,
                priority=ThoughtPriority.WHISPER,
                agent="system",
                text=str(data.get("message", channel)),
            )

        return None

    def _adjust_priority(self, thought: ThoughtEntry) -> ThoughtEntry:
        """Ajuste la priorité selon l'état d'activité utilisateur."""
        activity = self._input_monitor.state

        if activity == ActivityState.TYPING_BURST:
            if thought.priority == ThoughtPriority.NORMAL:
                return ThoughtEntry(
                    id=thought.id,
                    timestamp=thought.timestamp,
                    thought_type=thought.thought_type,
                    priority=ThoughtPriority.WHISPER,
                    agent=thought.agent,
                    text=thought.text,
                    detail=thought.detail,
                    confidence=thought.confidence,
                    latency_ms=thought.latency_ms,
                    metadata=thought.metadata,
                )

        return thought

    def _emit(self, thought: ThoughtEntry) -> None:
        """Envoie une pensée dans le stream (→ bridge → UI)."""
        self._stream.push(thought)

    def _on_new_thought(self, thought: ThoughtEntry) -> None:
        """Callback stream → bridge."""
        self._bridge.publish(thought)

    def _on_focus_change(self, focus: FocusContext) -> None:
        """Réagir aux changements de focus utilisateur."""
        self._emit(ThoughtEntry(
            thought_type=ThoughtType.CONTEXT,
            priority=ThoughtPriority.WHISPER,
            agent="accessibility",
            text=f"Focus: {focus.app_name} ({focus.domain})",
            metadata={"bundle_id": focus.app_bundle_id},
        ))

    def _on_activity_change(self, state: ActivityState) -> None:
        """Réagir aux changements d'état d'activité."""
        if state == ActivityState.IDLE:
            self._bridge.publish_state("idle")
        elif state == ActivityState.AWAY:
            self._bridge.publish_state("away")
            self._emit(ThoughtEntry(
                thought_type=ThoughtType.SYSTEM,
                priority=ThoughtPriority.MURMUR,
                agent="system",
                text="Utilisateur absent — mode proactif",
            ))
        elif state == ActivityState.ACTIVE:
            self._bridge.publish_state("active")

    @property
    def stream(self) -> ThoughtStream:
        return self._stream

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "stream_size": self._stream.size,
            "stream_version": self._stream.version,
            "bridge": self._bridge.stats,
            "activity": self._input_monitor.state.value,
            "focus": self._ax_monitor.current_focus.app_name,
            "running": self._running,
        }
