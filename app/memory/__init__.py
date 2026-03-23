"""
Module de mémoire pour Agent Lucide.
Inspiré du cerveau humain : mémoire épisodique (long terme) et mémoire de travail (court terme).
"""

from .consolidation import ConsolidationEngine
from .context_graph import ContextEdge, ContextGraph, ContextNode
from .contextual_memory import ContextualMemory
from .episodic_memory import EpisodicMemory
from .memory_service import MemoryService
from .working_memory import WorkingMemory

__all__ = [
    "EpisodicMemory",
    "WorkingMemory",
    "MemoryService",
    "ConsolidationEngine",
    "ContextGraph",
    "ContextNode",
    "ContextEdge",
    "ContextualMemory",
]
