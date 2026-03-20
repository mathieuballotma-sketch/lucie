"""
WorkflowExecutor — Moteur d'exécution de workflows visuels.

Fonctionnalités :
  - Validation du DAG (cycles, orphelins, types)
  - Tri topologique (Kahn) pour exécution parallèle par niveaux
  - Dispatch par type de nœud (control, llm, data, agent)
  - Propagation des outputs entre nœuds via les edges
  - Publication d'événements sur l'EventBus
  - Intégration ActionGate pour les nœuds à effet de bord
"""
import ast
import asyncio
import operator
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .schemas import ExecutionResult, Workflow, WorkflowEdge, WorkflowNode
from .node_registry import NodeRegistry
from ..utils.logger import logger


# ── Évaluateur d'expressions sécurisé ────────────────────────────────────────

_COMPARE_OPS: Dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _eval_ast_value(node: ast.expr, context: Dict[str, Any]) -> Any:
    """Évalue un nœud AST simple (Constant, Name) depuis un contexte."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return context.get(node.id)
    raise ValueError(f"Nœud AST non supporté : {type(node).__name__}")


def _safe_eval_condition(expression: str, context: Dict[str, Any]) -> bool:
    """
    Évalue une expression de comparaison simple (ex: 'value > 5').

    Supporte uniquement les comparaisons binaires de constantes/noms.
    Tout autre expression retourne False sans lever d'exception.
    """
    if not expression:
        return bool(context.get("value"))
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        body = tree.body

        if isinstance(body, ast.Compare):
            left = _eval_ast_value(body.left, context)
            for op, comparator in zip(body.ops, body.comparators):
                right = _eval_ast_value(comparator, context)
                fn = _COMPARE_OPS.get(type(op))
                if fn is None:
                    logger.warning(f"Opérateur non supporté : {type(op).__name__}")
                    return False
                if not fn(left, right):
                    return False
                left = right
            return True

        if isinstance(body, ast.Constant):
            return bool(body.value)

        if isinstance(body, ast.Name):
            return bool(context.get(body.id))

    except Exception as e:
        logger.warning(f"_safe_eval_condition: expression='{expression}' — {e}")

    return False


# ── WorkflowExecutor ──────────────────────────────────────────────────────────

class WorkflowExecutor:
    """
    Exécute un workflow en respectant le DAG.

    Les nœuds indépendants d'un même niveau sont exécutés en parallèle
    via asyncio.gather. Si un nœud échoue, les nœuds qui n'en dépendent
    pas continuent de s'exécuter.
    """

    def __init__(
        self,
        registry: NodeRegistry,
        agents: Optional[Dict[str, Any]] = None,
        provider: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        token: Optional[str] = None,
        action_gate: Optional[Any] = None,
    ) -> None:
        self.registry = registry
        self.agents: Dict[str, Any] = agents or {}
        self.provider = provider
        self.event_bus = event_bus
        self.token = token
        self.action_gate = action_gate

    # ── Validation ───────────────────────────────────────────────────────────

    def validate(self, workflow: Workflow) -> List[str]:
        """
        Valide le workflow. Retourne une liste d'erreurs (liste vide = valide).

        Vérifie :
          - Workflow non vide
          - Références d'edges valides
          - Absence de cycles (DFS)
          - Nœuds orphelins (aucune connexion)
          - Compatibilité des types de ports
        """
        errors: List[str] = []

        if not workflow.nodes:
            errors.append("Le workflow ne contient aucun nœud.")
            return errors

        node_ids = {n.id for n in workflow.nodes}

        # Références d'edges
        for edge in workflow.edges:
            if edge.source_node not in node_ids:
                errors.append(
                    f"Edge {edge.id}: nœud source '{edge.source_node}' introuvable."
                )
            if edge.target_node not in node_ids:
                errors.append(
                    f"Edge {edge.id}: nœud cible '{edge.target_node}' introuvable."
                )

        # Cycles
        if self._has_cycle(workflow):
            errors.append("Le workflow contient un cycle — exécution impossible.")

        # Orphelins (nœuds sans aucune connexion)
        connected: set = set()
        for edge in workflow.edges:
            connected.add(edge.source_node)
            connected.add(edge.target_node)

        _exempt = {"control.start", "control.end"}
        for node in workflow.nodes:
            if node.id not in connected and node.node_type not in _exempt:
                errors.append(
                    f"Nœud '{node.id}' ({node.node_type}) est orphelin (aucune connexion)."
                )

        # Compatibilité des types de ports
        node_map = {n.id: n for n in workflow.nodes}
        for edge in workflow.edges:
            src_node = node_map.get(edge.source_node)
            tgt_node = node_map.get(edge.target_node)
            if not src_node or not tgt_node:
                continue

            src_def = self.registry.get(src_node.node_type)
            tgt_def = self.registry.get(tgt_node.node_type)
            if not src_def or not tgt_def:
                continue

            src_port = next(
                (p for p in src_def.outputs if p.id == edge.source_port), None
            )
            tgt_port = next(
                (p for p in tgt_def.inputs if p.id == edge.target_port), None
            )

            if src_port and tgt_port:
                compatible = (
                    src_port.data_type == tgt_port.data_type
                    or "any" in (src_port.data_type, tgt_port.data_type)
                )
                if not compatible:
                    errors.append(
                        f"Edge {edge.id}: type incompatible "
                        f"'{src_port.data_type}' → '{tgt_port.data_type}'."
                    )

        return errors

    def _has_cycle(self, workflow: Workflow) -> bool:
        """Détecte les cycles via DFS (visited + in_stack)."""
        adjacency: Dict[str, List[str]] = defaultdict(list)
        for edge in workflow.edges:
            adjacency[edge.source_node].append(edge.target_node)

        visited: set = set()
        in_stack: set = set()

        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            in_stack.add(node_id)
            for neighbor in adjacency[node_id]:
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in in_stack:
                    return True
            in_stack.discard(node_id)
            return False

        for node in workflow.nodes:
            if node.id not in visited:
                if dfs(node.id):
                    return True
        return False

    # ── Tri topologique ───────────────────────────────────────────────────────

    def _topological_levels(self, workflow: Workflow) -> List[List[str]]:
        """
        Algorithme de Kahn — retourne les nœuds groupés par niveaux.

        Les nœuds d'un même niveau n'ont aucune dépendance entre eux
        et peuvent s'exécuter en parallèle.
        """
        in_degree: Dict[str, int] = {n.id: 0 for n in workflow.nodes}
        children: Dict[str, List[str]] = defaultdict(list)

        for edge in workflow.edges:
            if edge.source_node in in_degree and edge.target_node in in_degree:
                children[edge.source_node].append(edge.target_node)
                in_degree[edge.target_node] += 1

        queue: List[str] = [nid for nid, deg in in_degree.items() if deg == 0]
        levels: List[List[str]] = []

        while queue:
            levels.append(list(queue))
            next_queue: List[str] = []
            for nid in queue:
                for child in children[nid]:
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        next_queue.append(child)
            queue = next_queue

        return levels

    # ── Exécution ─────────────────────────────────────────────────────────────

    async def execute(
        self,
        workflow: Workflow,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, ExecutionResult]:
        """
        Exécute le workflow et retourne les résultats indexés par node_id.

        Retourne un dict vide si le workflow est invalide.
        """
        errors = self.validate(workflow)
        if errors:
            logger.error(f"WorkflowExecutor: workflow invalide — {errors}")
            return {}

        results: Dict[str, ExecutionResult] = {}
        # Injecter les edges dans le contexte pour _execute_node
        _ctx: Dict[str, Any] = {**(context or {}), "_edges": workflow.edges}
        node_map = {n.id: n for n in workflow.nodes}
        outputs_store: Dict[str, Dict[str, Any]] = {}

        await self._publish("workflow_start", {
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
        })

        for level in self._topological_levels(workflow):
            tasks = [
                self._execute_node_safe(node_map[nid], outputs_store, _ctx)
                for nid in level
            ]
            level_results = await asyncio.gather(*tasks)

            for nid, result in zip(level, level_results):
                results[nid] = result
                if result.status == "success":
                    outputs_store[nid] = result.outputs

        success_count = sum(1 for r in results.values() if r.status == "success")
        await self._publish("workflow_complete", {
            "workflow_id": workflow.id,
            "total": len(results),
            "success": success_count,
        })

        return results

    def _gather_inputs(
        self,
        node_id: str,
        edges: List[WorkflowEdge],
        outputs_store: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Collecte les inputs d'un nœud depuis les outputs des nœuds précédents."""
        inputs: Dict[str, Any] = {}
        for edge in edges:
            if edge.target_node != node_id:
                continue
            src_outputs = outputs_store.get(edge.source_node, {})
            value = src_outputs.get(edge.source_port)
            if value is not None:
                inputs[edge.target_port] = value
        return inputs

    async def _execute_node_safe(
        self,
        node: WorkflowNode,
        outputs_store: Dict[str, Dict[str, Any]],
        ctx: Dict[str, Any],
    ) -> ExecutionResult:
        """Wrapper sécurisé — isole les erreurs et publie les événements."""
        await self._publish("workflow_node_start", {
            "node_id": node.id,
            "node_type": node.node_type,
        })
        start = time.monotonic()
        try:
            result = await self._execute_node(node, outputs_store, ctx)
            result.duration_ms = (time.monotonic() - start) * 1000
            await self._publish("workflow_node_complete", {
                "node_id": node.id,
                "node_type": node.node_type,
                "status": result.status,
                "duration_ms": result.duration_ms,
            })
            return result
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(
                f"WorkflowExecutor: nœud {node.id} ({node.node_type}) — {exc}"
            )
            await self._publish("workflow_error", {
                "node_id": node.id,
                "node_type": node.node_type,
                "error": str(exc),
            })
            return ExecutionResult(
                node_id=node.id,
                status="error",
                error=str(exc),
                duration_ms=duration_ms,
            )

    async def _execute_node(
        self,
        node: WorkflowNode,
        outputs_store: Dict[str, Dict[str, Any]],
        ctx: Dict[str, Any],
    ) -> ExecutionResult:
        """Dispatch selon le type de nœud."""
        # Les inputs viennent du workflow courant — reconstruit depuis outputs_store
        # Note: on a besoin des edges pour ça, mais on les passe via ctx
        edges: List[WorkflowEdge] = ctx.get("_edges", [])
        inputs = self._gather_inputs(node.id, edges, outputs_store)

        ntype = node.node_type

        if ntype == "control.start":
            return ExecutionResult(
                node_id=node.id,
                status="success",
                outputs={"trigger": True},
            )

        if ntype == "control.end":
            return ExecutionResult(
                node_id=node.id,
                status="success",
                outputs={"result": inputs.get("result", inputs)},
            )

        if ntype == "control.condition":
            return self._execute_condition(node, inputs)

        if ntype == "control.for_each":
            return self._execute_for_each(node, inputs)

        if ntype == "control.wait":
            seconds = float(node.config.get("seconds", 1))
            await asyncio.sleep(seconds)
            return ExecutionResult(
                node_id=node.id,
                status="success",
                outputs={"done": True},
            )

        if ntype == "llm.generate":
            return await self._execute_llm(node, inputs)

        if ntype == "data.read_file":
            return await self._execute_read_file(node, inputs)

        if ntype == "data.write_file":
            return await self._execute_write_file(node, inputs)

        if ntype == "data.variable":
            value = inputs.get("value")
            if value is None:
                value = node.config.get("value")
            return ExecutionResult(
                node_id=node.id,
                status="success",
                outputs={"value": value},
            )

        if ntype.startswith("agent."):
            return await self._execute_agent(node, inputs)

        logger.warning(f"WorkflowExecutor: type de nœud inconnu '{ntype}' — skipped")
        return ExecutionResult(node_id=node.id, status="skipped")

    # ── Handlers spécialisés ──────────────────────────────────────────────────

    def _execute_condition(
        self, node: WorkflowNode, inputs: Dict[str, Any]
    ) -> ExecutionResult:
        """Évalue une expression de comparaison et retourne la branche."""
        value = inputs.get("value")
        expression = (
            inputs.get("condition")
            or node.config.get("expression", "")
        )
        ctx = {"value": value, **inputs}
        result = _safe_eval_condition(str(expression) if expression else "", ctx)

        return ExecutionResult(
            node_id=node.id,
            status="success",
            outputs={
                "true": value if result else None,
                "false": value if not result else None,
                "branch": "true" if result else "false",
            },
        )

    def _execute_for_each(
        self, node: WorkflowNode, inputs: Dict[str, Any]
    ) -> ExecutionResult:
        """Retourne les éléments du tableau + métadonnées d'itération."""
        items = inputs.get("items", node.config.get("items", []))
        if not isinstance(items, list):
            items = [items]

        return ExecutionResult(
            node_id=node.id,
            status="success",
            outputs={
                "items": items,
                "item": items[0] if items else None,
                "index": 0,
                "count": len(items),
            },
        )

    async def _execute_llm(
        self, node: WorkflowNode, inputs: Dict[str, Any]
    ) -> ExecutionResult:
        """Génère du texte via le ProviderManager."""
        provider = self.provider
        if provider is None:
            return ExecutionResult(
                node_id=node.id,
                status="error",
                error="Provider LLM non configuré dans WorkflowExecutor.",
            )

        prompt = inputs.get("prompt") or node.config.get("prompt", "")
        system = inputs.get("system") or node.config.get("system")
        model = str(node.config.get("model", "balanced"))
        temperature = float(node.config.get("temperature", 0.7))
        max_tokens = int(node.config.get("max_tokens", 512))

        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(
                None,
                lambda: provider.generate(
                    prompt=str(prompt),
                    system=system,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
            )
            return ExecutionResult(
                node_id=node.id,
                status="success",
                outputs={"response": response, "text": response},
            )
        except Exception as e:
            return ExecutionResult(
                node_id=node.id, status="error", error=str(e)
            )

    async def _execute_read_file(
        self, node: WorkflowNode, inputs: Dict[str, Any]
    ) -> ExecutionResult:
        """Lit un fichier texte (passe par ActionGate si configuré)."""
        path = inputs.get("path") or node.config.get("path", "")
        if not path:
            return ExecutionResult(
                node_id=node.id, status="error", error="Chemin manquant."
            )

        action_gate = self.action_gate
        if action_gate is not None:
            approved, _ = action_gate.evaluate({
                "action_type": "list_files",
                "preview": f"read {path}",
                "agent": "workflow",
            })
            if not approved:
                return ExecutionResult(
                    node_id=node.id,
                    status="error",
                    error="ActionGate: lecture refusée.",
                )

        try:
            content = Path(str(path)).expanduser().read_text(encoding="utf-8")
            return ExecutionResult(
                node_id=node.id,
                status="success",
                outputs={"content": content, "path": str(path)},
            )
        except Exception as e:
            return ExecutionResult(node_id=node.id, status="error", error=str(e))

    async def _execute_write_file(
        self, node: WorkflowNode, inputs: Dict[str, Any]
    ) -> ExecutionResult:
        """Écrit un fichier (passe par ActionGate si configuré)."""
        path = inputs.get("path") or node.config.get("path", "")
        content = inputs.get("content") or node.config.get("content", "")

        if not path:
            return ExecutionResult(
                node_id=node.id, status="error", error="Chemin manquant."
            )

        action_gate = self.action_gate
        if action_gate is not None:
            approved, _ = action_gate.evaluate({
                "action_type": "write_file",
                "preview": f"write {path}",
                "agent": "workflow",
            })
            if not approved:
                return ExecutionResult(
                    node_id=node.id,
                    status="error",
                    error="ActionGate: écriture refusée.",
                )

        try:
            p = Path(str(path)).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(content), encoding="utf-8")
            return ExecutionResult(
                node_id=node.id,
                status="success",
                outputs={"path": str(p)},
            )
        except Exception as e:
            return ExecutionResult(node_id=node.id, status="error", error=str(e))

    async def _execute_agent(
        self, node: WorkflowNode, inputs: Dict[str, Any]
    ) -> ExecutionResult:
        """Appelle un agent par son nom (via agents dict)."""
        agent_key = node.node_type.split(".", 1)[1] if "." in node.node_type else node.node_type
        query = str(inputs.get("query") or node.config.get("query", ""))

        # Recherche de l'agent dans le dict (clé exacte ou fuzzy)
        agent = self.agents.get(agent_key) or self.agents.get(node.node_type)
        if agent is None:
            for key, val in self.agents.items():
                if agent_key.lower().replace("_", "") in key.lower().replace("_", ""):
                    agent = val
                    break

        if agent is None:
            return ExecutionResult(
                node_id=node.id,
                status="error",
                error=f"Agent '{agent_key}' non trouvé dans WorkflowExecutor.",
            )

        action_gate = self.action_gate
        if action_gate is not None:
            approved, _ = action_gate.evaluate({
                "action_type": "list_agents",
                "preview": f"agent {agent_key}: {query[:50]}",
                "agent": "workflow",
            })
            if not approved:
                return ExecutionResult(
                    node_id=node.id,
                    status="error",
                    error="ActionGate: appel agent refusé.",
                )

        try:
            if hasattr(agent, "handle"):
                response = await agent.handle(query)
            else:
                response = str(agent)

            return ExecutionResult(
                node_id=node.id,
                status="success",
                outputs={"response": response},
            )
        except Exception as e:
            return ExecutionResult(node_id=node.id, status="error", error=str(e))

    # ── EventBus ──────────────────────────────────────────────────────────────

    async def _publish(self, channel: str, data: Dict[str, Any]) -> None:
        """Publie un événement sur l'EventBus si disponible."""
        event_bus = self.event_bus
        if event_bus is None or not self.token:
            return
        try:
            await event_bus.publish(
                channel=channel,
                data=data,
                source="workflow_executor",
                token=self.token,
            )
        except Exception as e:
            logger.debug(f"WorkflowExecutor._publish({channel}): {e}")
