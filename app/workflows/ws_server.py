"""
WorkflowEventServer — Serveur WebSocket temps-réel pour l'éditeur de flux.

Diffuse les événements d'exécution de workflow (démarrage, nœud terminé,
workflow terminé) aux clients frontend connectés.
Port par défaut : 9724
"""

import json
from typing import Any, Optional, Set

from ..utils.logger import logger

try:
    import websockets  # type: ignore

    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    logger.warning(
        "WorkflowEventServer: websockets non installé — streaming temps-réel désactivé"
    )

# Canaux EventBus surveillés
_WATCHED_CHANNELS = [
    "workflow_workflow_started",
    "workflow_node_completed",
    "workflow_workflow_completed",
]


class WorkflowEventServer:
    """Serveur WebSocket qui diffuse les événements de workflow au frontend."""

    DEFAULT_PORT = 9724

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        event_bus: Optional[Any] = None,
        token: Optional[str] = None,
    ) -> None:
        self.port = port
        self.event_bus = event_bus
        self.token = token
        self._clients: Set[Any] = set()
        self._server: Optional[Any] = None

    async def start(self) -> bool:
        """
        Démarre le serveur WebSocket.

        Retourne True si démarré avec succès, False sinon.
        """
        if not HAS_WEBSOCKETS:
            logger.warning(
                "WorkflowEventServer: websockets manquant, serveur non démarré"
            )
            return False

        try:
            self._server = await websockets.serve(  # type: ignore[attr-defined]
                self._handle_client,
                "localhost",
                self.port,
            )
            logger.info(
                f"WorkflowEventServer: démarré sur ws://localhost:{self.port}"
            )

            # Abonnement aux événements EventBus si disponible
            event_bus = self.event_bus
            if event_bus is not None:
                token = self.token
                if token is not None:
                    for channel in _WATCHED_CHANNELS:
                        try:
                            await event_bus.subscribe(
                                channel,
                                self._on_event,
                                source="WorkflowEventServer",
                                token=token,
                            )
                        except Exception as exc:
                            logger.debug(
                                f"WorkflowEventServer: abonnement {channel} échoué: {exc}"
                            )

            return True

        except Exception as exc:
            logger.error(f"WorkflowEventServer: erreur démarrage: {exc}")
            return False

    async def stop(self) -> None:
        """Arrête proprement le serveur et ferme toutes les connexions client."""
        server = self._server
        if server is not None:
            server.close()
            try:
                await server.wait_closed()
            except Exception:
                pass
            self._server = None
            logger.info("WorkflowEventServer: arrêté")

        clients = list(self._clients)
        for client in clients:
            try:
                await client.close()
            except Exception:
                pass
        self._clients.clear()

    async def broadcast(self, message: dict) -> int:
        """
        Diffuse un message JSON à tous les clients connectés.

        Retourne le nombre de clients atteints.
        """
        if not self._clients:
            return 0

        payload = json.dumps(message)
        disconnected: Set[Any] = set()
        sent = 0

        for client in list(self._clients):
            try:
                await client.send(payload)
                sent += 1
            except Exception:
                disconnected.add(client)

        self._clients -= disconnected
        return sent

    async def _handle_client(self, websocket: Any, path: str = "") -> None:
        """Gère le cycle de vie d'une connexion WebSocket cliente."""
        self._clients.add(websocket)
        client_count = len(self._clients)
        logger.debug(
            f"WorkflowEventServer: client connecté ({client_count} total)"
        )

        # Envoyer un message de bienvenue
        try:
            await websocket.send(
                json.dumps({"channel": "connected", "data": {"port": self.port}})
            )
        except Exception:
            pass

        try:
            await websocket.wait_closed()
        finally:
            self._clients.discard(websocket)
            logger.debug(
                f"WorkflowEventServer: client déconnecté "
                f"({len(self._clients)} restant)"
            )

    async def _on_event(self, event: Any) -> None:
        """Handler EventBus — relaie les événements aux clients WebSocket."""
        try:
            data = event.data if hasattr(event, "data") else {}
            channel = event.channel if hasattr(event, "channel") else "unknown"
            await self.broadcast({"channel": channel, "data": data})
        except Exception as exc:
            logger.debug(
                f"WorkflowEventServer: erreur relay événement: {exc}"
            )

    @property
    def client_count(self) -> int:
        """Nombre de clients WebSocket actuellement connectés."""
        return len(self._clients)

    @property
    def is_running(self) -> bool:
        """True si le serveur WebSocket est actif."""
        return self._server is not None
