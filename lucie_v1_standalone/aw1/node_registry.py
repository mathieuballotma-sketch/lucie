"""
NodeRegistry — Registre singleton des types de nœuds disponibles.

Salvagé depuis archive/pre-cleanup:app/workflows/node_registry.py.
auto_discover_agents() retiré — l'architecture n'est pas stabilisée
et importlib.util.spec_from_file_location sur dossiers user-writable
représente un risque RCE (cf. rapport Protecteur-IP 16 avril 2026).
Seul register_manually() est exposé pour l'enregistrement explicite.
"""

import logging
import threading
from typing import Dict, List, Optional

from .schemas import NodeDefinition, Port

logger = logging.getLogger(__name__)


class NodeRegistry:
    """Registre centralisé des définitions de nœuds (singleton thread-safe)."""

    _instance: Optional["NodeRegistry"] = None
    _lock = threading.Lock()
    _definitions: Dict[str, NodeDefinition]
    _initialized: bool

    def __new__(cls) -> "NodeRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._definitions = {}
                cls._instance._initialized = True
            return cls._instance

    def register(self, node_def: NodeDefinition) -> None:
        """Enregistre une définition de nœud."""
        self._definitions[node_def.id] = node_def
        logger.debug("NodeRegistry: enregistré '%s' (%s)", node_def.id, node_def.category)

    def register_manually(
        self,
        name: str,
        category: str = "general",
        description: str = "",
    ) -> NodeDefinition:
        """
        Crée et enregistre une NodeDefinition minimale.

        API simplifiée pour l'enregistrement explicite — alternative
        à auto_discover_agents() qui est désactivé (sécurité + architecture).
        Retourne la définition créée.
        """
        node_def = NodeDefinition(
            id=name,
            name=name,
            category=category,
            description=description,
            inputs=[Port(name="input", type="any")],
            outputs=[Port(name="output", type="any")],
        )
        self.register(node_def)
        return node_def

    def unregister(self, definition_id: str) -> bool:
        """Retire une définition. Retourne True si elle existait."""
        removed = self._definitions.pop(definition_id, None)
        return removed is not None

    def get(self, definition_id: str) -> Optional[NodeDefinition]:
        """Retourne la définition d'un nœud par son id, ou None."""
        return self._definitions.get(definition_id)

    def list_all(self) -> List[NodeDefinition]:
        """Liste toutes les définitions enregistrées."""
        return list(self._definitions.values())

    def list_by_category(self, category: str) -> List[NodeDefinition]:
        """Liste les définitions d'une catégorie donnée."""
        return [d for d in self._definitions.values() if d.category == category]

    def categories(self) -> List[str]:
        """Retourne la liste des catégories uniques."""
        return sorted({d.category for d in self._definitions.values()})

    def clear(self) -> None:
        """Vide le registre (utile pour les tests)."""
        self._definitions.clear()

    @classmethod
    def reset_singleton(cls) -> None:
        """Réinitialise le singleton (tests uniquement)."""
        with cls._lock:
            cls._instance = None
