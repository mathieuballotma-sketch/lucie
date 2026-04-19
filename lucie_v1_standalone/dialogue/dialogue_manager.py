"""
DialogueManager — Squelette de gestion des états conversationnels.

Non branché dans le pipeline principal — structure posée pour validation
avant intégration. Les méthodes stub retournent des valeurs neutres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DialogueState:
    """État courant d'une conversation."""
    domain: Optional[str] = None
    info_collected: Dict[str, Any] = field(default_factory=dict)
    info_missing: List[str] = field(default_factory=list)
    turn_count: int = 0


class DialogueManager:
    """
    Gère l'état conversationnel multi-tours pour les questions juridiques imprécises.

    Usage prévu (post-validation) :
        manager = DialogueManager("licenciement_economique")
        if manager.needs_clarification(query):
            return manager.next_question()
        # sinon, passer au pipeline principal
    """

    def __init__(self, domain: str) -> None:
        self.state = DialogueState(domain=domain)

    def needs_clarification(self, query: str) -> bool:
        """
        Retourne True si la requête manque d'informations pour une réponse précise.

        Stub — implémentation complète après validation Mathieu + corpus empirique.
        """
        return bool(self.state.info_missing)

    def next_question(self) -> Optional[str]:
        """
        Retourne la prochaine question de clarification, ou None si tout est collecté.

        Stub — retourne la première info manquante formatée en question.
        """
        if not self.state.info_missing:
            return None
        missing = self.state.info_missing[0]
        return f"Pourriez-vous me préciser : {missing} ?"

    def mark_answered(self, param: str, value: Any) -> None:
        """Enregistre une réponse et retire le paramètre de la liste manquante."""
        self.state.info_collected[param] = value
        if param in self.state.info_missing:
            self.state.info_missing.remove(param)
        self.state.turn_count += 1

    def reset(self) -> None:
        """Réinitialise l'état (nouvelle conversation)."""
        domain = self.state.domain
        self.state = DialogueState(domain=domain)

    @property
    def is_complete(self) -> bool:
        """Toutes les infos requises ont été collectées."""
        return not self.state.info_missing
