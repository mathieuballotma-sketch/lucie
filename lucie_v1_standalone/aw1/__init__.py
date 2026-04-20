"""AW-1 — Auto-wiring primitives (isolated from core/ Bloc 1)."""

from .node_registry import NodeRegistry
from .plasticity import Plasticity
from .quantum_models import CollapseResult, FusionStrategy, PathState, PathWeight, QuantumState
from .schemas import ExecutionResult, NodeDefinition, Port, Workflow, WorkflowEdge, WorkflowNode
from .waterflow import WaterDrop, WaterFlow, WaterGrain

__all__ = [
    "NodeRegistry",
    "Plasticity",
    "CollapseResult",
    "FusionStrategy",
    "PathState",
    "PathWeight",
    "QuantumState",
    "ExecutionResult",
    "NodeDefinition",
    "Port",
    "Workflow",
    "WorkflowEdge",
    "WorkflowNode",
    "WaterDrop",
    "WaterFlow",
    "WaterGrain",
]
