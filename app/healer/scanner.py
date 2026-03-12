"""
Scanner de fichiers - Détection de menaces par signatures et heuristique.
"""

import hashlib
import os
from typing import Dict, Any, List, Optional
import aiofiles
import yara  # À installer: pip install yara-python

from app.utils.logger import logger


class FileScanner:
    """
    Scanner de fichiers utilisant des signatures YARA et des vérifications heuristiques.
    """

    def __init__(self, config: dict):
        self.config = config
        self.rules = self._load_rules()
        self.known_hashes = self._load_known_hashes()  # Base de hash malveillants

    def _load_rules(self) -> Optional[yara.Rules]:
        """Charge les règles YARA depuis un fichier."""
        rules_path = self.config.get("yara_rules_path", "~/.agent_lucide/yara_rules.yar")
        rules_path = os.path.expanduser(rules_path)
        if os.path.exists(rules_path):
            try:
                return yara.compile(filepath=rules_path)
            except Exception as e:
                logger.error(f"Erreur chargement règles YARA: {e}")
        return None

    def _load_known_hashes(self) -> set:
        """Charge une liste de hash malveillants (SHA256) depuis un fichier."""
        hash_file = self.config.get("malicious_hashes_path", "~/.agent_lucide/malicious_hashes.txt")
        hash_file = os.path.expanduser(hash_file)
        hashes = set()
        if os.path.exists(hash_file):
            with open(hash_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        hashes.add(line.lower())
        return hashes

    async def scan(self, filepath: str) -> Dict[str, Any]:
        """
        Analyse un fichier et retourne un dict avec les résultats.
        """
        result = {
            "threat_detected": False,
            "score": 0.0,
            "matches": [],
            "hash": None,
            "size": 0,
        }

        if not os.path.isfile(filepath):
            return result

        # Taille du fichier
        result["size"] = os.path.getsize(filepath)

        # Calcul du hash SHA256
        sha256 = hashlib.sha256()
        try:
            async with aiofiles.open(filepath, 'rb') as f:
                while chunk := await f.read(8192):
                    sha256.update(chunk)
            file_hash = sha256.hexdigest()
            result["hash"] = file_hash

            # Vérification dans la base de hash connus
            if file_hash in self.known_hashes:
                result["threat_detected"] = True
                result["score"] = 1.0
                result["matches"].append(f"Hash malveillant connu: {file_hash}")
                return result
        except Exception as e:
            logger.error(f"Erreur lecture fichier {filepath}: {e}")
            return result

        # Scan YARA si des règles sont chargées
        if self.rules:
            try:
                matches = self.rules.match(filepath)
                if matches:
                    result["threat_detected"] = True
                    result["score"] = max(result["score"], 0.8)
                    for m in matches:
                        result["matches"].append(f"Règle YARA: {m.rule}")
            except Exception as e:
                logger.error(f"Erreur scan YARA {filepath}: {e}")

        # Heuristique basique : extension suspecte
        ext = os.path.splitext(filepath)[1].lower()
        suspicious_ext = ['.exe', '.bat', '.cmd', '.ps1', '.vbs', '.js', '.jar', '.dll']
        if ext in suspicious_ext and result["size"] < 10*1024*1024:  # moins de 10 Mo
            result["score"] = max(result["score"], 0.3)
            result["matches"].append(f"Extension suspecte: {ext}")

        # Détection si score > seuil
        threshold = self.config.get("scan_threshold", 0.5)
        if result["score"] >= threshold:
            result["threat_detected"] = True

        return result