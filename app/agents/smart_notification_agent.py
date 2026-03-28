"""
SmartNotificationAgent — Filtrage intelligent des notifications macOS.

Fonctionnalités :
- Classification par importance : critique, important, informatif, bruit
- Mode focus : ne laisse passer que les notifications critiques
- Apprentissage des préférences via MemoryService
- Résumé des notifications manquées pendant le mode focus
- Publication sur "notification.filtered" pour affichage HUD

model_role = "lightweight" — classement rapide par mots-clés, pas de gros modèle.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional

from pydantic.v1 import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger


class Priority(str, Enum):
    """Niveaux d'importance d'une notification."""

    CRITICAL = "critique"
    IMPORTANT = "important"
    INFORMATIVE = "informatif"
    NOISE = "bruit"


@dataclass
class Notification:
    """Représente une notification reçue et classifiée."""

    app: str
    title: str
    body: str
    priority: Priority = Priority.NOISE
    seen: bool = False


class ToggleFocusContract(BaseModel):
    """Contrat pour l'outil toggle_focus."""

    enabled: bool = Field(
        ...,
        description="True pour activer le mode focus, False pour le désactiver",
    )


class SmartNotificationAgent(BaseAgent):
    """
    Filtre et classe les notifications macOS selon leur importance.

    Utilise une classification rapide par mots-clés (sans LLM)
    pour minimiser la latence. Les préférences apprises sont
    persistées via MemoryService entre les sessions.
    """

    _PRIORITY_KEYWORDS: ClassVar[Dict[Priority, List[str]]] = {
        Priority.CRITICAL: [
            "erreur critique",
            "alerte",
            "urgence",
            "crash",
            "failed",
            "error",
            "virus",
            "intrusion",
            "sécurité",
            "paiement",
            "2fa",
            "code de vérification",
            "authentification",
        ],
        Priority.IMPORTANT: [
            "réunion",
            "meeting",
            "rappel",
            "deadline",
            "livraison",
            "commande",
            "appel manqué",
            "mise à jour importante",
            "message de",
        ],
        Priority.INFORMATIVE: [
            "mise à jour",
            "téléchargé",
            "synchronisé",
            "sauvegarde",
            "backup",
            "update",
            "info",
        ],
    }

    def __init__(
        self,
        llm_service: Any,
        bus: Any,
        config: Dict[str, Any],
        memory_service: Optional[Any] = None,
    ) -> None:
        super().__init__("SmartNotificationAgent", llm_service, bus)
        self._focus_mode: bool = False
        self._notification_queue: List[Notification] = []
        self._missed_while_focus: List[Notification] = []
        self.memory_service = memory_service

    def can_handle(self, query: str) -> bool:
        q = query.lower().strip()
        keywords = [
            "mode focus",
            "focus mode",
            "activer focus",
            "désactiver focus",
            "notifications manquées",
            "résume les notifications",
            "qu'ai-je manqué",
            "notifications récentes",
            "dernières notifications",
        ]
        return any(kw in q for kw in keywords)

    def get_tools(self) -> List[Tool]:
        return [
            Tool(
                name="toggle_focus",
                description=(
                    "Active ou désactive le mode focus "
                    "(filtre les notifications non critiques)"
                ),
                contract=ToggleFocusContract,
            )
        ]

    async def handle(self, query: str) -> str:
        """Gère les requêtes utilisateur liées aux notifications."""
        q = query.lower().strip()

        is_focus_query = "mode focus" in q or "focus mode" in q or "activer focus" in q
        is_disable = any(kw in q for kw in ("désactiver", "off", "arrêt", "arrêter", "stopper"))

        if is_focus_query:
            return await self._tool_toggle_focus(enabled=not is_disable)

        if any(kw in q for kw in ("manquées", "qu'ai-je manqué", "résume")):
            return self._summarize_missed()

        if any(kw in q for kw in ("récentes", "dernières")):
            return self._list_recent()

        return await self.ask_llm_async(query, model_role="lightweight")

    # ------------------------------------------------------------------
    # Outil : toggle_focus
    # ------------------------------------------------------------------

    async def _tool_toggle_focus(self, enabled: bool) -> str:
        """Active ou désactive le mode focus."""
        self._focus_mode = enabled
        if enabled:
            self._missed_while_focus.clear()
            msg = "Mode focus activé — seules les notifications critiques passeront."
        else:
            missed = len(self._missed_while_focus)
            msg = (
                f"Mode focus désactivé — {missed} notification(s) en attente. "
                "Dites \"résume les notifications\" pour voir le résumé."
            )
        logger.info(f"SmartNotificationAgent: {msg}")
        return msg

    # ------------------------------------------------------------------
    # Ingestion de notifications
    # ------------------------------------------------------------------

    async def ingest(self, app: str, title: str, body: str) -> Optional[Notification]:
        """
        Reçoit une notification, la classe et décide de l'afficher ou non.

        Retourne la Notification si elle doit être affichée,
        None si elle est filtrée (bruit ou mode focus actif).
        """
        priority = self._classify_priority(app, title, body)
        notif = Notification(app=app, title=title, body=body, priority=priority)
        self._notification_queue.append(notif)

        if self._focus_mode and priority != Priority.CRITICAL:
            self._missed_while_focus.append(notif)
            logger.debug(
                f"SmartNotificationAgent: filtrée (mode focus) — app={app}"
            )
            return None

        if priority == Priority.NOISE:
            logger.debug(
                f"SmartNotificationAgent: ignorée (bruit) — app={app}"
            )
            return None

        notif.seen = True
        await self._publish_notification(notif)
        return notif

    def _classify_priority(self, app: str, title: str, body: str) -> Priority:
        """
        Classification rapide par mots-clés sans LLM (latence minimale).
        Ordre : critique > important > informatif > bruit.
        """
        text = f"{app} {title} {body}".lower()
        for priority in (Priority.CRITICAL, Priority.IMPORTANT, Priority.INFORMATIVE):
            for kw in self._PRIORITY_KEYWORDS.get(priority, []):
                if kw in text:
                    return priority
        return Priority.NOISE

    async def _publish_notification(self, notif: Notification) -> None:
        """Publie la notification filtrée sur l'EventBus pour affichage HUD."""
        event_bus = self.event_bus
        if event_bus is None or not self.token:
            return
        try:
            await event_bus.publish(
                channel="notification.filtered",
                data={
                    "app": notif.app,
                    "title": notif.title,
                    "body": notif.body,
                    "priority": notif.priority.value,
                },
                source=self.name,
                token=self.token,
            )
        except Exception as exc:
            logger.warning(
                f"SmartNotificationAgent: échec publication notification — {exc}"
            )

    # ------------------------------------------------------------------
    # Résumé et historique
    # ------------------------------------------------------------------

    def _summarize_missed(self) -> str:
        """Résume les notifications manquées pendant le mode focus et vide la file."""
        missed = self._missed_while_focus
        if not missed:
            return "Aucune notification manquée pendant le mode focus."

        by_priority: Dict[str, List[str]] = {
            Priority.CRITICAL.value: [],
            Priority.IMPORTANT.value: [],
            Priority.INFORMATIVE.value: [],
            Priority.NOISE.value: [],
        }
        for n in missed:
            by_priority[n.priority.value].append(f"[{n.app}] {n.title}")

        lines = [f"**{len(missed)} notifications manquées :**"]
        for level in (
            Priority.CRITICAL.value,
            Priority.IMPORTANT.value,
            Priority.INFORMATIVE.value,
        ):
            items = by_priority[level]
            if items:
                lines.append(f"\n_{level.capitalize()} ({len(items)})_")
                lines.extend(f"  • {item}" for item in items)

        self._missed_while_focus.clear()
        return "\n".join(lines)

    def _list_recent(self, n: int = 10) -> str:
        """Liste les n dernières notifications qui ont été affichées."""
        recent = [notif for notif in self._notification_queue[-n:] if notif.seen]
        if not recent:
            return "Aucune notification récente."
        lines = ["**Notifications récentes :**"]
        for notif in reversed(recent):
            lines.append(
                f"  [{notif.priority.value.upper()}] [{notif.app}] {notif.title}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Apprentissage des préférences
    # ------------------------------------------------------------------

    async def learn_preference(self, app: str, action: str) -> None:
        """
        Enregistre une préférence utilisateur (ex: ignorer les notifications de X).
        Persiste via MemoryService si disponible, sinon log uniquement.
        """
        memory = self.memory_service
        if memory is None:
            logger.debug(
                "SmartNotificationAgent: MemoryService absent, préférence non persistée."
            )
            return
        try:
            await memory.add_episode(
                query=f"préférence notification {app}",
                response=action,
                metadata={
                    "type": "notification_preference",
                    "app": app,
                    "action": action,
                },
            )
            logger.info(
                f"SmartNotificationAgent: préférence enregistrée — {app}: {action}"
            )
        except Exception as exc:
            logger.warning(
                f"SmartNotificationAgent: erreur enregistrement préférence — {exc}"
            )
