"""
Agent Cybernétique — Système immunitaire de Lucie.
Surveille les erreurs, détecte les menaces, place en quarantaine et archive les signatures.

Corrections v3 :
  - MetricsCollector supprimé → compteurs Prometheus directs (cyber_errors_detected, etc.)
  - publish sur None corrigé → variable locale 'event_bus' pour type-narrowing Pylance
  - _subscribe() async avec token et source
  - stop() async
  - Handlers _on_*() : signature (event: Event)

Principes :
  • Homéostasie     : détection et réaction aux anomalies
  • Immunité adapt. : mémoire des menaces, quarantaine
  • Symbiose        : communication via event_bus
"""

import asyncio
import re
import time
from collections import deque, Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from enum import Enum

from app.agents.base_agent import BaseAgent, Tool
from app.brain.synapses.event_bus import EventBus, Event
from app.utils.logger import logger
from app.utils.errors import ToolExecutionError
from app.utils.metrics import (
    cyber_errors_detected,
    cyber_threats_shared,
    cyber_quarantine_actions,
)


# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────
ERROR_HISTORY_MAXLEN         = 1000
DEFAULT_ERROR_THRESHOLD      = 3
DEFAULT_SEVERITY_THRESHOLD   = 0.5
DEFAULT_QUARANTINE_DURATION  = 3600
DEFAULT_CLEANUP_INTERVAL     = 300
DEFAULT_TOTAL_AGENTS         = 5
EMERGING_PATTERN_MIN_SAMPLES = 10

EXCLUDED_FROM_QUARANTINE: Set[str] = {
    "AgentNotFoundError",
    "ToolNotFoundError",
    "InvalidParametersError",
    "PermissionDeniedError",
}


class ThreatSeverity(Enum):
    LOW      = 0.3
    MEDIUM   = 0.6
    HIGH     = 0.8
    CRITICAL = 0.95


@dataclass
class ThreatSignature:
    """Signature d'une menace basée sur un pattern d'erreur normalisé."""
    pattern:         str
    count:           int           = 0
    severity:        float         = 0.0
    first_seen:      float         = field(default_factory=time.time)
    last_seen:       float         = field(default_factory=time.time)
    affected_agents: Set[str]      = field(default_factory=set)
    resolved:        bool          = False
    solution:        Optional[str] = None


class CyberAgent(BaseAgent):
    """
    Système immunitaire de Lucie.
    Opère exclusivement via l'EventBus — n'expose aucun outil direct.
    """

    agent_name  = "cyber_agent"
    description = "Système immunitaire : détection de menaces, quarantaine, signatures."

    def __init__(
        self,
        llm_service: Any,
        bus: Any,
        event_bus: EventBus,
        config: dict,
        memory_service: Any = None,
        token: Optional[str] = None,
        get_agent_count: Optional[Callable[[], int]] = None,
    ):
        super().__init__(
            name=self.agent_name,
            llm_service=llm_service,
            bus=bus,
            event_bus=event_bus,
            token=token,
        )

        self.memory           = memory_service
        self._lock            = asyncio.Lock()
        self._get_agent_count = get_agent_count

        self.error_threshold     = config.get("error_threshold",     DEFAULT_ERROR_THRESHOLD)
        self.severity_threshold  = config.get("severity_threshold",  DEFAULT_SEVERITY_THRESHOLD)
        self.quarantine_duration = config.get("quarantine_duration", DEFAULT_QUARANTINE_DURATION)
        self.cleanup_interval    = config.get("cleanup_interval",    DEFAULT_CLEANUP_INTERVAL)

        self.signatures:    Dict[str, ThreatSignature]    = {}
        self.quarantine:    Dict[Tuple[str, str], float]  = {}
        self.error_history: deque                         = deque(maxlen=ERROR_HISTORY_MAXLEN)

        self._loop:         Optional[asyncio.AbstractEventLoop] = None
        self._cleanup_task: Optional[asyncio.Task]              = None
        self._subscribed:   bool                                = False
        self._active:       bool                                = False

        if not self.token:
            logger.debug(
                "🔬 CyberAgent : token non encore injecté — "
                "sera fourni par _register_event_handlers() avant set_loop()."
            )
        else:
            logger.info("🔬 CyberAgent initialisé (en attente de set_loop)")

    # ── Cycle de vie ─────────────────────────────────────────────────────────

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Injecte la boucle asyncio et démarre les tâches de fond."""
        if not self.token:
            logger.warning("CyberAgent.set_loop : token absent, démarrage ignoré.")
            return

        self._loop   = loop
        self._active = True

        loop.create_task(self._subscribe())
        loop.create_task(self._load_historical_signatures())
        self._cleanup_task = loop.create_task(self._cleanup_loop())

        logger.info("🔬 CyberAgent actif — surveillance démarrée")

    async def _subscribe(self) -> None:
        """Abonne l'agent aux canaux d'événements (async, token requis)."""
        if self._subscribed:
            return

        # Variable locale → Pylance sait que event_bus n'est pas None après le guard
        event_bus = self.event_bus
        if event_bus is None or not self.token:
            logger.error("CyberAgent._subscribe : event_bus ou token manquant.")
            return

        try:
            await event_bus.subscribe(
                "tool.error",     self._on_tool_error,
                source=self.name, token=self.token,
            )
            await event_bus.subscribe(
                "agent.error",    self._on_agent_error,
                source=self.name, token=self.token,
            )
            await event_bus.subscribe(
                "system.anomaly", self._on_system_anomaly,
                source=self.name, token=self.token,
            )
            self._subscribed = True
            logger.debug("🔬 CyberAgent : abonné à tool.error / agent.error / system.anomaly")
        except Exception as e:
            logger.error(f"CyberAgent._subscribe erreur : {e}")

    async def stop(self) -> None:
        """Arrêt propre — async pour être awaitable depuis engine.py."""
        self._active = False
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 CyberAgent arrêté")

    # ── Nettoyage ─────────────────────────────────────────────────────────────

    async def _cleanup_loop(self) -> None:
        while self._active:
            await asyncio.sleep(self.cleanup_interval)
            await self._cleanup_expired_quarantine()
            await self._cleanup_old_signatures()

    async def _cleanup_expired_quarantine(self) -> None:
        now = time.time()
        async with self._lock:
            expired = [k for k, exp in self.quarantine.items() if exp < now]
            for k in expired:
                del self.quarantine[k]
        if expired:
            logger.info(f"🧹 Quarantaine : {len(expired)} entrée(s) expirée(s) supprimée(s)")

    async def _cleanup_old_signatures(self) -> None:
        to_archive: List[str] = []
        async with self._lock:
            for pattern, sig in self.signatures.items():
                if sig.resolved and (time.time() - sig.last_seen) > 7 * 86400:
                    to_archive.append(pattern)

        for pattern in to_archive:
            await self._archive_signature(pattern)

        async with self._lock:
            for pattern in to_archive:
                self.signatures.pop(pattern, None)

        if to_archive:
            logger.debug(f"📦 {len(to_archive)} signature(s) archivée(s)")

    # ── Persistance ───────────────────────────────────────────────────────────

    async def _load_historical_signatures(self) -> None:
        if not self.memory:
            return
        try:
            try:
                episodes = await self.memory.remember(
                    query="threat signatures",
                    limit=100,
                    metadata_filter={"type": "threat_signature"},
                )
            except TypeError:
                episodes = await self.memory.remember(query="threat signatures", limit=100)
                episodes = [
                    ep for ep in episodes
                    if ep.metadata.get("type") == "threat_signature"
                ]

            loaded = 0
            async with self._lock:
                for ep in episodes:
                    sig_data = ep.metadata.get("signature")
                    if not sig_data:
                        continue
                    pattern = sig_data.get("pattern")
                    if pattern and pattern not in self.signatures:
                        self.signatures[pattern] = ThreatSignature(
                            pattern         = pattern,
                            count           = sig_data.get("count", 0),
                            severity        = sig_data.get("severity", 0.0),
                            first_seen      = sig_data.get("first_seen", ep.timestamp),
                            last_seen       = sig_data.get("last_seen", ep.timestamp),
                            affected_agents = set(sig_data.get("affected_agents", [])),
                            resolved        = sig_data.get("resolved", False),
                            solution        = sig_data.get("solution"),
                        )
                        loaded += 1

            logger.info(f"📚 {loaded} signature(s) historique(s) chargée(s)")
        except Exception as exc:
            logger.error(f"CyberAgent : erreur chargement signatures : {exc}")

    async def _archive_signature(self, pattern: str) -> None:
        if not self.memory:
            return
        async with self._lock:
            sig = self.signatures.get(pattern)
        if not sig:
            return
        try:
            await self.memory.add_episode(
                query    = f"threat: {pattern}",
                response = "",
                metadata = {
                    "type": "threat_signature",
                    "signature": {
                        "pattern":         pattern,
                        "count":           sig.count,
                        "severity":        sig.severity,
                        "first_seen":      sig.first_seen,
                        "last_seen":       sig.last_seen,
                        "affected_agents": list(sig.affected_agents),
                        "resolved":        sig.resolved,
                        "solution":        sig.solution,
                    },
                },
            )
        except Exception as exc:
            logger.error(f"CyberAgent : erreur archivage : {exc}")

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _normalize_error(self, msg: str) -> str:
        msg = re.sub(r"/[^\s]*", "<path>", msg)
        msg = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "<uuid>", msg, flags=re.IGNORECASE,
        )
        msg = re.sub(r"\b\d+\b", "<num>", msg)
        msg = re.sub(r'"[^"]{20,}"', "<str>", msg)
        return msg.strip()

    # ── Handlers d'événements ─────────────────────────────────────────────────

    async def _on_tool_error(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        await self._analyze_error(data, source_type="tool")

    async def _on_agent_error(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        await self._analyze_error(data, source_type="agent")

    async def _on_system_anomaly(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        await self._analyze_error(data, source_type="system")

    async def _analyze_error(self, data: dict, source_type: str) -> None:
        if not self._active:
            return

        error_msg = data.get("error", "")
        agent     = data.get("agent", "unknown")
        tool      = data.get("tool", "unknown")
        code      = data.get("code", "UNKNOWN")

        if code in EXCLUDED_FROM_QUARANTINE:
            return

        normalized = self._normalize_error(error_msg)
        pattern    = f"{code}:{normalized}"

        self.error_history.append((time.time(), agent, tool, error_msg))

        should_alert      = False
        should_quarantine = False
        sig_snapshot:     Optional[ThreatSignature] = None
        run_detection     = False

        async with self._lock:
            sig = self.signatures.get(pattern)
            if not sig:
                sig = ThreatSignature(pattern=pattern)
                self.signatures[pattern] = sig

            sig.count    += 1
            sig.last_seen = time.time()
            sig.affected_agents.add(agent)
            sig.severity  = self._compute_severity(sig)

            # Compteur Prometheus direct (API réelle de metrics.py)
            cyber_errors_detected.labels(agent=agent, tool=tool).inc()

            should_alert      = (
                sig.count >= self.error_threshold
                and sig.severity >= self.severity_threshold
            )
            should_quarantine = sig.severity >= ThreatSeverity.HIGH.value
            run_detection     = sig.count % 10 == 0

            sig_snapshot = ThreatSignature(
                pattern         = sig.pattern,
                count           = sig.count,
                severity        = sig.severity,
                first_seen      = sig.first_seen,
                last_seen       = sig.last_seen,
                affected_agents = set(sig.affected_agents),
                resolved        = sig.resolved,
                solution        = sig.solution,
            )

        if should_alert:
            await self._trigger_alert(sig_snapshot, agent, tool)
        if should_quarantine:
            await self._quarantine_tool(agent, tool, sig_snapshot)
        if run_detection:
            await self._detect_emerging_patterns()

    # ── Calcul de sévérité ────────────────────────────────────────────────────

    def _compute_severity(self, sig: ThreatSignature) -> float:
        freq_score    = min(sig.count / 100.0, 1.0)
        age           = time.time() - sig.last_seen
        recency_score = max(0.0, 1.0 - age / 3600.0)

        total_agents = DEFAULT_TOTAL_AGENTS
        if self._get_agent_count:
            try:
                total_agents = max(1, self._get_agent_count())
            except Exception:
                pass
        spread_score = min(len(sig.affected_agents) / total_agents, 1.0)

        return round(0.4 * freq_score + 0.3 * recency_score + 0.3 * spread_score, 3)

    # ── Actions ───────────────────────────────────────────────────────────────

    async def _trigger_alert(self, sig: ThreatSignature, agent: str, tool: str) -> None:
        # Variable locale → type-narrowing Pylance (évite "publish sur None")
        event_bus = self.event_bus
        if event_bus is None or not self.token:
            logger.error("CyberAgent._trigger_alert : event_bus ou token manquant.")
            return

        logger.warning(f"🔥 Menace : {sig.pattern[:80]} (sév. {sig.severity:.2f}, {sig.count} occ.)")
        try:
            await event_bus.publish(
                channel="cyber.threat",
                data={
                    "pattern":         sig.pattern,
                    "severity":        sig.severity,
                    "count":           sig.count,
                    "affected_agents": list(sig.affected_agents),
                    "solution":        sig.solution or "Aucune solution connue",
                },
                source=self.name,
                token=self.token,
            )
            cyber_threats_shared.inc()
        except Exception as e:
            logger.error(f"CyberAgent._trigger_alert erreur : {e}")

    async def _quarantine_tool(self, agent: str, tool: str, sig: ThreatSignature) -> None:
        event_bus = self.event_bus
        if event_bus is None or not self.token:
            logger.error("CyberAgent._quarantine_tool : event_bus ou token manquant.")
            return

        key        = (agent, tool)
        expiration = time.time() + self.quarantine_duration

        async with self._lock:
            self.quarantine[key] = expiration

        logger.error(f"⛔ Quarantaine : {agent}.{tool} jusqu'à {time.strftime('%H:%M:%S', time.localtime(expiration))}")
        try:
            await event_bus.publish(
                channel="cyber.quarantine",
                data={"agent": agent, "tool": tool, "until": expiration, "pattern": sig.pattern},
                source=self.name,
                token=self.token,
            )
            cyber_quarantine_actions.labels(agent=agent, tool=tool).inc()
        except Exception as e:
            logger.error(f"CyberAgent._quarantine_tool erreur : {e}")

    async def _detect_emerging_patterns(self) -> None:
        event_bus = self.event_bus
        if event_bus is None or not self.token:
            return

        recent = list(self.error_history)[-100:]
        if len(recent) < EMERGING_PATTERN_MIN_SAMPLES:
            return

        messages = [self._normalize_error(msg) for (_, _, _, msg) in recent]

        word_counter: Counter = Counter()
        for msg in messages:
            words = set(re.findall(r"\b[a-zA-Z_]{5,}\b", msg))
            word_counter.update(words)

        threshold = max(3, len(messages) * 0.30)
        emerging  = {w: c for w, c in word_counter.items() if c >= threshold}

        if not emerging:
            return

        async with self._lock:
            known_patterns = " ".join(self.signatures.keys())

        truly_new = {w: c for w, c in emerging.items() if w not in known_patterns}
        if not truly_new:
            return

        top_word, top_count = max(truly_new.items(), key=lambda x: x[1])
        logger.warning(f"⚠️ Pattern émergent : '{top_word}' ({top_count}/{len(messages)} messages récents)")
        try:
            await event_bus.publish(
                channel="cyber.emerging_pattern",
                data={"top_pattern": top_word, "frequency": top_count, "sample_size": len(messages), "candidates": truly_new},
                source=self.name,
                token=self.token,
            )
        except Exception as e:
            logger.error(f"CyberAgent._detect_emerging_patterns erreur : {e}")

    # ── Interface BaseAgent ───────────────────────────────────────────────────

    def get_tools(self) -> list:
        return []

    def can_handle(self, query: str) -> bool:
        return False

    async def execute_tool(self, tool_name: str, params: dict) -> Any:
        raise ToolExecutionError("CyberAgent n'expose aucun outil — il opère via l'EventBus.")

    # ── Monitoring ────────────────────────────────────────────────────────────

    async def get_status(self) -> dict:
        async with self._lock:
            active_threats = sum(
                1 for s in self.signatures.values()
                if s.severity >= self.severity_threshold and not s.resolved
            )
            return {
                "active":            self._active,
                "subscribed":        self._subscribed,
                "signatures_total":  len(self.signatures),
                "active_threats":    active_threats,
                "quarantine_count":  len(self.quarantine),
                "errors_in_history": len(self.error_history),
            }

    def is_quarantined(self, agent: str, tool: str) -> bool:
        key = (agent, tool)
        exp = self.quarantine.get(key)
        if exp is None:
            return False
        return time.time() <= exp