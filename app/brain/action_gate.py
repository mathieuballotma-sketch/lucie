"""
ActionGate — Contrôleur de risque pour les actions des agents.

Classifie chaque action par niveau de risque (1–4) et décide de l'approuver
ou de la bloquer.  Par défaut le seuil d'auto-approbation est HIGH : LOW/MODERATE/HIGH passent
automatiquement, CRITICAL (irréversible / impact externe) est bloqué et exige
une validation utilisateur.  Abaisser ``auto_approve_threshold`` à MODERATE
pour un contrôle encore plus strict.

Niveaux de risque :
    1 — LOW      : lecture seule, aucun effet de bord
    2 — MODERATE : modifie l'état, réversible
    3 — HIGH     : modification critique, difficile à annuler
    4 — CRITICAL : irréversible ou fort impact externe
"""

from enum import IntEnum
from typing import Any, Dict, Optional, Tuple

from app.utils.logger import logger


class RiskLevel(IntEnum):
    """Niveaux de risque d'une action agent."""

    LOW = 1
    MODERATE = 2
    HIGH = 3
    CRITICAL = 4


DEFAULT_RISK_REGISTRY: Dict[str, int] = {
    # ── Niveau 1 — lecture / observation ──────────────────────────────────
    "list_files":       RiskLevel.LOW,
    "get_screenshot":   RiskLevel.LOW,
    "move_mouse":       RiskLevel.LOW,
    "open_application": RiskLevel.LOW,
    "list_agents":      RiskLevel.LOW,
    # ── Niveau 2 — modification réversible ────────────────────────────────
    "write_file":       RiskLevel.MODERATE,
    "copy_file":        RiskLevel.MODERATE,
    "type_text":        RiskLevel.MODERATE,
    "press_key":        RiskLevel.MODERATE,
    "click":            RiskLevel.MODERATE,
    "safari_open_url":  RiskLevel.MODERATE,
    "arrange_windows":  RiskLevel.MODERATE,
    # ── Niveau 3 — modification à fort impact ─────────────────────────────
    "delete_file":      RiskLevel.HIGH,
    "move_file":        RiskLevel.HIGH,
    "rename_file":      RiskLevel.HIGH,
    "create_agent":     RiskLevel.HIGH,
    "delete_agent":     RiskLevel.HIGH,
    # ── Niveau 4 — irréversible / impact externe ──────────────────────────
    "mail_compose":     RiskLevel.CRITICAL,
    "execute_command":  RiskLevel.CRITICAL,
}


class ActionGate:
    """
    Évalue le risque d'une action agent et décide de l'approuver ou de la bloquer.

    Par défaut le seuil est HIGH : les actions LOW/MODERATE/HIGH sont auto-approuvées,
    les actions CRITICAL (mail_compose, execute_command) exigent une confirmation.
    Abaisser ``auto_approve_threshold`` à MODERATE pour un contrôle plus strict.
    """

    def __init__(
        self,
        risk_registry: Optional[Dict[str, int]] = None,
        auto_approve_threshold: int = RiskLevel.HIGH,
    ) -> None:
        self.risk_registry: Dict[str, int] = (
            risk_registry if risk_registry is not None else dict(DEFAULT_RISK_REGISTRY)
        )
        self.auto_approve_threshold = auto_approve_threshold

    def get_risk_level(self, action_type: str) -> int:
        """Retourne le niveau de risque d'un type d'action (défaut : MODERATE)."""
        return self.risk_registry.get(action_type, RiskLevel.MODERATE)

    def evaluate(self, action_data: Dict[str, Any]) -> Tuple[bool, int]:
        """
        Évalue si une action peut être exécutée.

        Args:
            action_data: dict avec au minimum ``action_type``.  Champs optionnels :
                         ``preview`` (description lisible), ``reversible`` (bool),
                         ``agent`` (nom de l'agent émetteur).

        Returns:
            Tuple (approved, risk_level).  ``approved`` est True si l'action est
            autorisée selon le seuil d'auto-approbation.
        """
        action_type: str = action_data.get("action_type", "unknown")
        risk_level: int = self.get_risk_level(action_type)
        approved: bool = risk_level <= self.auto_approve_threshold

        preview = action_data.get("preview", "")
        agent = action_data.get("agent", "?")

        if not approved:
            logger.warning(
                f"🚫 ActionGate BLOQUÉ — agent={agent}, "
                f"action={action_type}, risk={risk_level}, preview={preview!r}"
            )
        elif risk_level >= RiskLevel.HIGH:
            logger.warning(
                f"⚠️ ActionGate RISQUE ÉLEVÉ — agent={agent}, "
                f"action={action_type}, risk={risk_level}, preview={preview!r}"
            )
        elif risk_level == RiskLevel.MODERATE:
            logger.info(
                f"🔶 ActionGate approuvé — agent={agent}, "
                f"action={action_type}, preview={preview!r}"
            )
        else:
            logger.debug(
                f"✅ ActionGate approuvé — agent={agent}, action={action_type}"
            )

        return approved, risk_level
