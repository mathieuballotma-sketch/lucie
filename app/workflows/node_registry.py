"""
NodeRegistry — Registre des types de nœuds disponibles pour l'éditeur visuel.

Permet d'enregistrer des NodeDefinition, de les retrouver par type,
et de découvrir automatiquement les agents BaseAgent existants.
"""
import importlib
import inspect
from pathlib import Path
from typing import Dict, List, Optional

from .schemas import NodeDefinition, Port
from ..utils.logger import logger


class NodeRegistry:
    """
    Registre des types de nœuds disponibles.

    Usage :
        reg = NodeRegistry()
        reg.auto_discover_agents()
        defn = reg.get("agent.file_agent")
    """

    def __init__(self) -> None:
        self._registry: Dict[str, NodeDefinition] = {}
        self._register_builtins()

    # ── API publique ──────────────────────────────────────────────────────────

    def register(self, node_def: NodeDefinition) -> None:
        """Enregistre (ou écrase) un type de nœud."""
        self._registry[node_def.node_type] = node_def
        logger.debug(f"NodeRegistry: enregistré '{node_def.node_type}'")

    def get(self, node_type: str) -> Optional[NodeDefinition]:
        """Retourne la définition d'un type de nœud, ou None si inconnu."""
        return self._registry.get(node_type)

    def list_all(self) -> Dict[str, List[NodeDefinition]]:
        """Retourne tous les nœuds groupés par catégorie."""
        result: Dict[str, List[NodeDefinition]] = {}
        for node_def in self._registry.values():
            cat = node_def.category
            if cat not in result:
                result[cat] = []
            result[cat].append(node_def)
        return result

    def auto_discover_agents(self) -> int:
        """
        Scanne app/agents/ et crée un NodeDefinition pour chaque classe BaseAgent.

        Retourne le nombre d'agents découverts.
        Les agents dont l'import échoue sont silencieusement ignorés.
        """
        agents_dir = Path(__file__).parent.parent / "agents"
        if not agents_dir.exists():
            logger.warning(f"NodeRegistry: dossier agents introuvable: {agents_dir}")
            return 0

        try:
            from ..agents.base_agent import BaseAgent
        except ImportError as e:
            logger.warning(f"NodeRegistry: impossible d'importer BaseAgent: {e}")
            return 0

        _skip = {"base_agent", "speed_config", "accessibility_layer", "action_broker"}
        discovered = 0

        for py_file in sorted(agents_dir.glob("*.py")):
            if py_file.stem.startswith("_") or py_file.stem in _skip:
                continue

            module_path = f"app.agents.{py_file.stem}"
            try:
                module = importlib.import_module(module_path)
            except Exception as e:
                logger.debug(f"NodeRegistry: skip {py_file.stem} ({e})")
                continue

            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if obj is BaseAgent:
                    continue
                if not issubclass(obj, BaseAgent):
                    continue
                # Un NodeDefinition par fichier
                agent_type = f"agent.{py_file.stem}"
                label = _name.replace("Agent", " Agent").strip()
                node_def = NodeDefinition(
                    node_type=agent_type,
                    category="agent",
                    label=label,
                    description=f"Agent {_name} — {py_file.stem}",
                    inputs=[
                        Port(id="query", name="Requête", data_type="string", direction="input"),
                    ],
                    outputs=[
                        Port(id="response", name="Réponse", data_type="string", direction="output"),
                    ],
                    color="#8b5cf6",
                )
                self.register(node_def)
                discovered += 1
                break  # Un seul NodeDef par fichier

        logger.info(f"NodeRegistry: {discovered} agents auto-découverts")
        return discovered

    # ── Nœuds built-in ───────────────────────────────────────────────────────

    def _register_builtins(self) -> None:
        """Enregistre les nœuds built-in (control, llm, data)."""
        builtins: List[NodeDefinition] = [
            # ── Control ──────────────────────────────────────────────────────
            NodeDefinition(
                node_type="control.start",
                category="control",
                label="Démarrage",
                description="Point d'entrée du workflow",
                inputs=[],
                outputs=[
                    Port(id="trigger", name="Démarrage", data_type="any",
                         direction="output", required=False),
                ],
                color="#10b981",
            ),
            NodeDefinition(
                node_type="control.end",
                category="control",
                label="Fin",
                description="Point de sortie du workflow",
                inputs=[
                    Port(id="result", name="Résultat", data_type="any",
                         direction="input", required=False),
                ],
                outputs=[],
                color="#ef4444",
            ),
            NodeDefinition(
                node_type="control.condition",
                category="control",
                label="Condition",
                description="Branchement conditionnel (if/else)",
                inputs=[
                    Port(id="value", name="Valeur", data_type="any", direction="input"),
                    Port(id="condition", name="Condition", data_type="string",
                         direction="input", required=False),
                ],
                outputs=[
                    Port(id="true", name="Vrai", data_type="any", direction="output"),
                    Port(id="false", name="Faux", data_type="any", direction="output"),
                    Port(id="branch", name="Branche", data_type="string", direction="output"),
                ],
                config_schema={
                    "expression": {
                        "type": "string",
                        "description": "Expression de comparaison (ex: value > 10)",
                    }
                },
                color="#f59e0b",
            ),
            NodeDefinition(
                node_type="control.for_each",
                category="control",
                label="Pour chaque",
                description="Itère sur un tableau",
                inputs=[
                    Port(id="items", name="Éléments", data_type="array", direction="input"),
                ],
                outputs=[
                    Port(id="item", name="Élément courant", data_type="any", direction="output"),
                    Port(id="index", name="Index", data_type="number", direction="output"),
                    Port(id="items", name="Tous les éléments", data_type="array", direction="output"),
                    Port(id="count", name="Nombre", data_type="number", direction="output"),
                ],
                color="#8b5cf6",
            ),
            NodeDefinition(
                node_type="control.wait",
                category="control",
                label="Attente",
                description="Pause d'exécution (secondes)",
                inputs=[
                    Port(id="trigger", name="Déclencheur", data_type="any",
                         direction="input", required=False),
                ],
                outputs=[
                    Port(id="done", name="Terminé", data_type="any", direction="output"),
                ],
                config_schema={"seconds": {"type": "number", "default": 1}},
                color="#64748b",
            ),
            # ── LLM ──────────────────────────────────────────────────────────
            NodeDefinition(
                node_type="llm.generate",
                category="llm",
                label="Génération LLM",
                description="Génère du texte avec un modèle LLM local",
                inputs=[
                    Port(id="prompt", name="Prompt", data_type="string", direction="input"),
                    Port(id="system", name="Système", data_type="string",
                         direction="input", required=False),
                ],
                outputs=[
                    Port(id="response", name="Réponse brute", data_type="llm_response",
                         direction="output"),
                    Port(id="text", name="Texte", data_type="string", direction="output"),
                ],
                config_schema={
                    "model": {"type": "string", "default": "balanced"},
                    "temperature": {"type": "number", "default": 0.7},
                    "max_tokens": {"type": "number", "default": 512},
                },
                color="#6366f1",
            ),
            # ── Data ─────────────────────────────────────────────────────────
            NodeDefinition(
                node_type="data.read_file",
                category="data",
                label="Lire fichier",
                description="Lit le contenu d'un fichier texte",
                inputs=[
                    Port(id="path", name="Chemin", data_type="file_path", direction="input"),
                ],
                outputs=[
                    Port(id="content", name="Contenu", data_type="string", direction="output"),
                    Port(id="path", name="Chemin", data_type="file_path", direction="output"),
                ],
                config_schema={"path": {"type": "string", "description": "Chemin par défaut"}},
                color="#0ea5e9",
            ),
            NodeDefinition(
                node_type="data.write_file",
                category="data",
                label="Écrire fichier",
                description="Écrit du contenu dans un fichier",
                inputs=[
                    Port(id="path", name="Chemin", data_type="file_path", direction="input"),
                    Port(id="content", name="Contenu", data_type="string", direction="input"),
                ],
                outputs=[
                    Port(id="path", name="Chemin écrit", data_type="file_path",
                         direction="output"),
                ],
                color="#0ea5e9",
            ),
            NodeDefinition(
                node_type="data.variable",
                category="data",
                label="Variable",
                description="Stocke et transmet une valeur",
                inputs=[
                    Port(id="value", name="Valeur", data_type="any",
                         direction="input", required=False),
                ],
                outputs=[
                    Port(id="value", name="Valeur", data_type="any", direction="output"),
                ],
                config_schema={"value": {"type": "any", "description": "Valeur par défaut"}},
                color="#0ea5e9",
            ),
        ]

        for node_def in builtins:
            self.register(node_def)
