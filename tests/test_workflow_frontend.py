"""
Tests pour le frontend de l'éditeur de flux visuel.

Couvre :
  - WorkflowEditorAPI (bridge.py) : toutes les méthodes
  - WorkflowEventServer (ws_server.py) : démarrage, arrêt, broadcast
Les tests fonctionnent sans pywebview ni websockets (mocks).
"""

import asyncio
import json
import sys
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub webview avant tout import de bridge ────────────────────────────────
_mock_webview = MagicMock()
sys.modules.setdefault("webview", _mock_webview)

from app.workflows.bridge import WorkflowEditorAPI  # noqa: E402
from app.workflows.node_registry import NodeRegistry  # noqa: E402
from app.workflows.schemas import (  # noqa: E402
    NodeDefinition,
    Port,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)
from app.workflows.storage import WorkflowStorage  # noqa: E402
from app.workflows.ws_server import WorkflowEventServer  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def registry():
    """Registre isolé avec quelques définitions de nœuds."""
    NodeRegistry.reset_singleton()
    reg = NodeRegistry()
    reg.register(
        NodeDefinition(
            id="test.node_a",
            name="NodeA",
            category="test",
            description="Nœud de test A",
            inputs=[Port(name="in", type="any")],
            outputs=[Port(name="out", type="any")],
            config_schema={"key": {"type": "string", "description": "Clé"}},
        )
    )
    reg.register(
        NodeDefinition(
            id="test.node_b",
            name="NodeB",
            category="test",
            description="Nœud de test B",
            inputs=[Port(name="data", type="string")],
            outputs=[Port(name="result", type="string")],
        )
    )
    yield reg
    NodeRegistry.reset_singleton()


@pytest.fixture
def storage(tmp_path):
    """WorkflowStorage temporaire (SQLite en mémoire)."""
    return WorkflowStorage(db_path=str(tmp_path / "test_workflows.db"))


@pytest.fixture
def api(registry, storage):
    """WorkflowEditorAPI configurée pour les tests."""
    instance = WorkflowEditorAPI(storage=storage, registry=registry)
    yield instance
    instance.shutdown()


@pytest.fixture
def simple_workflow():
    """Workflow valide avec deux nœuds connectés."""
    n1 = WorkflowNode(id="n1", definition_id="test.node_a", position_x=0, position_y=0)
    n2 = WorkflowNode(id="n2", definition_id="test.node_b", position_x=200, position_y=0)
    edge = WorkflowEdge(
        id="e1",
        source_node_id="n1",
        source_port="out",
        target_node_id="n2",
        target_port="data",
    )
    return Workflow(name="Test WF", nodes=[n1, n2], edges=[edge])


# ── Tests WorkflowEditorAPI ───────────────────────────────────────────────────


class TestGetNodeDefinitions:
    def test_returns_list(self, api):
        defs = api.get_node_definitions()
        assert isinstance(defs, list)

    def test_count_matches_registry(self, api):
        defs = api.get_node_definitions()
        assert len(defs) == 2

    def test_definition_fields_present(self, api):
        defs = api.get_node_definitions()
        for d in defs:
            assert "id" in d
            assert "name" in d
            assert "category" in d
            assert "description" in d
            assert "inputs" in d
            assert "outputs" in d
            assert "config_schema" in d

    def test_ports_are_serialized(self, api):
        defs = api.get_node_definitions()
        node_a = next(d for d in defs if d["id"] == "test.node_a")
        assert len(node_a["inputs"]) == 1
        assert node_a["inputs"][0]["name"] == "in"
        assert len(node_a["outputs"]) == 1
        assert node_a["outputs"][0]["name"] == "out"

    def test_config_schema_included(self, api):
        defs = api.get_node_definitions()
        node_a = next(d for d in defs if d["id"] == "test.node_a")
        assert "key" in node_a["config_schema"]

    def test_empty_registry(self, storage):
        NodeRegistry.reset_singleton()
        empty_reg = NodeRegistry()
        instance = WorkflowEditorAPI(storage=storage, registry=empty_reg)
        try:
            api_result = instance.get_node_definitions()
            assert api_result == []
        finally:
            instance.shutdown()
            NodeRegistry.reset_singleton()


class TestSaveAndLoadWorkflow:
    def test_save_returns_id(self, api, simple_workflow):
        wf_id = api.save_workflow(simple_workflow.dict())
        assert isinstance(wf_id, str)
        assert len(wf_id) > 0

    def test_save_and_load_roundtrip(self, api, simple_workflow):
        wf_id = api.save_workflow(simple_workflow.dict())
        loaded = api.load_workflow(wf_id)
        assert loaded is not None
        assert loaded["name"] == "Test WF"
        assert len(loaded["nodes"]) == 2
        assert len(loaded["edges"]) == 1

    def test_load_nonexistent_returns_none(self, api):
        result = api.load_workflow("does-not-exist-xyz")
        assert result is None

    def test_save_invalid_data_returns_empty(self, api):
        result = api.save_workflow({"invalid": "garbage", "nodes": "not-a-list"})
        assert result == ""

    def test_update_workflow(self, api, simple_workflow):
        wf_id = api.save_workflow(simple_workflow.dict())
        updated = simple_workflow.copy(update={"name": "Updated"})
        api.save_workflow(updated.dict())
        loaded = api.load_workflow(wf_id)
        assert loaded is not None
        assert loaded["name"] == "Updated"


class TestListWorkflows:
    def test_empty_list(self, api):
        result = api.list_workflows()
        assert result == []

    def test_list_after_save(self, api, simple_workflow):
        api.save_workflow(simple_workflow.dict())
        result = api.list_workflows()
        assert len(result) == 1
        item = result[0]
        assert "id" in item
        assert "name" in item
        assert "node_count" in item
        assert "edge_count" in item
        assert item["node_count"] == 2
        assert item["edge_count"] == 1

    def test_multiple_workflows(self, api, simple_workflow):
        wf2 = simple_workflow.copy(update={"id": str(uuid.uuid4()), "name": "Second"})
        api.save_workflow(simple_workflow.dict())
        api.save_workflow(wf2.dict())
        result = api.list_workflows()
        assert len(result) == 2


class TestValidateWorkflow:
    def test_valid_workflow_no_errors(self, api, simple_workflow):
        errors = api.validate_workflow(simple_workflow.dict())
        assert errors == []

    def test_invalid_definition_id_flagged(self, api):
        node = WorkflowNode(id="x1", definition_id="nonexistent.type")
        wf = Workflow(name="Bad", nodes=[node], edges=[])
        errors = api.validate_workflow(wf.dict())
        assert len(errors) > 0
        assert any("nonexistent.type" in e for e in errors)

    def test_invalid_data_returns_error_string(self, api):
        errors = api.validate_workflow({"nodes": "bad", "edges": None})
        assert isinstance(errors, list)
        assert len(errors) > 0

    def test_empty_workflow_is_valid(self, api):
        wf = Workflow(name="Empty")
        errors = api.validate_workflow(wf.dict())
        assert errors == []


class TestExecuteWorkflow:
    def test_execute_returns_list(self, api, simple_workflow):
        results = api.execute_workflow(simple_workflow.dict())
        assert isinstance(results, list)

    def test_execute_results_have_required_fields(self, api, simple_workflow):
        results = api.execute_workflow(simple_workflow.dict())
        for r in results:
            assert "node_id" in r
            assert "status" in r

    def test_execute_invalid_workflow_returns_error(self, api):
        node = WorkflowNode(id="bad1", definition_id="missing.def")
        wf = Workflow(name="Bad", nodes=[node], edges=[])
        results = api.execute_workflow(wf.dict())
        assert len(results) > 0
        assert any(r["status"] == "error" for r in results)

    def test_execute_empty_workflow(self, api):
        wf = Workflow(name="Empty")
        results = api.execute_workflow(wf.dict())
        assert isinstance(results, list)


# ── Tests WorkflowEventServer ────────────────────────────────────────────────


class TestWorkflowEventServerInit:
    def test_default_port(self):
        server = WorkflowEventServer()
        assert server.port == 9724

    def test_custom_port(self):
        server = WorkflowEventServer(port=9999)
        assert server.port == 9999

    def test_not_running_initially(self):
        server = WorkflowEventServer()
        assert not server.is_running

    def test_no_clients_initially(self):
        server = WorkflowEventServer()
        assert server.client_count == 0


class TestWorkflowEventServerWithoutWebsockets:
    """Tests dégradés quand le module websockets est absent."""

    def test_start_returns_false_without_websockets(self):
        server = WorkflowEventServer()
        with patch("app.workflows.ws_server.HAS_WEBSOCKETS", False):
            result = asyncio.get_event_loop().run_until_complete(server.start())
        assert result is False

    def test_is_running_false_after_failed_start(self):
        server = WorkflowEventServer()
        with patch("app.workflows.ws_server.HAS_WEBSOCKETS", False):
            asyncio.get_event_loop().run_until_complete(server.start())
        assert not server.is_running


class TestWorkflowEventServerBroadcast:
    def test_broadcast_no_clients_returns_zero(self):
        server = WorkflowEventServer()
        result = asyncio.get_event_loop().run_until_complete(
            server.broadcast({"channel": "test", "data": {}})
        )
        assert result == 0

    def test_broadcast_removes_closed_clients(self):
        server = WorkflowEventServer()
        bad_client = MagicMock()
        bad_client.send = AsyncMock(side_effect=Exception("disconnected"))
        server._clients.add(bad_client)
        asyncio.get_event_loop().run_until_complete(
            server.broadcast({"channel": "test", "data": {}})
        )
        assert bad_client not in server._clients

    def test_broadcast_good_clients_counted(self):
        server = WorkflowEventServer()
        good_client = MagicMock()
        good_client.send = AsyncMock(return_value=None)
        server._clients.add(good_client)
        sent = asyncio.get_event_loop().run_until_complete(
            server.broadcast({"channel": "hello", "data": {"x": 1}})
        )
        assert sent == 1
        good_client.send.assert_called_once()
        payload = json.loads(good_client.send.call_args[0][0])
        assert payload["channel"] == "hello"


class TestWorkflowEventServerStop:
    def test_stop_when_not_running_is_safe(self):
        server = WorkflowEventServer()
        asyncio.get_event_loop().run_until_complete(server.stop())
        assert not server.is_running

    def test_stop_clears_clients(self):
        server = WorkflowEventServer()
        mock_client = MagicMock()
        mock_client.close = AsyncMock(return_value=None)
        server._clients.add(mock_client)
        asyncio.get_event_loop().run_until_complete(server.stop())
        assert server.client_count == 0


class TestWorkflowEventHandler:
    def test_on_event_broadcasts_channel_and_data(self):
        server = WorkflowEventServer()
        good_client = MagicMock()
        good_client.send = AsyncMock(return_value=None)
        server._clients.add(good_client)

        class FakeEvent:
            channel = "workflow_node_completed"
            data = {"node_id": "n1", "status": "success"}

        asyncio.get_event_loop().run_until_complete(server._on_event(FakeEvent()))
        good_client.send.assert_called_once()
        payload = json.loads(good_client.send.call_args[0][0])
        assert payload["channel"] == "workflow_node_completed"
        assert payload["data"]["node_id"] == "n1"

    def test_on_event_handles_missing_attributes(self):
        server = WorkflowEventServer()

        class BareEvent:
            pass

        # Should not raise
        asyncio.get_event_loop().run_until_complete(server._on_event(BareEvent()))


class TestAsyncLoop:
    def test_api_async_loop_starts(self, api):
        assert api._loop is not None
        assert api._loop.is_running()

    def test_shutdown_stops_loop(self, storage, registry):
        instance = WorkflowEditorAPI(storage=storage, registry=registry)
        assert instance._loop is not None
        instance.shutdown()
        time.sleep(0.05)
        assert instance._loop is None
