"""
WatchAgent — Surveillance continue en arrière-plan.

Surveille un sujet et alerte quand une condition est remplie.
Exemple : "surveille le bitcoin et préviens-moi si ça passe 100 000€"

Utilise KnowledgeAgent pour la recherche et les notifications macOS.
"""

import asyncio
import hashlib
import time
from typing import Any, Dict

from pydantic.v1 import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger


class StartWatchContract(BaseModel):
    topic: str = Field(..., description="Sujet à surveiller")
    condition: str = Field(..., description="Condition de déclenchement")
    check_interval: int = Field(300, description="Intervalle de vérification en secondes")


class StopWatchContract(BaseModel):
    watch_id: str = Field(..., description="Identifiant de la surveillance à arrêter")


class WatchAgent(BaseAgent):
    """
    Surveille un sujet en continu.
    Alerte quand une condition est remplie.
    """

    def __init__(self, llm_service: Any, bus: Any, config: dict[str, Any]) -> None:
        super().__init__("WatchAgent", llm_service, bus)
        self._watches: Dict[str, dict[str, Any]] = {}
        self._running = False
        self._tasks: Dict[str, asyncio.Task[None]] = {}
        logger.info("👁️ WatchAgent initialisé")

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="start_watch",
                description="Lance une surveillance en arrière-plan sur un sujet",
                contract=StartWatchContract,
            ),
            Tool(
                name="stop_watch",
                description="Arrête une surveillance active",
                contract=StopWatchContract,
            ),
        ]

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        keywords = [
            "surveille", "préviens-moi si", "préviens moi si",
            "alerte quand", "watch", "monitore",
            "alerte-moi", "préviens-moi quand",
        ]
        return any(kw in q for kw in keywords)

    async def handle(self, query: str) -> str:
        """Extrait le sujet et la condition, puis lance la surveillance."""
        import re

        q = query.lower()
        # Extraire le sujet et la condition
        # Pattern : "surveille X et préviens-moi si Y"
        match = re.search(
            r"(?:surveille|monitore|watch)\s+(.+?)\s+(?:et\s+)?(?:préviens|alerte|notifie)[- ]moi\s+(?:si|quand|lorsque)\s+(.+)",
            q, re.IGNORECASE
        )
        if match:
            topic = match.group(1).strip()
            condition = match.group(2).strip()
        else:
            # Tenter un pattern plus simple
            match2 = re.search(r"(?:surveille|monitore|watch)\s+(.+)", q, re.IGNORECASE)
            if match2:
                topic = match2.group(1).strip()
                condition = "changement significatif"
            else:
                topic = query
                condition = "changement significatif"

        return await self._tool_start_watch(
            topic=topic,
            condition=condition,
            check_interval=300,
        )

    async def _tool_start_watch(
        self,
        topic: str,
        condition: str,
        check_interval: int = 300,
    ) -> str:
        """Lance une surveillance en arrière-plan."""
        # Générer un identifiant unique
        watch_id = hashlib.blake2b(
            f"{topic}:{condition}:{time.time()}".encode(),
            digest_size=8,
        ).hexdigest()

        self._watches[watch_id] = {
            "topic": topic,
            "condition": condition,
            "interval": check_interval,
            "created": time.time(),
            "last_check": 0,
            "triggered": False,
        }

        # Lancer la tâche de surveillance
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._watch_loop(watch_id))
            self._tasks[watch_id] = task
        except RuntimeError:
            logger.warning("Pas de boucle asyncio — surveillance en mode passif")

        logger.info(f"👁️ Surveillance démarrée: {topic} (id={watch_id})")
        return (
            f"✅ Surveillance active : \"{topic}\"\n"
            f"   Condition : {condition}\n"
            f"   Vérification toutes les {check_interval}s\n"
            f"   ID : {watch_id}"
        )

    async def _watch_loop(self, watch_id: str) -> None:
        """Boucle de surveillance pour un watch donné."""
        watch = self._watches.get(watch_id)
        if not watch:
            return

        while watch_id in self._watches and not watch.get("triggered"):
            try:
                await asyncio.sleep(watch["interval"])

                if watch_id not in self._watches:
                    break

                watch["last_check"] = time.time()
                triggered = await self._check_condition(watch_id)
                if triggered:
                    watch["triggered"] = True
                    break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erreur surveillance {watch_id}: {e}")
                await asyncio.sleep(60)  # Attendre avant de réessayer

    async def _check_condition(self, watch_id: str) -> bool:
        """
        Vérifie si la condition est remplie.
        Utilise le LLM pour interpréter les résultats.
        Si oui → notification macOS.
        """
        watch = self._watches.get(watch_id)
        if not watch:
            return False

        topic = watch["topic"]
        condition = watch["condition"]

        # Demander au LLM d'évaluer la condition
        prompt = (
            f"Tu surveilles le sujet \"{topic}\".\n"
            f"La condition d'alerte est : \"{condition}\".\n"
            f"Date actuelle : {time.strftime('%Y-%m-%d %H:%M')}.\n\n"
            f"En te basant sur tes connaissances actuelles, "
            f"la condition est-elle remplie ?\n"
            f"Réponds uniquement par JSON : "
            f'{{\"triggered\": true/false, \"reason\": \"...\"}}'
        )

        try:
            response = self.ask_llm(prompt, model="nano", max_tokens=100)
            data = self.extract_json_from_response(response)
            if data and data.get("triggered"):
                reason = data.get("reason", "Condition remplie")
                await self._send_notification(topic, condition, reason)
                logger.info(f"🔔 Alerte déclenchée: {topic} — {reason}")
                return True
        except Exception as e:
            logger.debug(f"Vérification échouée pour {watch_id}: {e}")

        return False

    async def _send_notification(self, topic: str, condition: str, reason: str) -> None:
        """Envoie une notification macOS native."""
        script = (
            f'display notification "{reason}" '
            f'with title "🔔 Lucie — Alerte" '
            f'subtitle "{topic}"'
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except Exception as e:
            logger.debug(f"Notification échouée: {e}")

    async def _tool_stop_watch(self, watch_id: str) -> str:
        """Arrête une surveillance."""
        if watch_id not in self._watches:
            return f"❌ Surveillance {watch_id} introuvable"

        # Annuler la tâche
        task = self._tasks.pop(watch_id, None)
        if task and not task.done():
            task.cancel()

        watch = self._watches.pop(watch_id)
        logger.info(f"👁️ Surveillance arrêtée: {watch['topic']}")
        return f"✅ Surveillance arrêtée : \"{watch['topic']}\" (id={watch_id})"

    def list_watches(self) -> list[dict[str, Any]]:
        """Liste les surveillances actives."""
        result = []
        for wid, watch in self._watches.items():
            result.append({
                "id": wid,
                "topic": watch["topic"],
                "condition": watch["condition"],
                "interval": watch["interval"],
                "last_check": watch["last_check"],
                "triggered": watch["triggered"],
            })
        return result

    def stop_watch(self, watch_id: str) -> str:
        """Arrête une surveillance (version sync)."""
        if watch_id not in self._watches:
            return f"❌ Surveillance {watch_id} introuvable"
        task = self._tasks.pop(watch_id, None)
        if task and not task.done():
            task.cancel()
        watch = self._watches.pop(watch_id)
        return f"✅ Surveillance arrêtée : \"{watch['topic']}\""

    async def stop(self) -> None:
        """Arrête toutes les surveillances."""
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        self._tasks.clear()
        self._watches.clear()
        logger.info("👁️ WatchAgent arrêté")
