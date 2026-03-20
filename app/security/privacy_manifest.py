"""PrivacyManifest — preuve de conformité RGPD pour Lucie."""

from typing import List


class PrivacyManifest:
    """Audit de confidentialité — argument de vente RGPD."""

    def check_outbound_connections(self) -> bool:
        """Vérifie qu'aucune connexion sortante non autorisée n'existe."""
        raise NotImplementedError

    def generate_report(self) -> str:
        """Génère un rapport de conformité RGPD."""
        raise NotImplementedError

    def list_local_data(self) -> List[str]:
        """Liste toutes les données stockées localement."""
        raise NotImplementedError
