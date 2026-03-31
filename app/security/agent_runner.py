"""
Point d'entrée pour les agents sandboxés.

Ce script est exécuté dans le sous-processus via :
    sandbox-exec -f profile.sb python3 -m app.security.agent_runner \\
        --agent app.agents.file_agent --name FileAgent

Il :
1. Lit les variables d'environnement (session_id, broker_pubkey, socket_path)
2. Crée le socket Unix et bind
3. Effectue le handshake X25519 avec le broker
4. Boucle d'écoute : reçoit des messages chiffrés, exécute l'agent, renvoie

IMPORTANT : Ce script tourne dans le sandbox.
Il n'a accès qu'aux ressources autorisées par le profil .sb.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any, Optional

# Ajouter le projet au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.security.ipc_crypto import AgentIPCClient, NONCE_SIZE


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", required=True, help="Module de l'agent")
    parser.add_argument("--name", required=True, help="Nom de l'agent")
    args = parser.parse_args()

    # Lire l'environnement
    session_id = os.environ.get("LUCIE_SESSION_ID", "")
    broker_pubkey_hex = os.environ.get("LUCIE_BROKER_PUBKEY", "")
    socket_path = os.environ.get("LUCIE_SOCKET_PATH", "")

    if not all([session_id, broker_pubkey_hex, socket_path]):
        print("Variables d'environnement manquantes", file=sys.stderr)
        sys.exit(1)

    broker_pubkey = bytes.fromhex(broker_pubkey_hex)

    # Créer le client IPC
    ipc = AgentIPCClient()

    # Créer le socket Unix et bind
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(socket_path)
        sock.listen(1)
        sock.setblocking(False)

        # Attendre la connexion du broker pour le handshake
        loop = asyncio.get_event_loop()
        conn, _ = await asyncio.wait_for(
            loop.sock_accept(sock), timeout=10.0,
        )

        # Envoyer notre clé publique (32 bytes)
        await loop.sock_sendall(conn, ipc.public_key_bytes)

        # Compléter le handshake
        ipc.complete_handshake(broker_pubkey, session_id)

        # Recevoir la confirmation chiffrée
        length_bytes = await _recv_exact(loop, conn, 4)
        length = int.from_bytes(length_bytes, "big")
        encrypted_confirm = await _recv_exact(loop, conn, length)
        confirmation = ipc.decrypt(encrypted_confirm, args.name.encode())

        if confirmation != b"HANDSHAKE_OK":
            print("Handshake failed", file=sys.stderr)
            sys.exit(1)

        conn.close()

        print(f"Agent {args.name} sandboxé et connecté")

        # Charger l'agent
        agent = _load_agent(args.agent, args.name)
        if agent is None:
            print(f"Cannot load agent {args.agent}", file=sys.stderr)
            sys.exit(1)

        # Boucle principale
        await _message_loop(sock, loop, ipc, agent, args.name)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Agent {args.name} error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        sock.close()
        if os.path.exists(socket_path):
            os.unlink(socket_path)


async def _message_loop(
    sock: socket.socket,
    loop: asyncio.AbstractEventLoop,
    ipc: AgentIPCClient,
    agent: Any,
    agent_name: str,
) -> None:
    """Boucle de réception des messages chiffrés."""
    while True:
        try:
            conn, _ = await loop.sock_accept(sock)
            try:
                # Lire le message
                length_bytes = await _recv_exact(loop, conn, 4)
                length = int.from_bytes(length_bytes, "big")
                encrypted = await _recv_exact(loop, conn, length)

                # Déchiffrer
                plaintext = ipc.decrypt(encrypted, agent_name.encode())
                message = json.loads(plaintext.decode("utf-8"))

                # Exécuter l'agent
                result = await _execute_agent(agent, message)

                # Chiffrer et renvoyer
                response = json.dumps(result).encode("utf-8")
                encrypted_resp = ipc.encrypt(response, agent_name.encode())
                await loop.sock_sendall(
                    conn,
                    len(encrypted_resp).to_bytes(4, "big") + encrypted_resp,
                )

            finally:
                conn.close()

        except Exception as e:
            print(f"Message loop error: {e}", file=sys.stderr)


async def _execute_agent(agent: Any, message: dict) -> dict:
    """Exécute l'agent et retourne le résultat."""
    query = message.get("query", "")
    try:
        if hasattr(agent, "execute"):
            result = await agent.execute(query)
        elif hasattr(agent, "handle"):
            result = await agent.handle(query)
        else:
            result = "Agent has no execute/handle method"
        return {"result": str(result), "error": None}
    except Exception as e:
        return {"result": None, "error": str(e)}


def _load_agent(module_path: str, name: str) -> Optional[Any]:
    """Charge dynamiquement un agent depuis son module."""
    try:
        module = importlib.import_module(module_path)
        for attr_name in dir(module):
            cls = getattr(module, attr_name)
            if (isinstance(cls, type) and
                    hasattr(cls, "execute") and
                    attr_name != "BaseAgent"):
                return cls(name=name, llm_service=None, bus=None)
        return None
    except Exception as e:
        print(f"Cannot load {module_path}: {e}", file=sys.stderr)
        return None


async def _recv_exact(loop: asyncio.AbstractEventLoop,
                      conn: socket.socket, n: int) -> bytes:
    """Lit exactement n bytes depuis un socket."""
    data = b""
    while len(data) < n:
        chunk = await loop.sock_recv(conn, n - len(data))
        if not chunk:
            raise ConnectionError("Connection closed")
        data += chunk
    return data


if __name__ == "__main__":
    asyncio.run(main())
