"""
Analyseur de menaces - Classe et analyse les menaces détectées.
Version simplifiée pour éviter les erreurs d'attribut.
"""

from typing import Dict, Any
from app.utils.logger import logger


class ThreatAnalyzer:
    """
    Analyse les menaces pour déterminer leur type, sévérité, et solution possible.
    """

    def __init__(self, config: Dict[str, Any], memory_service: Any = None) -> None:
        self.config = config
        self.memory = memory_service
        print(f"Analyzer initialisé avec memory = {self.memory}")  # Pour débogage

    async def analyze(self, filepath: str, scan_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse un résultat de scan pour produire une fiche de menace.
        """
        threat_info = {
            "name": "Inconnu",
            "type": "unknown",
            "severity": scan_result.get("score", 0.0),
            "signature": scan_result.get("hash"),
            "matches": scan_result.get("matches", []),
            "solution": None,
        }

        # Tenter de déterminer le type à partir des correspondances
        matches = threat_info["matches"]
        if any("ransomware" in m.lower() for m in matches):
            threat_info["type"] = "ransomware"
            threat_info["name"] = "Ransomware suspect"
        elif any("trojan" in m.lower() for m in matches):
            threat_info["type"] = "trojan"
            threat_info["name"] = "Trojan"
        elif any("worm" in m.lower() for m in matches):
            threat_info["type"] = "worm"
            threat_info["name"] = "Ver"
        elif any("keylogger" in m.lower() for m in matches):
            threat_info["type"] = "keylogger"
            threat_info["name"] = "Keylogger"

        # Chercher une solution dans la mémoire épisodique
        if self.memory and threat_info["signature"]:
            try:
                print(f"Analyzer: appel de remember avec signature {threat_info['signature']}")
                # Correction : ajout de await
                results = await self.memory.remember(threat_info["signature"], n_results=1, min_similarity=0.9)
                print(f"Analyzer: résultats = {results}")
                if results:
                    metadata = results[0].get("metadata", {})
                    if metadata.get("type") == "threat_solution":
                        threat_info["solution"] = metadata.get("solution")
                        threat_info["name"] = metadata.get("threat_name", threat_info["name"])
            except Exception as e:
                print(f"Analyzer: erreur lors de remember: {e}")
                logger.error(f"Erreur mémoire dans analyzer: {e}")

        return threat_info
