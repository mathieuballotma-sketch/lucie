from __future__ import annotations
import asyncio
import json
import logging
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_encryption = None

def _get_encryption():
    """Lazy init — évite crash si cryptography absent."""
    global _encryption
    if _encryption is None:
        from app.p2p.encryption import LucieEncryption
        _encryption = LucieEncryption()
    return _encryption

PEERS_DB = Path("memory/journals/peers.jsonl")

@dataclass
class LucieNode:
    """Un noeud Lucie sur le reseau."""
    host: str
    port: int
    node_id: str
    last_seen: float = field(default_factory=time.time)
    version: str = "1.0"
    healthy: bool = True

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "node_id": self.node_id,
            "last_seen": self.last_seen,
            "version": self.version,
            "healthy": self.healthy,
        }


class NetworkManager:
    """
    Gestionnaire P2P pour Lucie.
    Decouverte : mDNS local + ping reseau.
    Protocole  : HTTP leger sur port 7700.
    """

    DEFAULT_PORT = 7700

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.port = port
        self.node_id = self._generate_node_id()
        self._peers: Dict[str, LucieNode] = {}
        self._server: Optional[asyncio.Server] = None
        self._running: bool = False
        PEERS_DB.parent.mkdir(parents=True, exist_ok=True)
        self._load_known_peers()
        logger.info(f"NetworkManager init — node_id: {self.node_id} port: {port}")

    def _generate_node_id(self) -> str:
        import hashlib
        return hashlib.blake2b(
            f"{socket.gethostname()}{time.time()}".encode(), digest_size=6
        ).hexdigest()

    _MAX_PORT_RETRIES = 5

    async def start(self, _retry: int = 0) -> bool:
        """Demarre le serveur P2P et la decouverte."""
        try:
            self._server = await asyncio.start_server(
                self._handle_connection,
                "127.0.0.1", self.port,
            )
            self._running = True
            logger.info(f"Serveur P2P actif sur port {self.port}")

            # Decouverte en arriere-plan
            self._discovery_task = asyncio.ensure_future(self._discovery_loop())
            return True
        except OSError as e:
            if _retry >= self._MAX_PORT_RETRIES:
                logger.error(f"Impossible de demarrer P2P apres {_retry} tentatives")
                return False
            logger.warning(f"Port {self.port} occupe : {e}")
            self.port += 1
            return await self.start(_retry=_retry + 1)

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Gere une connexion entrante d'un autre noeud."""
        try:
            data = await asyncio.wait_for(reader.read(65536), timeout=5.0)
            raw = json.loads(data.decode("utf-8"))
            if raw.get("v") == 1:
                message = _get_encryption().decrypt_from_b64(raw.get("e",""))
                if message is None:
                    writer.write(json.dumps({"error":"decrypt_failed"}).encode())
                    await writer.drain()
                    return
            else:
                message = raw
            response = await self._process_message(message)
            enc_response = _get_encryption().encrypt_to_b64(response, self.node_id)
            writer.write(json.dumps({"v":1,"e":enc_response}).encode("utf-8"))
            await writer.drain()
        except Exception as e:
            logger.debug(f"Erreur connexion : {e}")
        finally:
            writer.close()

    async def _process_message(self, msg: dict) -> dict:
        """Traite un message P2P entrant."""
        msg_type = msg.get("type")

        if msg_type == "ping":
            # Enregistre le pair
            peer = LucieNode(
                host=msg.get("host",""),
                port=msg.get("port", self.DEFAULT_PORT),
                node_id=msg.get("node_id",""),
            )
            self._peers[peer.node_id] = peer
            self._save_peer(peer)
            return {
                "type": "pong",
                "node_id": self.node_id,
                "port": self.port,
                "peers": len(self._peers),
            }

        if msg_type == "get_logs":
            # Wanderer demande les machine_logs
            logs = self._get_recent_logs(limit=msg.get("limit", 50))
            return {"type": "logs", "data": logs}

        if msg_type == "share_fix":
            # Un autre noeud partage un correctif
            fix = msg.get("fix", {})
            self._apply_shared_fix(fix)
            return {"type": "ack", "received": True}

        if msg_type == "share_examples":
            # Partage de nouveaux exemples d'entrainement
            examples = msg.get("examples", [])
            self._apply_shared_examples(examples)
            return {"type": "ack", "count": len(examples)}

        return {"type": "unknown"}

    async def send(self, peer: LucieNode, message: dict) -> Optional[dict]:
        """Envoie un message a un pair."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(peer.host, peer.port),
                timeout=5.0,
            )
            encrypted = _get_encryption().encrypt_to_b64(message, self.node_id)
            writer.write(json.dumps({"v":1,"e":encrypted}).encode("utf-8"))
            await writer.drain()
            data = await asyncio.wait_for(reader.read(65536), timeout=5.0)
            writer.close()
            peer.last_seen = time.time()
            peer.healthy = True
            raw = json.loads(data.decode("utf-8"))
            if raw.get("v") == 1:
                return _get_encryption().decrypt_from_b64(raw.get("e",""))
            return raw
        except Exception as e:
            logger.debug(f"Erreur envoi a {peer.address} : {e}")
            peer.healthy = False
            return None

    async def ping_peer(self, host: str, port: int) -> Optional[LucieNode]:
        """Ping un noeud potentiel."""
        my_ip = self._get_local_ip()
        msg = {
            "type": "ping",
            "node_id": self.node_id,
            "host": my_ip,
            "port": self.port,
        }
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=3.0,
            )
            encrypted = _get_encryption().encrypt_to_b64(msg, self.node_id)
            writer.write(json.dumps({"v":1,"e":encrypted}).encode("utf-8"))
            await writer.drain()
            data = await asyncio.wait_for(reader.read(4096), timeout=3.0)
            writer.close()
            raw = json.loads(data.decode("utf-8"))
            resp = _get_encryption().decrypt_from_b64(raw.get("e","")) if raw.get("v")==1 else raw
            if resp is None:
                return None
            if resp.get("type") == "pong":
                peer = LucieNode(
                    host=host,
                    port=port,
                    node_id=resp.get("node_id",""),
                )
                self._peers[peer.node_id] = peer
                self._save_peer(peer)
                logger.info(f"Pair decouvert : {peer.address} ({peer.node_id})")
                return peer
        except Exception as _e:
            logger.debug(f"Découverte pair échouée ({host}:{port}) : {_e}")
        return None

    async def _discovery_loop(self) -> None:
        """Decouverte continue des noeuds Lucie sur le reseau local."""
        while self._running:
            await self._scan_local_network()
            await asyncio.sleep(30)  # Scan toutes les 30s

    async def _scan_local_network(self) -> None:
        """Scan le reseau local pour trouver d'autres instances Lucie."""
        local_ip = self._get_local_ip()
        base = ".".join(local_ip.split(".")[:3])
        tasks = []
        for i in range(1, 255):
            host = f"{base}.{i}"
            if host != local_ip:
                tasks.append(self.ping_peer(host, self.DEFAULT_PORT))
        # Scan par batch de 20 pour ne pas saturer
        for i in range(0, len(tasks), 20):
            batch = tasks[i:i+20]
            await asyncio.gather(*batch, return_exceptions=True)
            await asyncio.sleep(0.1)

    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _get_recent_logs(self, limit: int = 50) -> list:
        log_path = Path("memory/journals/machine_log.jsonl")
        if not log_path.exists():
            return []
        lines = log_path.read_text(encoding="utf-8").splitlines()
        result = []
        for line in lines[-limit:]:
            try:
                result.append(json.loads(line))
            except Exception:
                continue
        return result

    def _apply_shared_fix(self, fix: dict) -> None:
        fixes_path = Path("memory/journals/fixes.jsonl")
        fix["shared"] = True
        with open(fixes_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(fix, ensure_ascii=False) + "\n")
        logger.info(f"Fix partage applique : {fix.get('pattern','?')}")

    def _apply_shared_examples(self, examples: list) -> None:
        if not examples:
            return
        from app.security.threat_intelligence import ThreatIntelligence
        ti = ThreatIntelligence()
        valid = [
            (t, label) for t, label in examples
            if ti.validate_training_example(t, label)
        ]
        logger.info(f"{len(valid)}/{len(examples)} exemples partages valides")

    def _save_peer(self, peer: LucieNode) -> None:
        with open(PEERS_DB, "a", encoding="utf-8") as f:
            f.write(json.dumps(peer.to_dict(), ensure_ascii=False) + "\n")

    def _load_known_peers(self) -> None:
        if not PEERS_DB.exists():
            return
        seen = set()
        with open(PEERS_DB, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    nid = data.get("node_id","")
                    if nid and nid not in seen:
                        seen.add(nid)
                        self._peers[nid] = LucieNode(**{
                            k:v for k,v in data.items()
                            if k in LucieNode.__dataclass_fields__
                        })
                except Exception:
                    continue
        logger.info(f"{len(self._peers)} pairs connus charges")

    @property
    def peers(self) -> List[LucieNode]:
        return list(self._peers.values())

    @property
    def healthy_peers(self) -> List[LucieNode]:
        return [p for p in self._peers.values() if p.healthy]
