"""
Tests pour le bridge PyWebView, le WebSocket server et les intégrations frontend.
"""

import os
import tempfile

import pytest

from app.workflows.bridge import WorkflowEditorAPI, get_frontend_path
from app.workflows.schemas import NodeDefinition, Port
from app.workflows.node_registry import NodeRegistry
from app.workflows.storage import WorkflowStorage
from app.workflows.executor import WorkflowExecutor
from app.workflows.ws_server import WorkflowWSServer


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────

def _make_registry() -> NodeRegistry:
    NodeRegistry.reset_singleton()
    registry = NodeRegistry()
    registry.register(NodeDefinition(
        id="test.node",
        name="TestNode",
        category="test",
        inputs=[Port(name="input", type="any")],
        outputs=[Port(name="output", type="any")],
    ))
    return registry


def _make_api() -> WorkflowEditorAPI:
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_wf.db")
    storage = WorkflowStorage(db_path=db_path)
    registry = _make_registry()
    executor = WorkflowExecutor(registry=registry)
    return WorkflowEditorAPI(storage=storage, registry=registry, executor=executor)


# ────────────────────────────────────────────────────────────────────────
# Tests Bridge API
# ────────────────────────────────────────────────────────────────────────

class TestBridgeAPI:
    def setup_method(self) -> None:
        self.api = _make_api()

    def teardown_method(self) -> None:
        self.api.shutdown()
        NodeRegistry.reset_singleton()

    def test_get_node_definitions(self) -> None:
        defs = self.api.get_node_definitions()
        assert len(defs) >= 1
        assert defs[0]["id"] == "test.node"
        assert defs[0]["name"] == "TestNode"

    def test_get_node_categories(self) -> None:
        cats = self.api.get_node_categories()
        assert "test" in cats

    def test_save_and_load_workflow(self) -> None:
        wf_data = {
            "id": "wf-test-1",
            "name": "Test Workflow",
            "description": "Un test",
            "nodes": [],
            "edges": [],
        }
        wf_id = self.api.save_workflow(wf_data)
        assert wf_id == "wf-test-1"

        loaded = self.api.load_workflow("wf-test-1")
        assert loaded is not None
        assert loaded["name"] == "Test Workflow"

    def test_load_missing(self) -> None:
        assert self.api.load_workflow("nonexistent") is None

    def test_list_workflows(self) -> None:
        assert self.api.list_workflows() == []
        self.api.save_workflow({"id": "a", "name": "A", "nodes": [], "edges": []})
        self.api.save_workflow({"id": "b", "name": "B", "nodes": [], "edges": []})
        wfs = self.api.list_workflows()
        assert len(wfs) == 2

    def test_delete_workflow(self) -> None:
        self.api.save_workflow({"id": "del1", "name": "Del", "nodes": [], "edges": []})
        assert self.api.delete_workflow("del1") is True
        assert self.api.load_workflow("del1") is None

    def test_validate_workflow_empty(self) -> None:
        errors = self.api.validate_workflow({"name": "Empty", "nodes": [], "edges": []})
        assert errors == []

    def test_validate_workflow_missing_def(self) -> None:
        errors = self.api.validate_workflow({
            "nodes": [{"id": "n1", "definition_id": "nonexistent"}],
            "edges": [],
        })
        assert len(errors) > 0
        assert any("introuvable" in e for e in errors)

    def test_execute_workflow_empty(self) -> None:
        results = self.api.execute_workflow({"name": "Vide", "nodes": [], "edges": []})
        assert results == []

    def test_execute_workflow_with_node(self) -> None:
        results = self.api.execute_workflow({
            "nodes": [{"id": "n1", "definition_id": "test.node", "label": "T"}],
            "edges": [],
        })
        assert len(results) == 1
        assert results[0]["status"] == "success"

    def test_save_invalid_returns_empty(self) -> None:
        # Passer des données qui ne peuvent pas être parsées
        result = self.api.save_workflow(None)
        assert result == ""


# ────────────────────────────────────────────────────────────────────────
# Tests Frontend Path
# ────────────────────────────────────────────────────────────────────────

class TestFrontendPath:
    def test_get_frontend_path(self) -> None:
        path = get_frontend_path()
        assert path.endswith("index.html")
        assert "frontend" in path

    def test_frontend_file_exists(self) -> None:
        path = get_frontend_path()
        assert os.path.exists(path)


# ────────────────────────────────────────────────────────────────────────
# Tests WebSocket Server
# ────────────────────────────────────────────────────────────────────────

class TestWSServer:
    def test_init_defaults(self) -> None:
        ws = WorkflowWSServer()
        assert ws._host == "127.0.0.1"
        assert ws._port == 9724
        assert ws.client_count == 0
        assert ws.is_running is False

    def test_init_custom(self) -> None:
        ws = WorkflowWSServer(host="0.0.0.0", port=8888)
        assert ws._host == "0.0.0.0"
        assert ws._port == 8888

    @pytest.mark.asyncio
    async def test_broadcast_no_clients(self) -> None:
        ws = WorkflowWSServer()
        # Ne devrait pas lever d'erreur
        await ws.broadcast("test_event", {"key": "value"})

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self) -> None:
        ws = WorkflowWSServer()
        await ws.stop()
        assert ws.is_running is False
