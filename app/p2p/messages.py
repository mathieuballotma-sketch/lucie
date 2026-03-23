"""
Définition des messages échangés entre pairs.
"""

import base64
import json
import time
from typing import Any, Dict

from ..utils.crypto import CryptoManager  # pour signer les messages


class Message:
    """Message signé échangé entre pairs."""

    def __init__(
        self,
        msg_type: str,
        payload: Dict[str, Any],
        sender_id: str,
        crypto: CryptoManager,
    ):
        self.msg_type = msg_type
        self.payload = payload
        self.sender_id = sender_id
        self.timestamp = time.time()
        self.signature = self._sign(crypto)

    def _sign(self, crypto: CryptoManager) -> str:
        """Signe le message avec la clé du nœud (HMAC via Fernet encrypt)."""
        data = f"{self.msg_type}{json.dumps(self.payload)}{self.sender_id}{self.timestamp}"
        # TODO: implémenter sign() dans CryptoManager avec HMAC dédié
        # Pour l'instant, on utilise encrypt comme pseudo-signature
        signature = crypto.encrypt(data.encode())
        return base64.b64encode(signature).decode()

    def verify(self, crypto: CryptoManager, public_key: bytes) -> bool:
        """Vérifie la signature avec la clé du nœud (decrypt via Fernet)."""
        data = f"{self.msg_type}{json.dumps(self.payload)}{self.sender_id}{self.timestamp}"
        # TODO: implémenter verify() dans CryptoManager avec HMAC dédié
        # Pour l'instant, on tente un decrypt pour valider l'intégrité
        try:
            decrypted = crypto.decrypt(base64.b64decode(self.signature))
            return decrypted == data.encode()
        except Exception:
            return False

    def to_json(self) -> str:
        return json.dumps(
            {
                "type": self.msg_type,
                "payload": self.payload,
                "sender": self.sender_id,
                "timestamp": self.timestamp,
                "signature": self.signature,
            }
        )

    @classmethod
    def from_json(cls, data: str) -> "Message":
        obj = json.loads(data)
        msg = cls.__new__(cls)
        msg.msg_type = obj["type"]
        msg.payload = obj["payload"]
        msg.sender_id = obj["sender"]
        msg.timestamp = obj["timestamp"]
        msg.signature = obj["signature"]
        return msg
