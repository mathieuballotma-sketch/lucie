"""
Schémas Pydantic pour le registre de nœuds et l'éditeur de flux visuel.

Salvagé depuis archive/pre-cleanup:app/workflows/schemas.py.
Migré de pydantic.v1 vers pydantic v2.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Port(BaseModel):
    """Port d'entrée ou de sortie d'un nœud."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: str = "any"
    description: str = ""
    required: bool = True
    default: Optional[Any] = None


class NodeDefinition(BaseModel):
    """Définition d'un type de nœud disponible dans le registre."""

    id: str
    name: str
    category: str = "general"
    description: str = ""
    inputs: List[Port] = Field(default_factory=list)
    outputs: List[Port] = Field(default_factory=list)
    config_schema: Dict[str, Any] = Field(default_factory=dict)


class WorkflowNode(BaseModel):
    """Instance d'un nœud dans un workflow."""

    id: str = Field(default_factory=_uuid)
    definition_id: str
    position_x: float = 0.0
    position_y: float = 0.0
    config: Dict[str, Any] = Field(default_factory=dict)
    label: str = ""


class WorkflowEdge(BaseModel):
    """Connexion entre deux ports de nœuds."""

    id: str = Field(default_factory=_uuid)
    source_node_id: str
    source_port: str
    target_node_id: str
    target_port: str


class Workflow(BaseModel):
    """Workflow complet avec nœuds et arêtes."""

    id: str = Field(default_factory=_uuid)
    name: str = "Sans titre"
    description: str = ""
    nodes: List[WorkflowNode] = Field(default_factory=list)
    edges: List[WorkflowEdge] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


class ExecutionResult(BaseModel):
    """Résultat de l'exécution d'un nœud."""

    node_id: str
    status: str = "pending"
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
