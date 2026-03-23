"""
FeedbackAgent — Boucle de rétroaction pour le système Lucie.

S'abonne aux événements task.completed et tool.error pour maintenir
des scores de fiabilité par agent. Ces scores peuvent être consultés
par le cortex pour ajuster le routage.

Principes :
- Homéostasie : le système apprend de ses erreurs
- Évolution : les scores s'améliorent avec le temps
- Symbiose : communique via EventBus
"""

from typing import Any, Dict, Optional

from app.agents.base_agent import BaseAgent, Tool
from app.brain.synapses.event_bus import EventBus, Event
from app.utils.logger import logger


class FeedbackAgent(BaseAgent):
    """
    Agent de rétroaction — collecte les résultats de tous les agents
    et maintient des scores de fiabilité.
    """

    agent_name = "FeedbackAgent"
    description = "Boucle de rétroaction : scores de fiabilité par agent."

    def __init__(
        self,
        llm_service: Any,
        bus: Any,
        event_bus: EventBus,
        token: Optional[str] = None,
    ):
        super().__init__(
            name=self.agent_name,
            llm_service=llm_service,
            bus=bus,
            event_bus=event_bus,
            token=token,
        )

        # Scores par agent : {agent_name: {"success": int, "errors": int, "total_ms": float}}
        self._scores: Dict[str, Dict[str, Any]] = {}
        self._subscribed: bool = False

        logger.info("📊 FeedbackAgent initialisé")

    # ── Cycle de vie ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """S'abonne aux canaux de résultats."""
        if self._subscribed:
            return

        event_bus = self.event_bus
        if event_bus is None or not self.token:
            logger.warning("FeedbackAgent : event_bus ou token manquant, démarrage ignoré.")
            return

        try:
            await event_bus.subscribe(
                "task.completed", self._on_task_completed,
                source=self.name, token=self.token,
            )
            await event_bus.subscribe(
                "tool.error", self._on_tool_error,
                source=self.name, token=self.token,
            )
            self._subscribed = True
            logger.info("📊 FeedbackAgent : abonné à task.completed + tool.error")
        except Exception as e:
            logger.error(f"FeedbackAgent : erreur abonnement : {e}")

    # ── Handlers ──────────────────────────────────────────────────────────

    async def _on_task_completed(self, event: Event) -> None:
        """Enregistre un succès d'agent."""
        data = event.data if isinstance(event.data, dict) else {}
        agent = data.get("agent", "unknown")
        duration_ms = data.get("duration_ms", 0.0)

        score = self._scores.setdefault(agent, {"success": 0, "errors": 0, "total_ms": 0.0})
        score["success"] += 1
        score["total_ms"] += duration_ms
        logger.debug(f"📊 Score mis à jour : {agent} (succès={score['success']})")

    async def _on_tool_error(self, event: Event) -> None:
        """Enregistre une erreur d'agent."""
        data = event.data if isinstance(event.data, dict) else {}
        agent = data.get("agent", "unknown")

        score = self._scores.setdefault(agent, {"success": 0, "errors": 0, "total_ms": 0.0})
        score["errors"] += 1
        logger.debug(f"📊 Score mis à jour : {agent} (erreurs={score['errors']})")

    # ── API publique ──────────────────────────────────────────────────────

    def get_scores(self) -> Dict[str, Dict[str, Any]]:
        """Retourne les scores de fiabilité par agent."""
        result: Dict[str, Dict[str, Any]] = {}
        for agent, score in self._scores.items():
            total = score["success"] + score["errors"]
            avg_ms = score["total_ms"] / score["success"] if score["success"] > 0 else 0.0
            result[agent] = {
                "success": score["success"],
                "errors": score["errors"],
                "total": total,
                "reliability": round(score["success"] / total, 3) if total > 0 else 1.0,
                "avg_duration_ms": round(avg_ms, 1),
            }
        return result

    # ── Interface BaseAgent ───────────────────────────────────────────────

    def get_tools(self) -> list[Tool]:
        return []

    def can_handle(self, query: str) -> bool:
        return False

    async def execute_tool(self, tool_name: str, params: dict[str, Any]) -> Any:
        return "FeedbackAgent n'expose aucun outil — il collecte les métriques via l'EventBus."
