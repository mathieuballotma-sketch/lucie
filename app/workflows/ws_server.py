"""
WebSocket server pour les événements temps réel de l'éditeur de workflows.

Écoute les événements EventBus du WorkflowExecutor et les diffuse
aux clients WebSocket connectés (le frontend React Flow).
Port par défaut : 9724.
"""

import json
from typing import Any, Dict, Optional, Set

from ..utils.logger import logger


class WorkflowWSServer:
    """Serveur WebSocket pour les événements workflow en temps réel."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9724,
        event_bus: Optional[Any] = None,
        token: Optional[str] = None,
    ) -> None:
        self._host = host
        self._port = port
        self._event_bus = event_bus
        self._token = token
        self._clients: Set[Any] = set()
        self._server: Optional[Any] = None
        self._running = False

    async def start(self) -> None:
        """Démarre le serveur WebSocket."""
        try:
            import websockets
        except ImportError:
            logger.warning(
                "websockets non installé — serveur WS désactivé. "
                "Installez avec: pip install websockets"
            )
            return

        self._running = True
        self._server = await websockets.serve(
            self._handler,
            self._host,
            self._port,
        )
        logger.info(f"WorkflowWSServer: démarré sur ws://{self._host}:{self._port}")

        # S'abonner aux événements EventBus si disponible
        await self._subscribe_events()

    async def stop(self) -> None:
        """Arrête le serveur proprement."""
        self._running = False
        server = self._server
        if server is not None:
            server.close()
            await server.wait_closed()
            self._server = None
        logger.info("WorkflowWSServer: arrêté")

    async def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        """Diffuse un événement à tous les clients connectés."""
        if not self._clients:
            return

        message = json.dumps({"type": event_type, "data": data})
        disconnected: Set[Any] = set()

        for client in self._clients:
            try:
                await client.send(message)
            except Exception:
                disconnected.add(client)

        self._clients -= disconnected

    async def _handler(self, websocket: Any, path: str = "/") -> None:
        """Gère une connexion WebSocket entrante."""
        self._clients.add(websocket)
        logger.debug(f"WorkflowWSServer: client connecté ({len(self._clients)} total)")
        try:
            async for message in websocket:
                # Le frontend peut envoyer des commandes
                try:
                    data = json.loads(message)
                    await self._handle_client_message(websocket, data)
                except json.JSONDecodeError:
                    await websocket.send(
                        json.dumps({"type": "error", "data": {"message": "JSON invalide"}})
                    )
        except Exception:
            pass
        finally:
            self._clients.discard(websocket)
            logger.debug(
                f"WorkflowWSServer: client déconnecté ({len(self._clients)} restants)"
            )

    async def _handle_client_message(
        self, websocket: Any, data: Dict[str, Any]
    ) -> None:
        """Traite un message reçu d'un client."""
        msg_type = data.get("type", "")
        if msg_type == "ping":
            await websocket.send(json.dumps({"type": "pong", "data": {}}))

    async def _subscribe_events(self) -> None:
        """S'abonne aux événements workflow sur l'EventBus."""
        event_bus = self._event_bus
        if event_bus is None:
            return
        token = self._token
        if token is None:
            return

        channels = [
            "workflow_workflow_started",
            "workflow_node_completed",
            "workflow_workflow_completed",
        ]
        for channel in channels:
            try:
                await event_bus.subscribe(
                    channel,
                    self._on_workflow_event,
                    source="WorkflowWSServer",
                    token=token,
                )
            except Exception as exc:
                logger.debug(f"WorkflowWSServer: échec abonnement {channel}: {exc}")

    async def _on_workflow_event(self, event: Any) -> None:
        """Handler pour les événements EventBus workflow."""
        if not self._running:
            return
        data = event if isinstance(event, dict) else getattr(event, "data", {})
        channel = data.get("channel", "workflow_event") if isinstance(data, dict) else "workflow_event"
        await self.broadcast(channel, data)

    @property
    def client_count(self) -> int:
        """Nombre de clients WebSocket connectés."""
        return len(self._clients)

    @property
    def is_running(self) -> bool:
        """True si le serveur est en cours d'exécution."""
        return self._running
