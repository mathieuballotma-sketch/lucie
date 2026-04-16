"""
SandboxManager — Gère le cycle de vie des agents sandboxés.

Responsabilités :
1. Créer les répertoires de travail isolés
2. Générer les profils sandbox (.sb)
3. Spawn les sous-processus via sandbox-exec
4. Négocier le handshake IPC chiffré
5. Proxy les messages EventBus ↔ agents
6. Monitorer et tuer les processus anormaux

Architecture :
- Chaque agent = 1 sous-processus Python sandboxé
- Communication = Unix domain socket + AES-256-GCM
- Monitoring = ProcessWatchdog (thread dédié)

Contraintes M3 16GB :
- Max 8 processus agents simultanés
- Chaque sous-processus = ~15-30 MB RAM (Python + agent)
- Total overhead sandbox ≈ 120-240 MB
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .sandbox_profiles import (
    AGENT_SANDBOX_MAP, SandboxTier, write_sandbox_profile,
)
from .ipc_crypto import IPCCrypto, MAX_MESSAGE_SIZE
from ..utils.logger import logger


# Constantes
MAX_SANDBOXED_AGENTS = 8
AGENT_STARTUP_TIMEOUT = 10.0   # Secondes pour le handshake
HEALTH_CHECK_INTERVAL = 5.0    # Secondes entre les health checks
CPU_THRESHOLD = 90.0           # % CPU pour alerte
MEMORY_THRESHOLD_MB = 500      # MB par agent pour alerte
SOCKET_DIR = "/tmp/lucie/ipc"
WORK_DIR_BASE = "/tmp/lucie/agents"


@dataclass
class SandboxedAgent:
    """État d'un agent sandboxé."""
    agent_name: str
    pid: int = 0
    process: Optional[subprocess.Popen] = None
    session_id: str = ""
    socket_path: str = ""
    work_dir: str = ""
    profile_path: str = ""
    tier: SandboxTier = SandboxTier.RESTRICTED
    started_at: float = 0.0
    last_health_check: float = 0.0
    healthy: bool = True
    violation_count: int = 0


class SandboxManager:
    """
    Gestionnaire central des agents sandboxés.

    Usage :
        manager = SandboxManager()
        await manager.initialize()
        await manager.spawn_agent("FileAgent")
        result = await manager.send_to_agent("FileAgent", {"query": "..."})
        await manager.terminate_agent("FileAgent")
        await manager.shutdown()
    """

    def __init__(self) -> None:
        self._agents: Dict[str, SandboxedAgent] = {}
        self._crypto = IPCCrypto()
        self._running = False
        self._watchdog_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialise les répertoires et démarre le watchdog."""
        os.makedirs(SOCKET_DIR, mode=0o700, exist_ok=True)
        os.makedirs(WORK_DIR_BASE, mode=0o700, exist_ok=True)

        self._running = True
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

        logger.info("SandboxManager initialisé")

    async def spawn_agent(self, agent_name: str,
                          agent_module: str = "",
                          extra_env: Optional[Dict[str, str]] = None,
                          ) -> bool:
        """
        Lance un agent dans un sandbox.

        Étapes :
        1. Créer le répertoire de travail dédié
        2. Générer le profil sandbox
        3. Créer la session IPC et le socket
        4. Lancer le sous-processus via sandbox-exec
        5. Attendre le handshake

        Args:
            agent_name: Nom de l'agent (ex: "FileAgent")
            agent_module: Module Python de l'agent (auto-détecté si vide)
            extra_env: Variables d'environnement supplémentaires

        Returns:
            True si l'agent est lancé et le handshake complété
        """
        if agent_name in self._agents:
            logger.warning(f"Agent {agent_name} déjà sandboxé")
            return True

        if len(self._agents) >= MAX_SANDBOXED_AGENTS:
            logger.error(
                f"Max agents sandboxés atteint ({MAX_SANDBOXED_AGENTS})"
            )
            return False

        # 1. Répertoire de travail
        work_dir = os.path.join(WORK_DIR_BASE, agent_name.lower())
        os.makedirs(work_dir, mode=0o700, exist_ok=True)

        # 2. Socket path
        socket_path = os.path.join(SOCKET_DIR, f"{agent_name.lower()}.sock")
        if os.path.exists(socket_path):
            os.unlink(socket_path)

        # 3. Profil sandbox
        tier = AGENT_SANDBOX_MAP.get(agent_name, SandboxTier.RESTRICTED)
        profile_path = write_sandbox_profile(
            tier=tier,
            agent_name=agent_name,
            work_dir=work_dir,
            socket_path=socket_path,
        )

        # 4. Session IPC
        session_id, broker_pub_key = self._crypto.create_session(agent_name)

        # 5. Construire la commande
        if not agent_module:
            agent_module = f"app.agents.{self._agent_name_to_module(agent_name)}"

        # Whitelist explicite — ne pas transmettre os.environ en entier
        # (évite de leaker AWS_SECRET_ACCESS_KEY, ANTHROPIC_API_KEY, etc.)
        _ENV_WHITELIST = {"PATH", "HOME", "TMPDIR", "LUCIE_SANDBOX", "OLLAMA_HOST"}
        env = {k: os.environ[k] for k in _ENV_WHITELIST if k in os.environ}
        env.update({
            "LUCIE_SANDBOX": "1",
            "LUCIE_AGENT_NAME": agent_name,
            "LUCIE_SESSION_ID": session_id,
            "LUCIE_BROKER_PUBKEY": broker_pub_key.hex(),
            "LUCIE_SOCKET_PATH": socket_path,
            "LUCIE_WORK_DIR": work_dir,
            **(extra_env or {}),
        })

        cmd = [
            "sandbox-exec",
            "-f", str(profile_path),
            "python3", "-m", "app.security.agent_runner",
            "--agent", agent_module,
            "--name", agent_name,
        ]

        try:
            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(Path(__file__).parent.parent.parent),
            )

            agent_state = SandboxedAgent(
                agent_name=agent_name,
                pid=process.pid,
                process=process,
                session_id=session_id,
                socket_path=socket_path,
                work_dir=work_dir,
                profile_path=str(profile_path),
                tier=tier,
                started_at=time.time(),
            )
            self._agents[agent_name] = agent_state

            # 6. Attendre le handshake
            handshake_ok = await self._wait_handshake(agent_state)

            if not handshake_ok:
                logger.error(f"Handshake timeout pour {agent_name}")
                await self.terminate_agent(agent_name)
                return False

            logger.info(
                f"Agent {agent_name} sandboxé "
                f"(pid={process.pid}, tier={tier.value})"
            )
            return True

        except Exception as e:
            logger.error(f"Spawn agent {agent_name} failed: {e}")
            return False

    async def terminate_agent(self, agent_name: str,
                              force: bool = False) -> None:
        """
        Termine un agent sandboxé.

        1. Envoie SIGTERM (arrêt propre)
        2. Attend 3 secondes
        3. Si toujours vivant → SIGKILL
        4. Nettoie les ressources
        """
        agent = self._agents.get(agent_name)
        if not agent:
            return

        try:
            if agent.process and agent.process.poll() is None:
                if force:
                    agent.process.kill()
                else:
                    agent.process.terminate()
                    try:
                        agent.process.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        agent.process.kill()
                        agent.process.wait(timeout=1.0)

            # Nettoyer les ressources
            self._crypto.destroy_session(agent.session_id)

            if os.path.exists(agent.socket_path):
                os.unlink(agent.socket_path)

            if os.path.exists(agent.work_dir):
                shutil.rmtree(agent.work_dir, ignore_errors=True)

            if os.path.exists(agent.profile_path):
                os.unlink(agent.profile_path)

            del self._agents[agent_name]

            logger.info(f"Agent {agent_name} terminé et nettoyé")

        except Exception as e:
            logger.error(f"Erreur terminaison {agent_name}: {e}")

    async def send_to_agent(self, agent_name: str,
                            message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Envoie un message chiffré à un agent et attend la réponse.

        Le message est sérialisé en JSON, chiffré AES-256-GCM,
        envoyé via le socket Unix, et la réponse est déchiffrée.
        """
        agent = self._agents.get(agent_name)
        if not agent or not agent.healthy:
            return None

        try:
            plaintext = json.dumps(message).encode("utf-8")
            associated_data = agent_name.encode("utf-8")

            encrypted = self._crypto.encrypt(
                agent.session_id, plaintext, associated_data,
            )

            response_encrypted = await self._send_socket(
                agent.socket_path, encrypted,
            )

            if response_encrypted is None:
                return None

            response_plain = self._crypto.decrypt(
                agent.session_id, response_encrypted, associated_data,
            )

            # Rotation si nécessaire
            session = self._crypto._sessions.get(agent.session_id)
            if session and session.needs_rotation:
                self._crypto.rotate_key(agent.session_id)

            return json.loads(response_plain.decode("utf-8"))

        except Exception as e:
            logger.error(f"IPC error with {agent_name}: {e}")
            agent.violation_count += 1
            return None

    async def shutdown(self) -> None:
        """Arrêt propre de tous les agents sandboxés."""
        self._running = False

        if self._watchdog_task:
            self._watchdog_task.cancel()

        for agent_name in list(self._agents.keys()):
            await self.terminate_agent(agent_name)

        for d in [SOCKET_DIR, WORK_DIR_BASE]:
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)

        logger.info("SandboxManager arrêté")

    # ── Handshake ───────────────────────────────────────────────

    async def _wait_handshake(self, agent: SandboxedAgent,
                              timeout: float = AGENT_STARTUP_TIMEOUT) -> bool:
        """
        Attend que l'agent envoie sa clé publique via le socket.

        Protocole :
        1. Agent crée le socket et bind
        2. Agent envoie sa X25519 public key (32 bytes)
        3. Broker complète le handshake
        4. Broker envoie "OK" chiffré comme confirmation
        """
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if os.path.exists(agent.socket_path):
                break
            await asyncio.sleep(0.1)
        else:
            return False

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(agent.socket_path),
                timeout=timeout,
            )

            agent_pub_key = await asyncio.wait_for(
                reader.readexactly(32),
                timeout=5.0,
            )

            ok = self._crypto.complete_handshake(
                agent.session_id, agent_pub_key,
            )

            if ok:
                confirmation = self._crypto.encrypt(
                    agent.session_id,
                    b"HANDSHAKE_OK",
                    agent.agent_name.encode(),
                )
                writer.write(len(confirmation).to_bytes(4, "big"))
                writer.write(confirmation)
                await writer.drain()

            writer.close()
            await writer.wait_closed()

            return ok

        except Exception as e:
            logger.error(f"Handshake error for {agent.agent_name}: {e}")
            return False

    async def _send_socket(self, socket_path: str,
                           data: bytes) -> Optional[bytes]:
        """Envoie des données via Unix socket et lit la réponse."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(socket_path),
                timeout=5.0,
            )

            writer.write(len(data).to_bytes(4, "big"))
            writer.write(data)
            await writer.drain()

            length_bytes = await asyncio.wait_for(
                reader.readexactly(4), timeout=10.0,
            )
            length = int.from_bytes(length_bytes, "big")

            if length > MAX_MESSAGE_SIZE:
                raise ValueError(f"Response too large: {length}")

            response = await asyncio.wait_for(
                reader.readexactly(length), timeout=10.0,
            )

            writer.close()
            await writer.wait_closed()
            return response

        except Exception as e:
            logger.error(f"Socket send error: {e}")
            return None

    # ── Watchdog ────────────────────────────────────────────────

    async def _watchdog_loop(self) -> None:
        """
        Boucle de surveillance des processus sandboxés.

        Toutes les 5 secondes :
        1. Vérifier que chaque processus est vivant
        2. Vérifier CPU et mémoire via psutil
        3. Tuer les processus anormaux (>5 violations)
        """
        try:
            import psutil
        except ImportError:
            logger.warning("psutil non disponible — watchdog désactivé")
            return

        while self._running:
            try:
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)

                for name, agent in list(self._agents.items()):
                    # Processus mort ?
                    if agent.process and agent.process.poll() is not None:
                        exit_code = agent.process.returncode
                        logger.warning(
                            f"Agent {name} mort (exit={exit_code})"
                        )
                        agent.healthy = False
                        continue

                    # Métriques via psutil
                    try:
                        proc = psutil.Process(agent.pid)
                        cpu = proc.cpu_percent(interval=0.1)
                        mem_mb = proc.memory_info().rss / (1024 * 1024)

                        if cpu > CPU_THRESHOLD:
                            agent.violation_count += 1
                            logger.warning(
                                f"Agent {name} CPU élevé: {cpu:.1f}%"
                            )

                        if mem_mb > MEMORY_THRESHOLD_MB:
                            agent.violation_count += 1
                            logger.warning(
                                f"Agent {name} mémoire élevée: {mem_mb:.0f}MB"
                            )

                        # Trop de violations → kill
                        if agent.violation_count >= 5:
                            logger.error(
                                f"Agent {name} terminé: "
                                f"{agent.violation_count} violations"
                            )
                            await self.terminate_agent(name, force=True)

                    except psutil.NoSuchProcess:
                        agent.healthy = False

                    agent.last_health_check = time.time()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Watchdog error: {e}")

    # ── Helpers ─────────────────────────────────────────────────

    def _agent_name_to_module(self, name: str) -> str:
        """Convertit un nom d'agent en nom de module Python."""
        # FileAgent → file_agent
        s = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
        return s

    @property
    def active_agents(self) -> List[str]:
        return [
            name for name, a in self._agents.items()
            if a.healthy and a.process and a.process.poll() is None
        ]

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "active": len(self.active_agents),
            "total_spawned": len(self._agents),
            "agents": {
                name: {
                    "pid": a.pid,
                    "tier": a.tier.value,
                    "healthy": a.healthy,
                    "violations": a.violation_count,
                    "uptime_s": time.time() - a.started_at,
                }
                for name, a in self._agents.items()
            },
        }
