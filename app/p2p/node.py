"""
Module P2P simplifié pour le partage de signatures de menaces.
Version modifiée pour utiliser un fichier simple au lieu de CryptoManager.
"""

import asyncio
import hashlib
import hmac
import json
import secrets
import uuid
from pathlib import Path
from typing import Dict, Any

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
        # Clé partagée pour l'authentification HMAC-SHA256 des messages P2P
        self.shared_key: str = config.get("shared_key", "") or self._get_or_create_shared_key()

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

    def _get_or_create_shared_key(self) -> str:
        """Crée ou charge la clé partagée HMAC-SHA256 pour l'authentification P2P."""
        key_file = self.data_dir / "p2p_key.txt"
        if key_file.exists():
            return key_file.read_text().strip()
        key = secrets.token_hex(32)
        key_file.write_text(key)
        logger.info("🔑 Clé HMAC P2P générée et persistée.")
        return key

    def _verify_hmac(self, body: bytes, signature: str) -> bool:
        """Vérifie la signature HMAC-SHA256 d'un message entrant."""
        if not signature:
            return False
        expected = hmac.new(
            self.shared_key.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

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
        # Écoute sur 127.0.0.1 par défaut — évite l'exposition réseau non intentionnelle
        listen_host = self.config.get("host", "127.0.0.1")
        self.site = web.TCPSite(self.runner, listen_host, self.port)
        await self.site.start()
        logger.info(f"🚀 Serveur P2P démarré sur {listen_host}:{self.port}")

    async def _handle_threat(self, request):
        """Reçoit une menace d'un autre nœud — avec authentification HMAC-SHA256 et validation de schéma."""
        # Vérification de la signature HMAC avant tout traitement
        signature = request.headers.get("X-Signature", "")
        body = await request.read()
        if not self._verify_hmac(body, signature):
            logger.warning(f"🚫 Signature HMAC invalide depuis {request.remote}")
            return web.Response(status=401, text="Unauthorized")

        # Validation du JSON
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            logger.warning(f"JSON invalide depuis {request.remote}")
            return web.Response(status=400, text="Invalid JSON")

        # Validation du schéma minimal — évite les payloads malformés dans l'EventBus
        if not isinstance(data, dict) or "pattern" not in data:
            logger.warning(f"Schéma P2P invalide depuis {request.remote}: {type(data).__name__}")
            return web.Response(status=400, text="Invalid schema")

        logger.info(f"📥 Réception d'une menace depuis {request.remote}: {data.get('pattern', '?')}")
        self.event_bus.publish("cyber.threat", data, "p2p")
        return web.Response(text="OK")

    async def _handle_get_peers(self, request):
        """Retourne la liste des pairs connus."""
        return web.json_response(list(self.peers))

    async def broadcast_threat(self, threat_data: Dict[str, Any]):
        """Diffuse une menace à tous les pairs connus avec signature HMAC-SHA256."""
        body_bytes = json.dumps(threat_data).encode("utf-8")
        signature = hmac.new(
            self.shared_key.encode("utf-8"),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()
        for peer in self.peers:
            try:
                url = f"http://{peer}/threat"
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        data=body_bytes,
                        headers={"Content-Type": "application/json", "X-Signature": signature},
                        timeout=aiohttp.ClientTimeout(total=2),
                    ) as resp:
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
