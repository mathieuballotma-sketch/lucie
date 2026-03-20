"""
Schémas de données pour le système de workflows visuels.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
import uuid


@dataclass
class Port:
    """Définit un port d'entrée ou de sortie d'un nœud."""

    id: str
    name: str
    data_type: str  # "string", "number", "boolean", "object", "array", "llm_response", "file_path", "any"
    direction: str  # "input" ou "output"
    required: bool = True
    default: Any = None


@dataclass
class NodeDefinition:
    """Définition d'un type de nœud (template réutilisable)."""

    node_type: str  # "agent.file", "control.condition", "llm.generate", etc.
    category: str  # "agent", "control", "llm", "data", "custom"
    label: str
    description: str
    inputs: list[Port] = field(default_factory=list)
    outputs: list[Port] = field(default_factory=list)
    config_schema: dict = field(default_factory=dict)
    icon: str = ""
    color: str = "#6366f1"


@dataclass
class WorkflowNode:
    """Instance d'un nœud dans un workflow."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    node_type: str = ""
    config: dict = field(default_factory=dict)
    position: dict = field(default_factory=lambda: {"x": 0, "y": 0})


@dataclass
class WorkflowEdge:
    """Connexion entre deux nœuds (source_port → target_port)."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_node: str = ""
    source_port: str = ""
    target_node: str = ""
    target_port: str = ""


@dataclass
class Workflow:
    """Un workflow complet : graphe de nœuds connectés par des edges."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    nodes: list[WorkflowNode] = field(default_factory=list)
    edges: list[WorkflowEdge] = field(default_factory=list)
    version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ExecutionResult:
    """Résultat d'exécution d'un nœud."""

    node_id: str
    status: str  # "success", "error", "skipped", "pending"
    outputs: dict = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: float = 0.0
