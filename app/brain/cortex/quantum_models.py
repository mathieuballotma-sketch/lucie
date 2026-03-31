"""
Modèles de données pour le QuantumRouter — DS-P1-01.

Terminologie quantique (métaphorique) :
- Superposition : ensemble de chemins possibles avec probabilités
- PathWeight : un chemin + son poids (probabilité d'être le bon)
- Collapse : sélection du résultat final
- Decoherence : timeout ou erreur qui élimine un chemin
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class FusionStrategy(Enum):
    """Stratégie de fusion des résultats multi-agents."""
    FIRST_WINNER = "first_winner"      # Premier résultat avec confiance > seuil
    WEIGHTED_SUM = "weighted_sum"      # Somme pondérée des scores
    LLM_ARBITER = "llm_arbiter"        # LLM final pour choisir le meilleur
    CONSENSUS = "consensus"            # Majorité pondérée par confiance


class PathState(Enum):
    """État d'un chemin dans la superposition."""
    PENDING = "pending"          # En attente d'exécution
    RUNNING = "running"          # En cours
    COMPLETED = "completed"      # Terminé avec succès
    FAILED = "failed"            # Échec (erreur ou timeout)
    CANCELLED = "cancelled"      # Annulé (early termination)
    DECOHERENT = "decoherent"    # Éliminé par décoherence


@dataclass
class PathWeight:
    """
    Un chemin dans la superposition quantique.

    Le poids (weight) représente la probabilité initiale que ce chemin
    soit le bon. Il est calculé par le PathRouter (confiance) et ajusté
    par le NanoPredictor (historique utilisateur).

    weight ∈ [0, 1], normalisé tel que sum(weights) = 1.0
    """
    agent: str                    # Nom de l'agent
    weight: float                 # Probabilité initiale ∈ [0, 1]
    state: PathState = PathState.PENDING
    result: Optional[str] = None  # Résultat de l'agent
    confidence: float = 0.0       # Confiance du résultat ∈ [0, 1]
    latency_ms: float = 0.0      # Temps d'exécution
    error: Optional[str] = None   # Message d'erreur si échec

    @property
    def is_terminal(self) -> bool:
        """Le chemin est dans un état terminal (pas de changement possible)."""
        return self.state in (
            PathState.COMPLETED, PathState.FAILED,
            PathState.CANCELLED, PathState.DECOHERENT,
        )

    @property
    def effective_score(self) -> float:
        """Score effectif = poids initial × confiance résultat."""
        if self.state != PathState.COMPLETED:
            return 0.0
        return self.weight * self.confidence


@dataclass
class QuantumState:
    """
    État complet de la superposition.

    Contient tous les chemins avec leurs poids, l'état d'exécution,
    et les métadonnées pour le traçage.
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    query: str = ""
    paths: List[PathWeight] = field(default_factory=list)
    strategy: FusionStrategy = FusionStrategy.FIRST_WINNER
    created_at: float = field(default_factory=time.time)
    timeout_ms: float = 5000.0    # Timeout global en ms
    max_parallel: int = 3         # Max agents en parallèle

    @property
    def is_collapsed(self) -> bool:
        """La superposition est effondrée (tous les chemins terminaux)."""
        return all(p.is_terminal for p in self.paths)

    @property
    def active_paths(self) -> List[PathWeight]:
        """Chemins encore en cours."""
        return [p for p in self.paths if not p.is_terminal]

    @property
    def completed_paths(self) -> List[PathWeight]:
        """Chemins terminés avec succès."""
        return [p for p in self.paths if p.state == PathState.COMPLETED]

    def normalize_weights(self) -> None:
        """Normalise les poids pour que sum = 1.0."""
        total = sum(p.weight for p in self.paths)
        if total > 0:
            for p in self.paths:
                p.weight /= total


@dataclass
class CollapseResult:
    """
    Résultat final après effondrement de la superposition.

    Contient le résultat sélectionné, les métriques de tous les chemins,
    et les informations de traçage.
    """
    quantum_id: str               # ID de la superposition
    query: str                    # Requête originale
    selected_agent: str           # Agent gagnant
    result: str                   # Réponse finale
    confidence: float             # Confiance globale ∈ [0, 1]
    strategy_used: FusionStrategy # Stratégie de fusion utilisée
    total_latency_ms: float       # Latence totale
    paths_explored: int           # Nombre de chemins explorés
    paths_completed: int          # Nombre de chemins complétés
    paths_cancelled: int          # Nombre de chemins annulés
    all_paths: List[Dict[str, Any]] = field(default_factory=list)
    fusion_detail: str = ""       # Détail de la décision de fusion

    def to_audit_dict(self) -> Dict[str, Any]:
        """Sérialise pour l'AuditTrail."""
        return {
            "quantum_id": self.quantum_id,
            "query": self.query,
            "selected_agent": self.selected_agent,
            "confidence": self.confidence,
            "strategy": self.strategy_used.value,
            "latency_ms": self.total_latency_ms,
            "explored": self.paths_explored,
            "completed": self.paths_completed,
            "cancelled": self.paths_cancelled,
            "all_paths": self.all_paths,
            "fusion_detail": self.fusion_detail,
        }
