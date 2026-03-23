"""
Moteur de suggestions proactives avec anti-spam.
Genere des briefings matinaux, des suggestions contextuelles et des alertes utiles
sans submerger l'utilisateur.
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ..memory.contextual_memory import ContextualMemory
from ..services.time_tracker import TimeTracker
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ProactiveEngine:
    """Moteur de suggestions proactives avec anti-spam."""

    MAX_SUGGESTIONS_PER_HOUR: int = 3
    MIN_INTERVAL_SECONDS: int = 300  # 5 minutes minimum entre suggestions

    def __init__(
        self,
        contextual_memory: ContextualMemory,
        time_tracker: TimeTracker,
    ) -> None:
        self._memory = contextual_memory
        self._tracker = time_tracker
        self._suggestion_history: List[Dict[str, Any]] = []
        self._dismissed_topics: Dict[str, float] = {}  # topic -> dismissed_until
        self._dismissed_ttl: float = 86400.0  # 24h blacklist

        self._suggestion_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._running = False
        self._task: Optional[asyncio.Task[None]] = None
        self._morning_briefing_done = False
        self._last_suggestion_time: float = 0.0

        logger.info("ProactiveEngine initialise")

    # ─────────────────────────────────────────────────────────────────────────
    # Anti-spam
    # ─────────────────────────────────────────────────────────────────────────
    def _can_suggest(self) -> bool:
        """Verifie si on peut faire une nouvelle suggestion."""
        now = time.time()

        # Intervalle minimum
        if now - self._last_suggestion_time < self.MIN_INTERVAL_SECONDS:
            return False

        # Maximum par heure
        one_hour_ago = now - 3600
        recent = [
            s for s in self._suggestion_history
            if s.get("timestamp", 0) > one_hour_ago
        ]
        if len(recent) >= self.MAX_SUGGESTIONS_PER_HOUR:
            return False

        return True

    def _is_topic_dismissed(self, topic: str) -> bool:
        """Verifie si un sujet a ete dismiss et est encore blackliste."""
        until = self._dismissed_topics.get(topic, 0)
        if time.time() < until:
            return True
        # Nettoyer le sujet expire
        self._dismissed_topics.pop(topic, None)
        return False

    def dismiss_topic(self, topic: str) -> None:
        """Blackliste un sujet pour 24h."""
        self._dismissed_topics[topic] = time.time() + self._dismissed_ttl
        logger.debug(f"Sujet dismiss: {topic}")

    def _record_suggestion(self, suggestion: Dict[str, Any]) -> None:
        """Enregistre une suggestion dans l'historique."""
        suggestion["timestamp"] = time.time()
        self._suggestion_history.append(suggestion)
        self._last_suggestion_time = time.time()

    # ─────────────────────────────────────────────────────────────────────────
    # Callbacks
    # ─────────────────────────────────────────────────────────────────────────
    def on_suggestion(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Enregistre un callback pour les nouvelles suggestions."""
        self._suggestion_callbacks.append(callback)

    def _emit_suggestion(self, suggestion: Dict[str, Any]) -> None:
        """Emet une suggestion vers les callbacks enregistres."""
        if not self._can_suggest():
            logger.debug("Anti-spam: suggestion bloquee")
            return

        topic = suggestion.get("topic", "")
        if topic and self._is_topic_dismissed(topic):
            logger.debug(f"Sujet dismiss: {topic}")
            return

        self._record_suggestion(suggestion)
        for cb in self._suggestion_callbacks:
            try:
                cb(suggestion)
            except Exception as e:
                logger.error(f"Suggestion callback error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Briefing matinal
    # ─────────────────────────────────────────────────────────────────────────
    async def generate_morning_briefing(self) -> Optional[Dict[str, Any]]:
        """Genere le briefing matinal (premier lancement de la journee)."""
        tracker_status = self._tracker.get_status_for_hud()

        parts = []

        # Stats de la veille
        daily = self._tracker.get_daily_stats()
        if daily["task_count"] > 0:
            parts.append(
                f"Hier: {daily['task_count']} taches, "
                f"{daily['time_saved_formatted']} gagnes"
            )

        # Streak
        streak = tracker_status.get("streak", 0)
        if streak > 1:
            parts.append(f"Serie active: {streak} jours consecutifs")

        # Total
        total_saved = tracker_status.get("total_saved", "0s")
        parts.append(f"Total temps gagne: {total_saved}")

        if not parts:
            return None

        briefing = {
            "type": "morning_briefing",
            "topic": "morning_briefing",
            "title": "Briefing du matin",
            "content": "\n".join(parts),
            "score": 0.9,
        }
        return briefing

    # ─────────────────────────────────────────────────────────────────────────
    # Suggestions contextuelles
    # ─────────────────────────────────────────────────────────────────────────
    async def generate_contextual_suggestions(self) -> List[Dict[str, Any]]:
        """Genere des suggestions basees sur les patterns recents."""
        suggestions: List[Dict[str, Any]] = []

        patterns = await self._memory.get_patterns()
        if not patterns:
            return suggestions

        now = datetime.now()
        current_hour = now.hour

        for pattern in patterns[:5]:
            data = pattern.get("data", {})
            pattern_hour = data.get("hour")
            action = data.get("action", "")
            freq = pattern.get("frequency", 0)

            # Suggerer si l'heure correspond et la frequence est suffisante
            if (
                pattern_hour is not None
                and abs(current_hour - pattern_hour) <= 1
                and freq >= 3
            ):
                suggestion = {
                    "type": "contextual",
                    "topic": f"pattern_{action}",
                    "title": f"Suggestion: {action}",
                    "content": (
                        f"Tu fais souvent '{action}' a cette heure. "
                        f"Veux-tu que je le fasse ?"
                    ),
                    "score": min(1.0, 0.5 + freq * 0.1),
                    "action": action,
                }
                suggestions.append(suggestion)

        return suggestions

    # ─────────────────────────────────────────────────────────────────────────
    # Boucle principale
    # ─────────────────────────────────────────────────────────────────────────
    async def start(self) -> None:
        """Demarre le moteur proactif."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._main_loop())
        logger.info("ProactiveEngine demarre")

    async def stop(self) -> None:
        """Arrete le moteur proactif."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ProactiveEngine arrete")

    async def _main_loop(self) -> None:
        """Boucle principale de verification."""
        while self._running:
            try:
                # Briefing matinal
                if not self._morning_briefing_done:
                    briefing = await self.generate_morning_briefing()
                    if briefing:
                        self._emit_suggestion(briefing)
                    self._morning_briefing_done = True

                # Suggestions contextuelles (toutes les 15 min)
                suggestions = await self.generate_contextual_suggestions()
                for s in suggestions:
                    score = s.get("score", 0)
                    if score > 0.7:
                        self._emit_suggestion(s)

            except Exception as e:
                logger.error(f"ProactiveEngine loop error: {e}")

            await asyncio.sleep(900)  # 15 minutes

    def get_recent_suggestions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retourne les suggestions recentes."""
        return self._suggestion_history[-limit:]

    def compute_relevance_score(
        self,
        frequency: int,
        recency_seconds: float,
        user_accepted_ratio: float = 0.5,
    ) -> float:
        """Calcule un score de pertinence pour une suggestion.

        Args:
            frequency: Nombre d'occurrences du pattern.
            recency_seconds: Secondes depuis la derniere occurrence.
            user_accepted_ratio: Ratio de suggestions acceptees (0-1).

        Returns:
            Score entre 0 et 1.
        """
        # Frequence: logarithmique, plafonne a 0.4
        import math
        freq_score = min(0.4, 0.1 * math.log1p(frequency))

        # Recence: decroissance exponentielle
        recency_score = 0.3 * math.exp(-recency_seconds / 86400)

        # Acceptation: directe
        accept_score = 0.3 * user_accepted_ratio

        return min(1.0, freq_score + recency_score + accept_score)
