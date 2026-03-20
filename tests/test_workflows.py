"""
Tests pour app.workflows — schemas, node_registry, executor, storage.
"""

import os
import tempfile

import pytest

from app.workflows.schemas import (
    ExecutionResult,
    NodeDefinition,
    Port,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)
from app.workflows.node_registry import NodeRegistry
from app.workflows.executor import WorkflowExecutor
from app.workflows.storage import WorkflowStorage


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────

def _make_port(name: str = "input", type_: str = "any") -> Port:
    return Port(name=name, type=type_)


def _make_node_def(
    id_: str = "test.node",
    name: str = "TestNode",
    category: str = "test",
    inputs: list | None = None,
    outputs: list | None = None,
) -> NodeDefinition:
    return NodeDefinition(
        id=id_,
        name=name,
        category=category,
        inputs=inputs or [Port(name="input", type="any")],
        outputs=outputs or [Port(name="output", type="any")],
    )


def _make_linear_workflow(node_count: int = 3) -> tuple:
    """Crée un workflow linéaire : A → B → C → ..."""
    registry = NodeRegistry()
    registry.clear()

    node_def = _make_node_def()
    registry.register(node_def)

    nodes = [
        WorkflowNode(id=f"n{i}", definition_id="test.node", label=f"Node {i}")
        for i in range(node_count)
    ]
    edges = [
        WorkflowEdge(
            source_node_id=f"n{i}",
            source_port="output",
            target_node_id=f"n{i+1}",
            target_port="input",
        )
        for i in range(node_count - 1)
    ]
    wf = Workflow(id="wf-linear", name="Linear", nodes=nodes, edges=edges)
    return wf, registry


# ────────────────────────────────────────────────────────────────────────
# Tests Schemas
# ────────────────────────────────────────────────────────────────────────

class TestSchemas:
    def test_port_creation(self) -> None:
        port = Port(name="data", type="string", description="Données texte")
        assert port.name == "data"
        assert port.type == "string"
        assert port.required is True

    def test_port_defaults(self) -> None:
        port = Port(name="x")
        assert port.type == "any"
        assert port.default is None

    def test_node_definition(self) -> None:
        nd = _make_node_def(id_="my.node", name="MyNode", category="custom")
        assert nd.id == "my.node"
        assert nd.category == "custom"
        assert len(nd.inputs) == 1
        assert len(nd.outputs) == 1

    def test_workflow_node(self) -> None:
        wn = WorkflowNode(definition_id="test.node", label="Mon nœud")
        assert wn.definition_id == "test.node"
        assert wn.label == "Mon nœud"
        assert wn.position_x == 0.0

    def test_workflow_edge(self) -> None:
        edge = WorkflowEdge(
            source_node_id="a",
            source_port="output",
            target_node_id="b",
            target_port="input",
        )
        assert edge.source_node_id == "a"
        assert edge.target_node_id == "b"

    def test_workflow_creation(self) -> None:
        wf = Workflow(name="Test WF")
        assert wf.name == "Test WF"
        assert len(wf.nodes) == 0
        assert len(wf.edges) == 0
        assert wf.id  # UUID auto-généré

    def test_execution_result(self) -> None:
        er = ExecutionResult(node_id="n1", status="success", output={"key": "val"})
        assert er.status == "success"
        assert er.error is None
        assert er.duration_ms == 0.0

    def test_workflow_serialization(self) -> None:
        wf = Workflow(name="Sérialisable")
        data = wf.json()
        loaded = Workflow.parse_raw(data)
        assert loaded.name == wf.name
        assert loaded.id == wf.id


# ────────────────────────────────────────────────────────────────────────
# Tests NodeRegistry
# ────────────────────────────────────────────────────────────────────────

class TestNodeRegistry:
    def setup_method(self) -> None:
        NodeRegistry.reset_singleton()
        self.registry = NodeRegistry()

    def teardown_method(self) -> None:
        NodeRegistry.reset_singleton()

    def test_singleton(self) -> None:
        r1 = NodeRegistry()
        r2 = NodeRegistry()
        assert r1 is r2

    def test_register_and_get(self) -> None:
        nd = _make_node_def(id_="test.a")
        self.registry.register(nd)
        assert self.registry.get("test.a") is nd

    def test_get_missing(self) -> None:
        assert self.registry.get("nonexistent") is None

    def test_list_all(self) -> None:
        self.registry.register(_make_node_def(id_="a"))
        self.registry.register(_make_node_def(id_="b"))
        assert len(self.registry.list_all()) == 2

    def test_list_by_category(self) -> None:
        self.registry.register(_make_node_def(id_="a", category="cat1"))
        self.registry.register(_make_node_def(id_="b", category="cat2"))
        self.registry.register(_make_node_def(id_="c", category="cat1"))
        assert len(self.registry.list_by_category("cat1")) == 2
        assert len(self.registry.list_by_category("cat2")) == 1

    def test_categories(self) -> None:
        self.registry.register(_make_node_def(id_="a", category="z"))
        self.registry.register(_make_node_def(id_="b", category="a"))
        cats = self.registry.categories()
        assert cats == ["a", "z"]

    def test_unregister(self) -> None:
        self.registry.register(_make_node_def(id_="x"))
        assert self.registry.unregister("x") is True
        assert self.registry.get("x") is None
        assert self.registry.unregister("x") is False

    def test_clear(self) -> None:
        self.registry.register(_make_node_def(id_="a"))
        self.registry.clear()
        assert len(self.registry.list_all()) == 0


# ────────────────────────────────────────────────────────────────────────
# Tests WorkflowExecutor
# ────────────────────────────────────────────────────────────────────────

class TestWorkflowExecutor:
    def setup_method(self) -> None:
        NodeRegistry.reset_singleton()

    def teardown_method(self) -> None:
        NodeRegistry.reset_singleton()

    def test_validate_empty_workflow(self) -> None:
        registry = NodeRegistry()
        executor = WorkflowExecutor(registry=registry)
        wf = Workflow(name="Empty")
        errors = executor.validate(wf)
        assert errors == []

    def test_validate_missing_definition(self) -> None:
        registry = NodeRegistry()
        executor = WorkflowExecutor(registry=registry)
        wf = Workflow(
            nodes=[WorkflowNode(id="n1", definition_id="nonexistent")],
        )
        errors = executor.validate(wf)
        assert any("introuvable" in e for e in errors)

    def test_validate_missing_edge_node(self) -> None:
        registry = NodeRegistry()
        nd = _make_node_def()
        registry.register(nd)
        executor = WorkflowExecutor(registry=registry)
        wf = Workflow(
            nodes=[WorkflowNode(id="n1", definition_id="test.node")],
            edges=[
                WorkflowEdge(
                    source_node_id="n1",
                    source_port="output",
                    target_node_id="n_missing",
                    target_port="input",
                )
            ],
        )
        errors = executor.validate(wf)
        assert any("n_missing" in e for e in errors)

    def test_validate_type_mismatch(self) -> None:
        registry = NodeRegistry()
        registry.register(
            NodeDefinition(
                id="src",
                name="Src",
                outputs=[Port(name="out", type="string")],
            )
        )
        registry.register(
            NodeDefinition(
                id="tgt",
                name="Tgt",
                inputs=[Port(name="in", type="number")],
            )
        )
        executor = WorkflowExecutor(registry=registry)
        wf = Workflow(
            nodes=[
                WorkflowNode(id="a", definition_id="src"),
                WorkflowNode(id="b", definition_id="tgt"),
            ],
            edges=[
                WorkflowEdge(
                    source_node_id="a",
                    source_port="out",
                    target_node_id="b",
                    target_port="in",
                )
            ],
        )
        errors = executor.validate(wf)
        assert any("incompatible" in e for e in errors)

    def test_validate_any_type_compatible(self) -> None:
        registry = NodeRegistry()
        registry.register(
            NodeDefinition(
                id="src",
                name="Src",
                outputs=[Port(name="out", type="any")],
            )
        )
        registry.register(
            NodeDefinition(
                id="tgt",
                name="Tgt",
                inputs=[Port(name="in", type="number")],
            )
        )
        executor = WorkflowExecutor(registry=registry)
        wf = Workflow(
            nodes=[
                WorkflowNode(id="a", definition_id="src"),
                WorkflowNode(id="b", definition_id="tgt"),
            ],
            edges=[
                WorkflowEdge(
                    source_node_id="a",
                    source_port="out",
                    target_node_id="b",
                    target_port="in",
                )
            ],
        )
        errors = executor.validate(wf)
        assert errors == []

    def test_detect_cycle(self) -> None:
        registry = NodeRegistry()
        nd = _make_node_def()
        registry.register(nd)
        executor = WorkflowExecutor(registry=registry)
        wf = Workflow(
            nodes=[
                WorkflowNode(id="a", definition_id="test.node"),
                WorkflowNode(id="b", definition_id="test.node"),
            ],
            edges=[
                WorkflowEdge(
                    source_node_id="a",
                    source_port="output",
                    target_node_id="b",
                    target_port="input",
                ),
                WorkflowEdge(
                    source_node_id="b",
                    source_port="output",
                    target_node_id="a",
                    target_port="input",
                ),
            ],
        )
        errors = executor.validate(wf)
        assert any("cycle" in e for e in errors)

    def test_topological_sort_linear(self) -> None:
        wf, registry = _make_linear_workflow(3)
        executor = WorkflowExecutor(registry=registry)
        levels = executor.topological_sort(wf)
        assert levels == [["n0"], ["n1"], ["n2"]]

    def test_topological_sort_parallel(self) -> None:
        registry = NodeRegistry()
        nd = _make_node_def()
        registry.register(nd)

        # n0 → n1, n0 → n2 (n1 et n2 parallèles)
        wf = Workflow(
            nodes=[
                WorkflowNode(id="n0", definition_id="test.node"),
                WorkflowNode(id="n1", definition_id="test.node"),
                WorkflowNode(id="n2", definition_id="test.node"),
            ],
            edges=[
                WorkflowEdge(
                    source_node_id="n0",
                    source_port="output",
                    target_node_id="n1",
                    target_port="input",
                ),
                WorkflowEdge(
                    source_node_id="n0",
                    source_port="output",
                    target_node_id="n2",
                    target_port="input",
                ),
            ],
        )
        executor = WorkflowExecutor(registry=registry)
        levels = executor.topological_sort(wf)
        assert levels[0] == ["n0"]
        assert set(levels[1]) == {"n1", "n2"}

    @pytest.mark.asyncio
    async def test_execute_linear(self) -> None:
        wf, registry = _make_linear_workflow(3)
        executor = WorkflowExecutor(registry=registry)
        results = await executor.execute(wf)
        assert len(results) == 3
        assert all(r.status == "success" for r in results)

    @pytest.mark.asyncio
    async def test_execute_validation_error(self) -> None:
        registry = NodeRegistry()
        executor = WorkflowExecutor(registry=registry)
        wf = Workflow(
            nodes=[WorkflowNode(id="n1", definition_id="nonexistent")],
        )
        results = await executor.execute(wf)
        assert len(results) == 1
        assert results[0].status == "error"
        assert results[0].node_id == "__validation__"

    @pytest.mark.asyncio
    async def test_execute_empty(self) -> None:
        registry = NodeRegistry()
        executor = WorkflowExecutor(registry=registry)
        wf = Workflow(name="Vide")
        results = await executor.execute(wf)
        assert results == []


# ────────────────────────────────────────────────────────────────────────
# Tests WorkflowStorage
# ────────────────────────────────────────────────────────────────────────

class TestWorkflowStorage:
    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "test_workflows.db")
        self.storage = WorkflowStorage(db_path=self._db_path)

    def test_save_and_load(self) -> None:
        wf = Workflow(id="wf1", name="Mon workflow")
        self.storage.save(wf)
        loaded = self.storage.load("wf1")
        assert loaded is not None
        assert loaded.name == "Mon workflow"

    def test_load_missing(self) -> None:
        assert self.storage.load("nonexistent") is None

    def test_list_all_empty(self) -> None:
        assert self.storage.list_all() == []

    def test_list_all(self) -> None:
        self.storage.save(Workflow(id="a", name="A"))
        self.storage.save(Workflow(id="b", name="B"))
        all_wf = self.storage.list_all()
        assert len(all_wf) == 2

    def test_delete(self) -> None:
        self.storage.save(Workflow(id="del1", name="Del"))
        assert self.storage.delete("del1") is True
        assert self.storage.load("del1") is None

    def test_delete_missing(self) -> None:
        assert self.storage.delete("nonexistent") is False

    def test_count(self) -> None:
        assert self.storage.count() == 0
        self.storage.save(Workflow(id="c1", name="C1"))
        assert self.storage.count() == 1

    def test_update(self) -> None:
        self.storage.save(Workflow(id="u1", name="Original"))
        self.storage.save(Workflow(id="u1", name="Modifié"))
        loaded = self.storage.load("u1")
        assert loaded is not None
        assert loaded.name == "Modifié"
        assert self.storage.count() == 1
