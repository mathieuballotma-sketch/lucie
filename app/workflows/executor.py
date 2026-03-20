"""
WorkflowExecutor — Exécute un workflow en respectant l'ordre topologique.

Fonctionnalités :
  - Validation DAG (détection de cycles)
  - Vérification de compatibilité des types de ports
  - Exécution parallèle des nœuds indépendants via asyncio.gather
  - Publication d'événements sur l'EventBus
"""

import asyncio
import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set

from ..utils.logger import logger
from .node_registry import NodeRegistry
from .schemas import ExecutionResult, Workflow, WorkflowNode


class WorkflowExecutor:
    """Exécute un workflow DAG avec parallélisme maximal."""

    def __init__(
        self,
        registry: Optional[NodeRegistry] = None,
        event_bus: Optional[Any] = None,
        token: Optional[str] = None,
    ) -> None:
        self.registry = registry or NodeRegistry()
        self.event_bus = event_bus
        self.token: Optional[str] = token

    def validate(self, workflow: Workflow) -> List[str]:
        """
        Valide un workflow et retourne la liste des erreurs (vide = OK).

        Vérifie :
          1. Tous les nœuds référencent une définition existante
          2. Toutes les arêtes référencent des nœuds existants
          3. Les ports source/target existent sur les nœuds
          4. Compatibilité des types de ports
          5. Le graphe est un DAG (pas de cycles)
        """
        errors: List[str] = []
        node_ids: Set[str] = {n.id for n in workflow.nodes}

        # 1 — Définitions existantes
        for node in workflow.nodes:
            node_def = self.registry.get(node.definition_id)
            if node_def is None:
                errors.append(
                    f"Nœud '{node.id}': définition '{node.definition_id}' introuvable"
                )

        # 2 — Arêtes référencent des nœuds valides
        for edge in workflow.edges:
            if edge.source_node_id not in node_ids:
                errors.append(
                    f"Arête '{edge.id}': nœud source '{edge.source_node_id}' introuvable"
                )
            if edge.target_node_id not in node_ids:
                errors.append(
                    f"Arête '{edge.id}': nœud cible '{edge.target_node_id}' introuvable"
                )

        # 3 & 4 — Ports et compatibilité types
        for edge in workflow.edges:
            src_node = self._find_node(workflow, edge.source_node_id)
            tgt_node = self._find_node(workflow, edge.target_node_id)
            if src_node is None or tgt_node is None:
                continue

            src_def = self.registry.get(src_node.definition_id)
            tgt_def = self.registry.get(tgt_node.definition_id)
            if src_def is None or tgt_def is None:
                continue

            # Port source existe ?
            src_port = next((p for p in src_def.outputs if p.name == edge.source_port), None)
            if src_port is None:
                errors.append(
                    f"Arête '{edge.id}': port source '{edge.source_port}' "
                    f"introuvable sur '{src_node.definition_id}'"
                )

            # Port cible existe ?
            tgt_port = next((p for p in tgt_def.inputs if p.name == edge.target_port), None)
            if tgt_port is None:
                errors.append(
                    f"Arête '{edge.id}': port cible '{edge.target_port}' "
                    f"introuvable sur '{tgt_node.definition_id}'"
                )

            # Compatibilité types
            if src_port and tgt_port:
                if (
                    src_port.type != "any"
                    and tgt_port.type != "any"
                    and src_port.type != tgt_port.type
                ):
                    errors.append(
                        f"Arête '{edge.id}': type incompatible "
                        f"'{src_port.type}' → '{tgt_port.type}'"
                    )

        # 5 — Détection de cycles
        if self._has_cycle(workflow):
            errors.append("Le workflow contient un cycle (pas un DAG valide)")

        return errors

    def topological_sort(self, workflow: Workflow) -> List[List[str]]:
        """
        Tri topologique par niveaux (Kahn).

        Retourne une liste de niveaux, chaque niveau contenant les IDs
        des nœuds qui peuvent s'exécuter en parallèle.
        """
        node_ids: Set[str] = {n.id for n in workflow.nodes}

        # Construire le graphe d'adjacence et les in-degrees
        in_degree: Dict[str, int] = {nid: 0 for nid in node_ids}
        successors: Dict[str, List[str]] = defaultdict(list)

        for edge in workflow.edges:
            if edge.source_node_id in node_ids and edge.target_node_id in node_ids:
                in_degree[edge.target_node_id] += 1
                successors[edge.source_node_id].append(edge.target_node_id)

        # Kahn par niveaux
        levels: List[List[str]] = []
        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )

        while queue:
            level = list(queue)
            levels.append(level)
            next_queue: deque[str] = deque()
            for nid in level:
                for succ in successors[nid]:
                    in_degree[succ] -= 1
                    if in_degree[succ] == 0:
                        next_queue.append(succ)
            queue = next_queue

        return levels

    async def execute(self, workflow: Workflow) -> List[ExecutionResult]:
        """
        Exécute un workflow complet.

        Les nœuds indépendants (même niveau topologique) s'exécutent
        en parallèle via asyncio.gather.
        """
        errors = self.validate(workflow)
        if errors:
            return [
                ExecutionResult(
                    node_id="__validation__",
                    status="error",
                    error="; ".join(errors),
                )
            ]

        levels = self.topological_sort(workflow)
        all_results: List[ExecutionResult] = []
        node_outputs: Dict[str, Any] = {}

        await self._publish_event("workflow_started", {"workflow_id": workflow.id})

        for level_idx, level in enumerate(levels):
            tasks = [
                self._execute_node(workflow, nid, node_outputs)
                for nid in level
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for nid, result in zip(level, results):
                if isinstance(result, Exception):
                    exec_result = ExecutionResult(
                        node_id=nid,
                        status="error",
                        error=str(result),
                    )
                else:
                    exec_result = result
                    node_outputs[nid] = exec_result.output

                all_results.append(exec_result)

                await self._publish_event(
                    "node_completed",
                    {
                        "workflow_id": workflow.id,
                        "node_id": nid,
                        "status": exec_result.status,
                        "level": level_idx,
                    },
                )

        await self._publish_event(
            "workflow_completed",
            {
                "workflow_id": workflow.id,
                "total_nodes": len(workflow.nodes),
                "results": len(all_results),
            },
        )

        return all_results

    async def _execute_node(
        self,
        workflow: Workflow,
        node_id: str,
        node_outputs: Dict[str, Any],
    ) -> ExecutionResult:
        """Exécute un nœud individuel."""
        start = time.monotonic()
        node = self._find_node(workflow, node_id)
        if node is None:
            return ExecutionResult(
                node_id=node_id,
                status="error",
                error=f"Nœud '{node_id}' introuvable",
            )

        # Collecter les entrées depuis les nœuds parents
        inputs: Dict[str, Any] = {}
        for edge in workflow.edges:
            if edge.target_node_id == node_id:
                parent_output = node_outputs.get(edge.source_node_id)
                if parent_output is not None:
                    inputs[edge.target_port] = parent_output

        try:
            # Pour l'instant : simulation d'exécution
            # En prod, ça appellera l'agent via FrontalCortex/ActionGate
            output = {
                "node_id": node_id,
                "definition_id": node.definition_id,
                "inputs_received": list(inputs.keys()),
                "config": node.config,
            }
            duration = (time.monotonic() - start) * 1000

            return ExecutionResult(
                node_id=node_id,
                status="success",
                output=output,
                duration_ms=duration,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            logger.error(f"WorkflowExecutor: erreur nœud '{node_id}': {exc}")
            return ExecutionResult(
                node_id=node_id,
                status="error",
                error=str(exc),
                duration_ms=duration,
            )

    def _find_node(
        self, workflow: Workflow, node_id: str
    ) -> Optional[WorkflowNode]:
        """Trouve un nœud par son ID dans un workflow."""
        for node in workflow.nodes:
            if node.id == node_id:
                return node
        return None

    def _has_cycle(self, workflow: Workflow) -> bool:
        """Détecte les cycles via DFS coloré."""
        node_ids: Set[str] = {n.id for n in workflow.nodes}
        successors: Dict[str, List[str]] = defaultdict(list)
        for edge in workflow.edges:
            if edge.source_node_id in node_ids and edge.target_node_id in node_ids:
                successors[edge.source_node_id].append(edge.target_node_id)

        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {nid: WHITE for nid in node_ids}

        def dfs(nid: str) -> bool:
            color[nid] = GRAY
            for succ in successors[nid]:
                if color[succ] == GRAY:
                    return True
                if color[succ] == WHITE and dfs(succ):
                    return True
            color[nid] = BLACK
            return False

        for nid in node_ids:
            if color[nid] == WHITE and dfs(nid):
                return True
        return False

    async def _publish_event(self, channel: str, data: Dict[str, Any]) -> None:
        """Publie un événement sur l'EventBus si disponible."""
        event_bus = self.event_bus
        if event_bus is None:
            return
        token = self.token
        if token is None:
            return
        try:
            await event_bus.publish(
                f"workflow_{channel}", data, source="WorkflowExecutor", token=token
            )
        except Exception as exc:
            logger.debug(f"WorkflowExecutor: échec publication événement: {exc}")
