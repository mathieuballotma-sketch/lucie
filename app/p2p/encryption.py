from __future__ import annotations
import base64
import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
KEY_PATH = Path("config/lucie_network.key")

class LucieEncryption:
    """
    Chiffrement P2P pour le reseau Lucie.
    Algo    : Fernet (AES-128-CBC + HMAC-SHA256)
    Cle     : partagee entre toutes les instances
    Format  : {encrypted: b64, ts: float, node_id: str}
    """

    def __init__(self) -> None:
        self._fernet = None
        self._key: Optional[bytes] = None
        self._load_or_create_key()

    def _load_or_create_key(self) -> None:
        """Charge la cle existante ou en cree une nouvelle."""
        from cryptography.fernet import Fernet
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)

        if KEY_PATH.exists():
            self._key = KEY_PATH.read_bytes().strip()
            logger.info(f"Cle reseau chargee : {KEY_PATH}")
        else:
            self._key = Fernet.generate_key()
            KEY_PATH.write_bytes(self._key)
            KEY_PATH.chmod(0o600)  # Lecture seule proprietaire
            logger.info(f"Nouvelle cle reseau generee : {KEY_PATH}")

        self._fernet = Fernet(self._key)

    def encrypt(self, data: dict, node_id: str = "") -> bytes:
        """
        Chiffre un message P2P.
        Ajoute timestamp + node_id pour replay protection.
        """
        payload = {
            "data": data,
            "ts": time.time(),
            "node_id": node_id,
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        encrypted = self._fernet.encrypt(raw)
        return encrypted

    def decrypt(self, encrypted: bytes, max_age: float = 30.0) -> Optional[dict]:
        """
        Dechiffre un message P2P.
        Verifie le timestamp — rejette les messages > max_age secondes.
        Retourne None si invalide.
        """
        try:
            raw = self._fernet.decrypt(encrypted)
            payload = json.loads(raw.decode("utf-8"))

            # Protection replay — rejette les vieux messages
            age = time.time() - payload.get("ts", 0)
            if age > max_age:
                logger.warning(f"Message trop vieux rejete : {age:.0f}s")
                return None

            return payload.get("data")
        except Exception as e:
            logger.warning(f"Dechiffrement echoue : {e}")
            return None

    def encrypt_to_b64(self, data: dict, node_id: str = "") -> str:
        """Version base64 pour transport JSON."""
        return base64.b64encode(self.encrypt(data, node_id)).decode("utf-8")

    def decrypt_from_b64(self, b64: str, max_age: float = 30.0) -> Optional[dict]:
        """Dechiffre depuis base64."""
        try:
            encrypted = base64.b64decode(b64.encode("utf-8"))
            return self.decrypt(encrypted, max_age)
        except Exception as e:
            logger.warning(f"Erreur b64 decode : {e}")
            return None

    def export_key(self) -> str:
        """Exporte la cle en base64 pour la partager avec d'autres instances."""
        return base64.b64encode(self._key).decode("utf-8")

    def import_key(self, key_b64: str) -> bool:
        """Importe une cle partagee depuis une autre instance."""
        try:
            from cryptography.fernet import Fernet
            key = base64.b64decode(key_b64.encode("utf-8"))
            self._key = key
            self._fernet = Fernet(key)
            KEY_PATH.write_bytes(key)
            KEY_PATH.chmod(0o600)
            logger.info("Cle reseau importee avec succes")
            return True
        except Exception as e:
            logger.error(f"Erreur import cle : {e}")
            return False

    @property
    def key_fingerprint(self) -> str:
        """Empreinte courte de la cle — pour verifier que 2 noeuds partagent la meme."""
        import hashlib
        return hashlib.blake2b(self._key, digest_size=8).hexdigest()
