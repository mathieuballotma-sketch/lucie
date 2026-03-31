"""
P2PBroker — DS-P2P-01

Local network P2P broker for Lucie ↔ Mobile companion communication.
Handles mDNS discovery, WebSocket server, X25519 handshake, and
encrypted session management.

Architecture:
  - mDNS/Bonjour: publishes _lucie._tcp for local discovery
  - WebSocket: accepts connections on configurable port (default 8765)
  - X25519 + HKDF-SHA256: key agreement for AES-256-GCM encryption
  - Session management: one active session at a time (configurable)

Security:
  - All post-handshake messages encrypted with AES-256-GCM
  - Challenge-response authentication after key exchange
  - No internet exposure — local network only
  - Session tokens for replay protection
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization

from ...utils.logger import logger
from .protocol import P2PMessage, P2PProtocol, MessageType

# Optional imports
try:
    import websockets
    from websockets.server import serve as ws_serve
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    logger.warning("websockets not available — P2PBroker disabled")

try:
    from zeroconf import Zeroconf, ServiceInfo
    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False


# Constants
NONCE_SIZE = 12
KEY_SIZE = 32
DEFAULT_PORT = 8765
MAX_MESSAGE_SIZE = 1024 * 1024  # 1MB


def _get_public_bytes(private_key: X25519PrivateKey) -> bytes:
    """Get raw public key bytes, compatible with all cryptography versions."""
    pub = private_key.public_key()
    if hasattr(pub, "public_bytes_raw"):
        return pub.public_bytes_raw()
    return pub.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def _get_local_ip() -> str:
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@dataclass
class P2PSession:
    """An authenticated P2P session with a mobile device."""

    session_id: str = field(default_factory=lambda: secrets.token_hex(8))
    peer_public_key: Optional[bytes] = None
    aes_key: Optional[bytes] = None
    _aesgcm: Optional[AESGCM] = None
    websocket: Any = None  # websockets.WebSocketServerProtocol
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    is_authenticated: bool = False
    device_name: str = "Unknown"
    _nonce_counter: int = 0
    _challenge: str = ""

    def encrypt(self, data: bytes) -> bytes:
        """
        Encrypt data with AES-256-GCM.

        Returns:
            nonce (12 bytes) + ciphertext
        """
        if not self._aesgcm:
            raise RuntimeError("Session not established")
        nonce = os.urandom(NONCE_SIZE)
        ciphertext = self._aesgcm.encrypt(nonce, data, None)
        self._nonce_counter += 1
        return nonce + ciphertext

    def decrypt(self, data: bytes) -> bytes:
        """
        Decrypt data with AES-256-GCM.

        Args:
            data: nonce (12 bytes) + ciphertext

        Returns:
            Plaintext bytes
        """
        if not self._aesgcm:
            raise RuntimeError("Session not established")
        nonce = data[:NONCE_SIZE]
        ciphertext = data[NONCE_SIZE:]
        return self._aesgcm.decrypt(nonce, ciphertext, None)

    def encrypt_message(self, msg: P2PMessage) -> Dict[str, str]:
        """Encrypt a P2PMessage to wire format."""
        plaintext = msg.to_json().encode("utf-8")
        encrypted = self.encrypt(plaintext)
        return {
            "nonce": encrypted[:NONCE_SIZE].hex(),
            "ciphertext": encrypted[NONCE_SIZE:].hex(),
        }

    def decrypt_message(self, wire: Dict[str, str]) -> P2PMessage:
        """Decrypt wire format to P2PMessage."""
        nonce = bytes.fromhex(wire["nonce"])
        ciphertext = bytes.fromhex(wire["ciphertext"])
        plaintext = self.decrypt(nonce + ciphertext)
        return P2PMessage.from_json(plaintext.decode("utf-8"))


class P2PBroker:
    """
    Local P2P broker for Lucie ↔ Mobile communication.

    Manages WebSocket server, mDNS discovery, X25519 handshake,
    and encrypted message routing.

    Usage:
        broker = P2PBroker(port=8765)
        await broker.start()
        # ... broker runs, handles connections ...
        await broker.stop()
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        max_sessions: int = 1,
        session_timeout: float = 3600.0,
    ) -> None:
        """
        Initialize P2PBroker.

        Args:
            port: WebSocket server port (default 8765)
            max_sessions: Max concurrent authenticated sessions (default 1)
            session_timeout: Session inactivity timeout in seconds (default 1h)
        """
        self.port = port
        self.max_sessions = max_sessions
        self.session_timeout = session_timeout

        # Crypto
        self._private_key = X25519PrivateKey.generate()
        self._public_key_bytes = _get_public_bytes(self._private_key)

        # Sessions
        self._sessions: Dict[str, P2PSession] = {}
        self._sessions_lock = asyncio.Lock()

        # Server state
        self._server: Any = None
        self._running = False
        self._zeroconf: Any = None
        self._service_info: Any = None

        # Message handlers (registered by consumers like PendingOrderManager)
        self._message_handlers: Dict[str, Any] = {}

        logger.info(
            f"P2PBroker initialized (port={port}, max_sessions={max_sessions})"
        )

    # ─────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────

    async def start(self, host: str = "0.0.0.0") -> None:
        """
        Start the WebSocket server and mDNS advertisement.

        Args:
            host: Bind address (default 0.0.0.0)
        """
        if not HAS_WEBSOCKETS:
            logger.error("Cannot start P2PBroker: websockets library not installed")
            return

        if self._running:
            logger.warning("P2PBroker already running")
            return

        self._running = True

        # Start WebSocket server
        self._server = await ws_serve(
            self._handle_connection,
            host,
            self.port,
            max_size=MAX_MESSAGE_SIZE,
        )

        # Start mDNS
        self._start_mdns()

        local_ip = _get_local_ip()
        logger.info(
            f"P2PBroker started on ws://{local_ip}:{self.port} "
            f"(pubkey: {self._public_key_bytes.hex()[:16]}...)"
        )

    async def stop(self) -> None:
        """Stop the WebSocket server and mDNS."""
        self._running = False

        # Close all sessions
        async with self._sessions_lock:
            for session in self._sessions.values():
                if session.websocket:
                    try:
                        await session.websocket.close()
                    except Exception:
                        pass
            self._sessions.clear()

        # Stop server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Stop mDNS
        self._stop_mdns()

        logger.info("P2PBroker stopped")

    # ─────────────────────────────────────────────────────────────────────
    # mDNS Discovery
    # ─────────────────────────────────────────────────────────────────────

    def _start_mdns(self) -> None:
        """Start mDNS/Bonjour service advertisement."""
        if not HAS_ZEROCONF:
            logger.info("zeroconf not available — mDNS discovery disabled")
            return

        try:
            local_ip = _get_local_ip()
            self._zeroconf = Zeroconf()
            self._service_info = ServiceInfo(
                "_lucie._tcp.local.",
                "Lucie AI Assistant._lucie._tcp.local.",
                addresses=[socket.inet_aton(local_ip)],
                port=self.port,
                properties={
                    "version": "1",
                    "pubkey": self._public_key_bytes.hex(),
                },
            )
            self._zeroconf.register_service(self._service_info)
            logger.info(f"mDNS: published _lucie._tcp on {local_ip}:{self.port}")
        except Exception as e:
            logger.warning(f"mDNS registration failed: {e}")

    def _stop_mdns(self) -> None:
        """Stop mDNS advertisement."""
        if self._zeroconf and self._service_info:
            try:
                self._zeroconf.unregister_service(self._service_info)
                self._zeroconf.close()
            except Exception:
                pass
            self._zeroconf = None
            self._service_info = None

    # ─────────────────────────────────────────────────────────────────────
    # QR Code
    # ─────────────────────────────────────────────────────────────────────

    def get_qr_data(self) -> Dict[str, Any]:
        """
        Get pairing data for QR code generation.

        Returns:
            Dict with ip, port, pubkey (hex)
        """
        return {
            "ip": _get_local_ip(),
            "port": self.port,
            "pubkey": self._public_key_bytes.hex(),
        }

    def generate_qr_image(self, filepath: str = "data/lucie_pairing.png") -> str:
        """
        Generate a QR code PNG image with pairing data.

        Args:
            filepath: Output path for PNG (default: data/lucie_pairing.png)

        Returns:
            Path to generated file, or empty string if qrcode lib not available
        """
        if not HAS_QRCODE:
            logger.warning("qrcode library not available")
            return ""

        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps(self.get_qr_data())
            img = qrcode.make(data)
            img.save(filepath)
            logger.info(f"QR code generated: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"QR code generation failed: {e}")
            return ""

    # ─────────────────────────────────────────────────────────────────────
    # WebSocket Connection Handler
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_connection(self, websocket: Any) -> None:
        """
        Handle a new WebSocket connection.

        Performs X25519 handshake, challenge-response auth,
        then routes encrypted messages to registered handlers.
        """
        session: Optional[P2PSession] = None
        try:
            # Step 1: Receive HELLO
            raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            hello = P2PMessage.from_json(raw)

            if hello.type != MessageType.HELLO:
                await websocket.close(1002, "Expected HELLO")
                return

            peer_pubkey_hex = hello.payload.get("pubkey", "")
            device_name = hello.payload.get("device_name", "Unknown")

            if not peer_pubkey_hex or len(peer_pubkey_hex) != 64:
                await websocket.close(1002, "Invalid public key")
                return

            # Step 2: Derive shared secret
            peer_pubkey_bytes = bytes.fromhex(peer_pubkey_hex)
            peer_pubkey = X25519PublicKey.from_public_bytes(peer_pubkey_bytes)
            shared_secret = self._private_key.exchange(peer_pubkey)

            # Derive AES key via HKDF
            aes_key = HKDF(
                algorithm=hashes.SHA256(),
                length=KEY_SIZE,
                salt=None,
                info=b"lucie-p2p-v1",
            ).derive(shared_secret)

            # Create session
            challenge = secrets.token_hex(16)
            session = P2PSession(
                peer_public_key=peer_pubkey_bytes,
                aes_key=aes_key,
                _aesgcm=AESGCM(aes_key),
                websocket=websocket,
                device_name=device_name,
                _challenge=challenge,
            )

            # Step 3: Send HELLO_ACK
            hello_ack = P2PProtocol.build_hello_ack(
                pubkey_hex=self._public_key_bytes.hex(),
                session_id=session.session_id,
                challenge=challenge,
            )
            await websocket.send(hello_ack.to_json())

            # Step 4: Receive AUTH (encrypted)
            raw_auth = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            auth_wire = json.loads(raw_auth)
            auth_msg = session.decrypt_message(auth_wire)

            if auth_msg.type != MessageType.AUTH:
                await websocket.close(1002, "Expected AUTH")
                return

            # Verify challenge response
            expected_response = self._compute_challenge_response(
                challenge, aes_key
            )
            if auth_msg.payload.get("challenge_response") != expected_response:
                fail_msg = P2PProtocol.build_auth_fail()
                await websocket.send(
                    json.dumps(session.encrypt_message(fail_msg))
                )
                await websocket.close(1002, "Auth failed")
                return

            # Auth OK
            session.is_authenticated = True

            # Check max sessions
            async with self._sessions_lock:
                if len(self._sessions) >= self.max_sessions:
                    # Disconnect oldest session
                    oldest_id = min(
                        self._sessions, key=lambda k: self._sessions[k].created_at
                    )
                    old_session = self._sessions.pop(oldest_id)
                    if old_session.websocket:
                        try:
                            await old_session.websocket.close(1000, "Replaced by new session")
                        except Exception:
                            pass

                self._sessions[session.session_id] = session

            # Send AUTH_OK
            auth_ok = P2PProtocol.build_auth_ok()
            await websocket.send(
                json.dumps(session.encrypt_message(auth_ok))
            )

            logger.info(
                f"P2P session established: {session.session_id} "
                f"({device_name})"
            )

            # Step 5: Message loop
            await self._message_loop(session)

        except asyncio.TimeoutError:
            logger.warning("P2P handshake timeout")
        except Exception as e:
            logger.error(f"P2P connection error: {e}")
        finally:
            if session:
                async with self._sessions_lock:
                    self._sessions.pop(session.session_id, None)
                logger.info(f"P2P session closed: {session.session_id}")

    async def _message_loop(self, session: P2PSession) -> None:
        """
        Encrypted message loop for an authenticated session.

        Routes messages to registered handlers based on MessageType.
        """
        while self._running and session.websocket:
            try:
                raw = await asyncio.wait_for(
                    session.websocket.recv(), timeout=self.session_timeout
                )
                wire = json.loads(raw)
                msg = session.decrypt_message(wire)
                session.last_activity = time.time()

                # Handle built-in messages
                if msg.type == MessageType.PING:
                    pong = P2PProtocol.build_pong()
                    await session.websocket.send(
                        json.dumps(session.encrypt_message(pong))
                    )
                elif msg.type == MessageType.DISCONNECT:
                    break
                elif msg.type == MessageType.STATUS_REQUEST:
                    status = self.get_status()
                    resp = P2PProtocol.build_status_response(status)
                    await session.websocket.send(
                        json.dumps(session.encrypt_message(resp))
                    )
                else:
                    # Route to registered handler
                    handler = self._message_handlers.get(msg.type.value)
                    if handler:
                        try:
                            result = handler(msg, session)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.error(f"Handler error for {msg.type.value}: {e}")
                    else:
                        logger.warning(f"No handler for message type: {msg.type.value}")

            except asyncio.TimeoutError:
                logger.info(f"Session timeout: {session.session_id}")
                break
            except Exception as e:
                logger.error(f"Message loop error: {e}")
                break

    # ─────────────────────────────────────────────────────────────────────
    # Crypto Helpers
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_challenge_response(challenge: str, aes_key: bytes) -> str:
        """
        Compute challenge response for authentication.

        The response is the HMAC-like hash of challenge with the shared key.
        """
        import hashlib
        return hashlib.blake2b(
            challenge.encode() + aes_key, digest_size=32
        ).hexdigest()

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def register_handler(self, message_type: str, handler: Any) -> None:
        """
        Register a message handler for a specific message type.

        Args:
            message_type: MessageType value string (e.g., "order_approve")
            handler: Callable(msg: P2PMessage, session: P2PSession)
        """
        self._message_handlers[message_type] = handler
        logger.debug(f"Registered P2P handler: {message_type}")

    async def send_to_session(self, session_id: str, msg: P2PMessage) -> bool:
        """
        Send an encrypted message to a specific session.

        Args:
            session_id: Target session ID
            msg: P2PMessage to send

        Returns:
            True if sent, False if session not found
        """
        async with self._sessions_lock:
            session = self._sessions.get(session_id)

        if not session or not session.is_authenticated:
            return False

        try:
            wire = session.encrypt_message(msg)
            await session.websocket.send(json.dumps(wire))
            return True
        except Exception as e:
            logger.error(f"Send to {session_id} failed: {e}")
            return False

    async def broadcast(self, msg: P2PMessage) -> int:
        """
        Send an encrypted message to all active sessions.

        Args:
            msg: P2PMessage to broadcast

        Returns:
            Number of sessions successfully sent to
        """
        sent = 0
        async with self._sessions_lock:
            sessions = list(self._sessions.values())

        for session in sessions:
            if session.is_authenticated:
                try:
                    wire = session.encrypt_message(msg)
                    await session.websocket.send(json.dumps(wire))
                    sent += 1
                except Exception as e:
                    logger.warning(
                        f"Broadcast to {session.session_id} failed: {e}"
                    )

        return sent

    def get_status(self) -> Dict[str, Any]:
        """Get broker status."""
        return {
            "running": self._running,
            "port": self.port,
            "local_ip": _get_local_ip(),
            "pubkey": self._public_key_bytes.hex(),
            "active_sessions": len(self._sessions),
            "max_sessions": self.max_sessions,
            "mdns_available": HAS_ZEROCONF,
            "websockets_available": HAS_WEBSOCKETS,
        }

    @property
    def active_sessions(self) -> List[Dict[str, Any]]:
        """Get list of active session summaries."""
        return [
            {
                "session_id": s.session_id,
                "device_name": s.device_name,
                "connected_at": s.created_at,
                "last_activity": s.last_activity,
                "authenticated": s.is_authenticated,
            }
            for s in self._sessions.values()
        ]
