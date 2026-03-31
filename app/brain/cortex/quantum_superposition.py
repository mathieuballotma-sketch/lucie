"""
SuperpositionGenerator — DS-P1-01

Détermine quels agents explorer en parallèle.

Critères de superposition :
1. Le PathRouter donne une confiance < AMBIGUITY_THRESHOLD (0.75)
2. La requête contient des marqueurs multi-tâches ("et", "puis", "aussi")
3. Le NanoPredictor suggère un agent différent du PathRouter

Le nombre de chemins est borné par MAX_PATHS (4 par défaut)
pour respecter les contraintes M3 16GB.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .router import PathRouter, RouteResult
from .quantum_models import (
    PathWeight, QuantumState, FusionStrategy, PathState,
)
from ...utils.logger import logger

if TYPE_CHECKING:
    from .predictor import NanoPredictor


# ── Seuils ──────────────────────────────────────────────────────
AMBIGUITY_THRESHOLD = 0.75   # En-dessous → superposition
MULTI_TASK_THRESHOLD = 0.60  # En-dessous → probablement multi-tâche
MAX_PATHS = 4                # Max chemins simultanés (M3 16GB)
MIN_WEIGHT = 0.10            # Poids minimum pour être inclus


# ── Détection multi-tâche ───────────────────────────────────────
_MULTI_TASK_PATTERNS = [
    r"\bet\b",              # "cherche X et crée Y"
    r"\bpuis\b",            # "fais X puis Y"
    r"\baussi\b",           # "regarde aussi"
    r"\bensuite\b",         # "ensuite fais Y"
    r"\ben plus\b",         # "en plus"
    r"\bégalement\b",       # "également"
    r"\bainsi que\b",       # "ainsi que"
    r",\s*(?:et\s)?",       # Virgule + optionnellement "et"
]

# ── Mapping agent → domaines compatibles ────────────────────────
# Utilisé pour générer des chemins alternatifs pertinents
_AGENT_AFFINITIES: Dict[str, List[str]] = {
    "file_agent": ["FileAgent", "DocumentAgent"],
    "computer_control": ["ComputerControlAgent", "WorkspaceAgent"],
    "reminder": ["AppleEcosystemAgent", "CalendarAgent"],
    "visual_research": ["KnowledgeAgent", "WebSearch"],
    "knowledge_agent": ["KnowledgeAgent", "DocumentAgent"],
    "creator": ["CreatorAgent", "DocumentAgent"],
    "planner": ["PlannerAgent"],
    "workspace_agent": ["WorkspaceAgent", "ComputerControlAgent"],
    "accounting": ["AccountingAgent", "FileAgent"],
}

# Mapping label PathRouter → nom agent réel dans le registre
_LABEL_TO_AGENT: Dict[str, str] = {
    "file_agent": "FileAgent",
    "computer_control": "ComputerControlAgent",
    "reminder": "AppleEcosystemAgent",
    "visual_research": "KnowledgeAgent",
    "knowledge_agent": "KnowledgeAgent",
    "creator": "CreatorAgent",
    "planner": "PlannerAgent",
    "workspace_agent": "WorkspaceAgent",
    "accounting": "AccountingAgent",
    "calendar_query": "CalendarAgent",
    "reminder_query": "AppleEcosystemAgent",
    "file_query": "FileAgent",
    "code_query": "CodeDebugAgent",
    "document_query": "DocumentAgent",
    "mac_query": "ComputerControlAgent",
}


class SuperpositionGenerator:
    """
    Génère l'état de superposition à partir d'une requête.

    Décision :
    - Si confiance PathRouter >= AMBIGUITY_THRESHOLD et pas multi-tâche
      → PAS de superposition (routage classique)
    - Sinon → génère N chemins pondérés

    Poids initiaux :
    - Agent principal (PathRouter) : confiance du router
    - Agents affinitaires : confiance × 0.5
    - Agent NanoPredictor : confiance × 0.7 (si différent)
    """

    def __init__(self, router: PathRouter,
                 predictor: Optional[NanoPredictor] = None) -> None:
        self._router = router
        self._predictor = predictor

    def should_superpose(self, route_result: RouteResult,
                         query: str) -> bool:
        """
        Détermine si la requête nécessite une superposition.

        Retourne True si :
        1. Confiance < AMBIGUITY_THRESHOLD, OU
        2. Requête contient des marqueurs multi-tâches, OU
        3. NanoPredictor prédit un agent différent avec bonne confiance
        """
        # 1. Confiance faible
        if route_result.confidence < AMBIGUITY_THRESHOLD:
            return True

        # 2. Multi-tâche détecté
        if self._is_multi_task(query):
            return True

        # 3. Conflit avec NanoPredictor
        if self._predictor:
            try:
                predicted = self._predictor.predict(query)
                if (predicted and
                        predicted.get("agent") != route_result.agent and
                        predicted.get("confidence", 0) > 0.5):
                    return True
            except Exception:
                pass

        return False

    def generate(self, query: str,
                 route_result: RouteResult,
                 strategy: FusionStrategy = FusionStrategy.FIRST_WINNER,
                 timeout_ms: float = 5000.0,
                 ) -> QuantumState:
        """
        Génère l'état de superposition pour une requête.

        Algorithme :
        1. Agent principal → poids = confiance PathRouter
        2. Pour chaque agent affinitaire → poids = confiance × 0.5
        3. Si NanoPredictor différent → poids = confiance_predictor × 0.7
        4. Filtrer poids < MIN_WEIGHT
        5. Tronquer à MAX_PATHS
        6. Normaliser les poids
        """
        paths: List[PathWeight] = []

        # 1. Agent principal
        main_agent = _LABEL_TO_AGENT.get(route_result.agent, route_result.agent)
        main_weight = max(route_result.confidence, 0.3)  # Minimum 0.3
        paths.append(PathWeight(agent=main_agent, weight=main_weight))

        seen_agents = {main_agent}

        # 2. Agents affinitaires
        affinities = _AGENT_AFFINITIES.get(route_result.agent, [])
        for aff_agent in affinities:
            if aff_agent not in seen_agents:
                aff_weight = route_result.confidence * 0.5
                if aff_weight >= MIN_WEIGHT:
                    paths.append(PathWeight(agent=aff_agent, weight=aff_weight))
                    seen_agents.add(aff_agent)

        # 3. NanoPredictor
        if self._predictor:
            try:
                predicted = self._predictor.predict(query)
                if predicted:
                    pred_agent = predicted.get("agent", "")
                    pred_agent = _LABEL_TO_AGENT.get(pred_agent, pred_agent)
                    pred_conf = predicted.get("confidence", 0)
                    if pred_agent not in seen_agents and pred_conf * 0.7 >= MIN_WEIGHT:
                        paths.append(PathWeight(
                            agent=pred_agent,
                            weight=pred_conf * 0.7,
                        ))
                        seen_agents.add(pred_agent)
            except Exception:
                pass

        # 4. Multi-tâche : extraire les sous-requêtes
        if self._is_multi_task(query):
            sub_queries = self._split_multi_task(query)
            for sub_q in sub_queries:
                sub_result = self._router.route(sub_q)
                sub_agent = _LABEL_TO_AGENT.get(sub_result.agent, sub_result.agent)
                if sub_agent not in seen_agents:
                    paths.append(PathWeight(
                        agent=sub_agent,
                        weight=sub_result.confidence * 0.6,
                    ))
                    seen_agents.add(sub_agent)

        # 5. Tronquer à MAX_PATHS (garder les plus lourds)
        paths.sort(key=lambda p: p.weight, reverse=True)
        paths = paths[:MAX_PATHS]

        # 6. Créer l'état et normaliser
        state = QuantumState(
            query=query,
            paths=paths,
            strategy=strategy,
            timeout_ms=timeout_ms,
            max_parallel=min(len(paths), MAX_PATHS),
        )
        state.normalize_weights()

        logger.debug(
            f"Superposition generee : {len(paths)} chemins — "
            f"{', '.join(f'{p.agent}({p.weight:.2f})' for p in paths)}"
        )

        return state

    def _is_multi_task(self, query: str) -> bool:
        """Détecte si la requête contient des marqueurs multi-tâches."""
        q = query.lower()
        matches = sum(1 for p in _MULTI_TASK_PATTERNS if re.search(p, q))
        return matches >= 1

    def _split_multi_task(self, query: str) -> List[str]:
        """
        Découpe une requête multi-tâche en sous-requêtes.

        Heuristique simple : split sur "et", "puis", virgules.
        Retourne au maximum 3 sous-requêtes.
        """
        # Split sur les connecteurs
        parts = re.split(
            r'\bet\b|\bpuis\b|\bensuite\b|\bainsi que\b|,',
            query,
            flags=re.IGNORECASE,
        )
        # Nettoyer et filtrer
        parts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 5]
        return parts[:3]
