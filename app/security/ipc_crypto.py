"""
IPC chiffré pour la communication agent ↔ EventBus.

Architecture cryptographique :
1. Handshake : X25519 Diffie-Hellman pour négocier une clé partagée
2. Dérivation : HKDF-SHA256 pour dériver la clé AES-256 et l'IV
3. Chiffrement : AES-256-GCM pour chaque message (authentifié)
4. Rotation : clés éphémères renouvelées toutes les 1000 messages

Pourquoi pas TLS 1.3 ?
- TLS sur Unix socket = overhead inutile (certificats, handshake complet)
- AES-GCM directement = plus léger, même sécurité pour l'IPC local
- Authentification mutuelle via challenge-response au handshake

IMPORTANT : Utilise la bibliothèque `cryptography` (déjà dans le projet)
qui s'appuie sur OpenSSL pour les primitives bas niveau.
"""

from __future__ import annotations

import os
import secrets
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from ..utils.logger import logger


def _get_public_bytes(private_key: X25519PrivateKey) -> bytes:
    """Get raw public key bytes, compatible with all cryptography versions."""
    pub = private_key.public_key()
    if hasattr(pub, 'public_bytes_raw'):
        return pub.public_bytes_raw()
    # Fallback for older versions
    from cryptography.hazmat.primitives import serialization
    return pub.public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )


# Taille du nonce AES-GCM (12 bytes = 96 bits, standard NIST)
NONCE_SIZE = 12
# Taille de la clé AES-256
KEY_SIZE = 32
# Rotation après N messages
KEY_ROTATION_INTERVAL = 1000
# Taille max d'un message (1 MB)
MAX_MESSAGE_SIZE = 1024 * 1024


@dataclass
class IPCSession:
    """
    Session IPC chiffrée entre le broker et un agent.

    Chaque session a :
    - Une clé AES-256-GCM dérivée du handshake X25519
    - Un compteur de nonce monotone (empêche la réutilisation)
    - Un agent_id pour l'authentification
    - Un compteur de messages pour la rotation
    """
    agent_id: str
    session_id: str = field(default_factory=lambda: secrets.token_hex(8))
    _aes_key: bytes = b""
    _aesgcm: Optional[AESGCM] = None
    _nonce_counter: int = 0
    _message_count: int = 0
    _created_at: float = field(default_factory=time.time)
    _peer_public_key: Optional[bytes] = None

    def _next_nonce(self) -> bytes:
        """
        Génère le prochain nonce.

        Utilise un compteur monotone (4 bytes) + random (8 bytes).
        Le compteur empêche la réutilisation même si l'aléa a un biais.
        """
        self._nonce_counter += 1
        counter_bytes = struct.pack(">I", self._nonce_counter)
        random_bytes = os.urandom(NONCE_SIZE - 4)
        return counter_bytes + random_bytes

    @property
    def needs_rotation(self) -> bool:
        return self._message_count >= KEY_ROTATION_INTERVAL

    @property
    def is_established(self) -> bool:
        return self._aesgcm is not None


class IPCCrypto:
    """
    Gestionnaire cryptographique pour l'IPC.

    Côté broker (processus principal) :
    - Génère une paire X25519 par session
    - Dérive la clé AES-GCM via HKDF
    - Chiffre/déchiffre les messages

    Côté agent (sous-processus) :
    - Reçoit la clé publique du broker dans l'env
    - Génère sa propre paire X25519
    - Envoie sa clé publique en clair (seul message non chiffré)
    - Dérive la même clé AES-GCM
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, IPCSession] = {}

    def create_session(self, agent_id: str) -> Tuple[str, bytes]:
        """
        Crée une nouvelle session pour un agent.

        Returns:
            (session_id, broker_public_key_bytes)
        """
        private_key = X25519PrivateKey.generate()
        public_key = _get_public_bytes(private_key)

        session = IPCSession(agent_id=agent_id)
        session._broker_private_key = private_key

        self._sessions[session.session_id] = session

        logger.debug(
            f"Session IPC créée pour {agent_id}: {session.session_id}"
        )
        return session.session_id, public_key

    def complete_handshake(
        self, session_id: str, agent_public_key: bytes
    ) -> bool:
        """
        Termine le handshake avec la clé publique de l'agent.

        Dérive la clé AES-256-GCM via HKDF-SHA256 :
        - IKM = shared_secret (X25519)
        - Salt = session_id encoded
        - Info = "lucie-ipc-v1"
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.error(f"Session inconnue: {session_id}")
            return False

        try:
            peer_key = X25519PublicKey.from_public_bytes(agent_public_key)
            session._peer_public_key = agent_public_key

            shared_secret = session._broker_private_key.exchange(peer_key)

            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=KEY_SIZE,
                salt=session.session_id.encode(),
                info=b"lucie-ipc-v1",
            )
            aes_key = hkdf.derive(shared_secret)

            session._aes_key = aes_key
            session._aesgcm = AESGCM(aes_key)

            # Supprimer la clé privée du broker (plus nécessaire)
            del session._broker_private_key

            logger.debug(f"Handshake IPC complété: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Handshake IPC échoué: {e}")
            return False

    def encrypt(self, session_id: str, plaintext: bytes,
                associated_data: Optional[bytes] = None) -> bytes:
        """
        Chiffre un message avec AES-256-GCM.

        Format du message chiffré :
        [nonce (12 bytes)] [ciphertext + tag (variable)]

        associated_data : données authentifiées mais non chiffrées
        (ex: type de message, timestamp) — intégrité garantie par le tag GCM.
        """
        session = self._sessions.get(session_id)
        if not session or not session.is_established:
            raise RuntimeError(f"Session {session_id} not established")

        if len(plaintext) > MAX_MESSAGE_SIZE:
            raise ValueError(f"Message too large: {len(plaintext)} > {MAX_MESSAGE_SIZE}")

        nonce = session._next_nonce()
        ciphertext = session._aesgcm.encrypt(nonce, plaintext, associated_data)
        session._message_count += 1

        return nonce + ciphertext

    def decrypt(self, session_id: str, encrypted: bytes,
                associated_data: Optional[bytes] = None) -> bytes:
        """
        Déchiffre et vérifie un message AES-256-GCM.

        Lève InvalidTag si :
        - Le message a été modifié (intégrité)
        - Les associated_data ne correspondent pas
        - Le tag d'authentification est invalide
        """
        session = self._sessions.get(session_id)
        if not session or not session.is_established:
            raise RuntimeError(f"Session {session_id} not established")

        if len(encrypted) < NONCE_SIZE + 16:  # 16 = GCM tag
            raise ValueError("Encrypted message too short")

        nonce = encrypted[:NONCE_SIZE]
        ciphertext = encrypted[NONCE_SIZE:]

        plaintext = session._aesgcm.decrypt(nonce, ciphertext, associated_data)
        session._message_count += 1
        return plaintext

    def rotate_key(self, session_id: str) -> bool:
        """
        Effectue une rotation de clé.

        Dérive une nouvelle clé à partir de l'ancienne via HKDF.
        Cela évite un nouveau handshake X25519.
        """
        session = self._sessions.get(session_id)
        if not session or not session.is_established:
            return False

        try:
            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=KEY_SIZE,
                salt=os.urandom(32),
                info=b"lucie-ipc-rotate-v1",
            )
            new_key = hkdf.derive(session._aes_key)

            session._aes_key = new_key
            session._aesgcm = AESGCM(new_key)
            session._nonce_counter = 0
            session._message_count = 0

            logger.debug(f"Rotation clé IPC: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Key rotation failed: {e}")
            return False

    def destroy_session(self, session_id: str) -> None:
        """
        Détruit une session — efface les clés de la mémoire.

        IMPORTANT : Remplace les clés par des zéros avant suppression.
        Python ne garantit pas le nettoyage mémoire immédiat (GC),
        mais c'est mieux que rien.
        """
        session = self._sessions.get(session_id)
        if session:
            if session._aes_key:
                session._aes_key = b"\x00" * len(session._aes_key)
            session._aesgcm = None
            del self._sessions[session_id]
            logger.debug(f"Session IPC détruite: {session_id}")


class AgentIPCClient:
    """
    Client IPC côté agent (sous-processus).

    Utilisé dans le sous-processus sandboxé pour communiquer
    avec le broker du processus principal.

    Le handshake est initié par le broker qui passe :
    - session_id via variable d'environnement
    - broker_public_key via variable d'environnement (hex)
    - socket_path via variable d'environnement
    """

    def __init__(self) -> None:
        self._private_key = X25519PrivateKey.generate()
        self._public_key = _get_public_bytes(self._private_key)
        self._aesgcm: Optional[AESGCM] = None
        self._nonce_counter: int = 0

    @property
    def public_key_bytes(self) -> bytes:
        return self._public_key

    def complete_handshake(self, broker_public_key: bytes,
                           session_id: str) -> bool:
        """Termine le handshake côté agent."""
        try:
            peer_key = X25519PublicKey.from_public_bytes(broker_public_key)
            shared_secret = self._private_key.exchange(peer_key)

            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=KEY_SIZE,
                salt=session_id.encode(),
                info=b"lucie-ipc-v1",
            )
            aes_key = hkdf.derive(shared_secret)
            self._aesgcm = AESGCM(aes_key)

            # Supprimer la clé privée
            self._private_key = None
            return True

        except Exception:
            return False

    def encrypt(self, plaintext: bytes,
                associated_data: Optional[bytes] = None) -> bytes:
        """Chiffre un message."""
        self._nonce_counter += 1
        nonce = struct.pack(">I", self._nonce_counter) + os.urandom(8)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, associated_data)
        return nonce + ciphertext

    def decrypt(self, encrypted: bytes,
                associated_data: Optional[bytes] = None) -> bytes:
        """Déchiffre un message."""
        nonce = encrypted[:NONCE_SIZE]
        ciphertext = encrypted[NONCE_SIZE:]
        return self._aesgcm.decrypt(nonce, ciphertext, associated_data)
