"""
NodeRegistry — Registre singleton des types de nœuds disponibles.

Gère l'enregistrement et la recherche de NodeDefinition.
Peut auto-découvrir les agents BaseAgent du projet.
"""

import importlib
import inspect
import os
import threading
from typing import Dict, List, Optional

from ..utils.logger import logger
from .schemas import NodeDefinition, Port


class NodeRegistry:
    """Registre centralisé des définitions de nœuds (singleton thread-safe)."""

    _instance: Optional["NodeRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "NodeRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._definitions: Dict[str, NodeDefinition] = {}
                cls._instance._initialized = True
            return cls._instance

    def register(self, node_def: NodeDefinition) -> None:
        """Enregistre une définition de nœud."""
        self._definitions[node_def.id] = node_def
        logger.debug(f"NodeRegistry: enregistré '{node_def.id}' ({node_def.category})")

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

    def auto_discover_agents(self, agents_dir: Optional[str] = None) -> int:
        """
        Découvre les agents BaseAgent dans app/agents/ et crée des NodeDefinition.

        Retourne le nombre d'agents découverts.
        """
        if agents_dir is None:
            agents_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "agents"
            )

        if not os.path.isdir(agents_dir):
            logger.warning(f"NodeRegistry: répertoire agents introuvable : {agents_dir}")
            return 0

        count = 0
        for filename in sorted(os.listdir(agents_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue

            module_name = filename[:-3]
            try:
                mod = importlib.import_module(f"app.agents.{module_name}")
            except Exception as exc:
                logger.debug(f"NodeRegistry: impossible d'importer {module_name}: {exc}")
                continue

            for attr_name in dir(mod):
                obj = getattr(mod, attr_name, None)
                if obj is None or not inspect.isclass(obj):
                    continue
                if attr_name == "BaseAgent":
                    continue

                # Vérifier que c'est une sous-classe de BaseAgent
                try:
                    from ..agents.base_agent import BaseAgent
                    if not issubclass(obj, BaseAgent):
                        continue
                except (ImportError, TypeError):
                    continue

                # Extraire les tools pour créer les ports
                inputs = [Port(name="input", type="any", description="Entrée principale")]
                outputs = [Port(name="output", type="any", description="Sortie principale")]

                node_def = NodeDefinition(
                    id=f"agent.{module_name}",
                    name=attr_name,
                    category="agent",
                    description=f"Agent {attr_name} (auto-découvert)",
                    inputs=inputs,
                    outputs=outputs,
                )
                self.register(node_def)
                count += 1

        logger.info(f"NodeRegistry: {count} agents découverts")
        return count

    @classmethod
    def reset_singleton(cls) -> None:
        """Réinitialise le singleton (tests uniquement)."""
        with cls._lock:
            cls._instance = None
