"""
Module P2P simplifié pour le partage de signatures de menaces.
Version modifiée pour utiliser un fichier simple au lieu de CryptoManager.
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

import aiohttp
from aiohttp import web

from app.utils.logger import logger


class P2PNode:
    """
    Nœud P2P pour échanger des signatures de menaces avec d'autres instances.
    """

    def __init__(self, config: dict, crypto: Any, event_bus: Any, data_dir: Path):
        self.config = config
        self.crypto = crypto  # Non utilisé dans cette version simplifiée
        self.event_bus = event_bus
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.port = config.get("port", 9000)
        self.bootstrap_peers = config.get("bootstrap_peers", [])
        self.peers = set(self.bootstrap_peers)
        self.node_id = self._get_or_create_node_id()

        self.app = web.Application()
        self.app.router.add_post("/threat", self._handle_threat)
        self.app.router.add_get("/peers", self._handle_get_peers)
        self.runner = None
        self.site = None

        logger.info(f"🌐 Nœud P2P initialisé avec ID {self.node_id} sur le port {self.port}")

    def _get_or_create_node_id(self) -> str:
        """Récupère ou crée un identifiant unique pour ce nœud."""
        id_file = self.data_dir / "node_id.txt"
        if id_file.exists():
            return id_file.read_text().strip()
        else:
            node_id = str(uuid.uuid4())
            id_file.write_text(node_id)
            return node_id

    def run_in_thread(self):
        """Démarre le serveur web dans un thread séparé."""
        import threading
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

    def _run_server(self):
        """Exécute le serveur asyncio dans une boucle dédiée."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._start())
        loop.run_forever()

    async def _start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '0.0.0.0', self.port)
        await self.site.start()
        logger.info(f"🚀 Serveur P2P démarré sur le port {self.port}")

    async def _handle_threat(self, request):
        """Reçoit une menace d'un autre nœud."""
        data = await request.json()
        logger.info(f"📥 Réception d'une menace depuis {request.remote}: {data.get('pattern', '?')}")
        # Publier sur l'event bus local
        self.event_bus.publish("cyber.threat", data, "p2p")
        return web.Response(text="OK")

    async def _handle_get_peers(self, request):
        """Retourne la liste des pairs connus."""
        return web.json_response(list(self.peers))

    async def broadcast_threat(self, threat_data: Dict[str, Any]):
        """Diffuse une menace à tous les pairs connus."""
        for peer in self.peers:
            try:
                url = f"http://{peer}/threat"
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=threat_data, timeout=2) as resp:
                        if resp.status == 200:
                            logger.debug(f"Menace envoyée à {peer}")
                        else:
                            logger.warning(f"Échec envoi à {peer} (status {resp.status})")
            except Exception as e:
                logger.warning(f"Erreur envoi à {peer}: {e}")

    async def stop(self):
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.shutdown()
        logger.info("Nœud P2P arrêté")