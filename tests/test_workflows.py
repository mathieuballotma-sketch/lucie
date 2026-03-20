"""
Tests complets pour app/workflows — schemas, registry, executor, storage.

Tous ces tests s'exécutent sans Ollama ni aucune dépendance réseau.
"""
import asyncio
import json
import time
import uuid

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
from app.workflows.executor import WorkflowExecutor, _safe_eval_condition
from app.workflows.storage import WorkflowStorage, _workflow_to_dict, _dict_to_workflow


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_node(node_type: str, node_id: str = "", config: dict = None) -> WorkflowNode:
    return WorkflowNode(
        id=node_id or str(uuid.uuid4()),
        node_type=node_type,
        config=config or {},
    )


def make_edge(src: str, src_port: str, tgt: str, tgt_port: str) -> WorkflowEdge:
    return WorkflowEdge(
        id=str(uuid.uuid4()),
        source_node=src,
        source_port=src_port,
        target_node=tgt,
        target_port=tgt_port,
    )


def simple_workflow() -> Workflow:
    """start → end"""
    start = make_node("control.start", "start")
    end = make_node("control.end", "end")
    edge = make_edge("start", "trigger", "end", "result")
    return Workflow(id="simple", name="Simple", nodes=[start, end], edges=[edge])


def make_executor(**kwargs) -> WorkflowExecutor:
    return WorkflowExecutor(registry=NodeRegistry(), **kwargs)


def run(coro):
    """Exécute une coroutine en contexte de test synchrone."""
    return asyncio.run(coro)


# ── Schemas ────────────────────────────────────────────────────────────────────

class TestSchemas:
    def test_port_defaults(self):
        p = Port(id="p1", name="Test", data_type="string", direction="input")
        assert p.required is True
        assert p.default is None

    def test_node_definition_defaults(self):
        nd = NodeDefinition(
            node_type="test.node", category="test",
            label="Test", description="desc",
        )
        assert nd.inputs == []
        assert nd.outputs == []
        assert nd.color == "#6366f1"
        assert nd.config_schema == {}

    def test_workflow_node_auto_id(self):
        n = WorkflowNode(node_type="control.start")
        assert n.id != ""
        assert n.position == {"x": 0, "y": 0}

    def test_workflow_edge_auto_id(self):
        e = WorkflowEdge(source_node="a", source_port="o", target_node="b", target_port="i")
        assert e.id != ""

    def test_workflow_defaults(self):
        w = Workflow(name="Test")
        assert w.version == "1.0"
        assert w.nodes == []
        assert w.edges == []
        assert w.created_at != ""
        assert w.updated_at != ""

    def test_execution_result_defaults(self):
        r = ExecutionResult(node_id="n1", status="success")
        assert r.outputs == {}
        assert r.error is None
        assert r.duration_ms == 0.0

    def test_workflow_serialization_roundtrip(self):
        w = Workflow(
            name="RT",
            nodes=[make_node("control.start", "s"), make_node("control.end", "e")],
            edges=[make_edge("s", "trigger", "e", "result")],
        )
        data = _workflow_to_dict(w)
        restored = _dict_to_workflow(data)
        assert restored.name == w.name
        assert restored.id == w.id
        assert len(restored.nodes) == 2
        assert len(restored.edges) == 1
        assert restored.edges[0].source_node == "s"
        assert restored.edges[0].target_node == "e"


# ── NodeRegistry ───────────────────────────────────────────────────────────────

class TestNodeRegistry:
    def test_builtins_control(self):
        reg = NodeRegistry()
        for t in ("control.start", "control.end", "control.condition",
                  "control.for_each", "control.wait"):
            assert reg.get(t) is not None, f"manquant: {t}"

    def test_builtins_llm(self):
        reg = NodeRegistry()
        nd = reg.get("llm.generate")
        assert nd is not None
        assert nd.category == "llm"
        input_ids = [p.id for p in nd.inputs]
        assert "prompt" in input_ids

    def test_builtins_data(self):
        reg = NodeRegistry()
        for t in ("data.read_file", "data.write_file", "data.variable"):
            assert reg.get(t) is not None, f"manquant: {t}"

    def test_register_custom(self):
        reg = NodeRegistry()
        nd = NodeDefinition(
            node_type="custom.xyz", category="custom",
            label="XYZ", description="Custom node",
        )
        reg.register(nd)
        assert reg.get("custom.xyz") is nd

    def test_overwrite_existing(self):
        reg = NodeRegistry()
        nd1 = NodeDefinition(node_type="test.dup", category="test", label="V1", description="")
        nd2 = NodeDefinition(node_type="test.dup", category="test", label="V2", description="")
        reg.register(nd1)
        reg.register(nd2)
        assert reg.get("test.dup").label == "V2"

    def test_get_unknown_returns_none(self):
        reg = NodeRegistry()
        assert reg.get("does.not.exist") is None

    def test_list_all_by_category(self):
        reg = NodeRegistry()
        all_nodes = reg.list_all()
        assert "control" in all_nodes
        assert "llm" in all_nodes
        assert "data" in all_nodes
        control_types = [nd.node_type for nd in all_nodes["control"]]
        assert "control.start" in control_types

    def test_auto_discover_agents_returns_int(self):
        reg = NodeRegistry()
        count = reg.auto_discover_agents()
        assert isinstance(count, int)
        assert count >= 0

    def test_auto_discover_agents_category(self):
        reg = NodeRegistry()
        count = reg.auto_discover_agents()
        if count > 0:
            all_nodes = reg.list_all()
            assert "agent" in all_nodes
            agent_types = [nd.node_type for nd in all_nodes["agent"]]
            assert all(t.startswith("agent.") for t in agent_types)


# ── _safe_eval_condition ───────────────────────────────────────────────────────

class TestSafeEvalCondition:
    def test_gt_true(self):
        assert _safe_eval_condition("value > 5", {"value": 10}) is True

    def test_gt_false(self):
        assert _safe_eval_condition("value > 5", {"value": 3}) is False

    def test_eq_string(self):
        assert _safe_eval_condition("value == 'hello'", {"value": "hello"}) is True

    def test_ne(self):
        assert _safe_eval_condition("value != 0", {"value": 1}) is True

    def test_empty_expression(self):
        # Empty → bool(context["value"])
        assert _safe_eval_condition("", {"value": True}) is True
        assert _safe_eval_condition("", {"value": False}) is False

    def test_invalid_expression_returns_false(self):
        assert _safe_eval_condition("totally invalid !!!", {}) is False

    def test_unsupported_op_returns_false(self):
        # 'in' operator not supported
        assert _safe_eval_condition("value in [1,2]", {"value": 1}) is False


# ── WorkflowExecutor.validate ──────────────────────────────────────────────────

class TestWorkflowValidation:
    def test_empty_workflow(self):
        errors = make_executor().validate(Workflow(name="Empty"))
        assert any("aucun nœud" in e for e in errors)

    def test_valid_simple(self):
        errors = make_executor().validate(simple_workflow())
        assert errors == []

    def test_orphan_node_error(self):
        start = make_node("control.start", "s")
        orphan = make_node("llm.generate", "orphan")
        end = make_node("control.end", "e")
        edge = make_edge("s", "trigger", "e", "result")
        w = Workflow(name="Orphan", nodes=[start, orphan, end], edges=[edge])
        errors = make_executor().validate(w)
        assert any("orphelin" in e for e in errors)

    def test_invalid_edge_source(self):
        end = make_node("control.end", "e")
        bad_edge = make_edge("nonexistent", "out", "e", "result")
        w = Workflow(name="BadSrc", nodes=[end], edges=[bad_edge])
        errors = make_executor().validate(w)
        assert any("introuvable" in e for e in errors)

    def test_invalid_edge_target(self):
        start = make_node("control.start", "s")
        bad_edge = make_edge("s", "trigger", "ghost", "in")
        w = Workflow(name="BadTgt", nodes=[start], edges=[bad_edge])
        errors = make_executor().validate(w)
        assert any("introuvable" in e for e in errors)

    def test_cycle_detection(self):
        a = make_node("data.variable", "a")
        b = make_node("data.variable", "b")
        e1 = make_edge("a", "value", "b", "value")
        e2 = make_edge("b", "value", "a", "value")
        w = Workflow(name="Cycle", nodes=[a, b], edges=[e1, e2])
        errors = make_executor().validate(w)
        assert any("cycle" in e.lower() for e in errors)

    def test_type_incompatible(self):
        reg = NodeRegistry()
        reg.register(NodeDefinition(
            node_type="t.num_out", category="test", label="NumOut", description="",
            outputs=[Port(id="out", name="Out", data_type="number", direction="output")],
        ))
        reg.register(NodeDefinition(
            node_type="t.str_in", category="test", label="StrIn", description="",
            inputs=[Port(id="in", name="In", data_type="string", direction="input")],
        ))
        ex = WorkflowExecutor(registry=reg)
        a = make_node("t.num_out", "a")
        b = make_node("t.str_in", "b")
        edge = make_edge("a", "out", "b", "in")
        w = Workflow(name="TypeIncompat", nodes=[a, b], edges=[edge])
        errors = ex.validate(w)
        assert any("incompatible" in e for e in errors)

    def test_any_type_compatible(self):
        """'any' est compatible avec tout."""
        reg = NodeRegistry()
        reg.register(NodeDefinition(
            node_type="t.any_out", category="test", label="AnyOut", description="",
            outputs=[Port(id="out", name="Out", data_type="any", direction="output")],
        ))
        reg.register(NodeDefinition(
            node_type="t.str_in2", category="test", label="StrIn2", description="",
            inputs=[Port(id="in", name="In", data_type="string", direction="input")],
        ))
        ex = WorkflowExecutor(registry=reg)
        a = make_node("t.any_out", "a")
        b = make_node("t.str_in2", "b")
        edge = make_edge("a", "out", "b", "in")
        w = Workflow(name="AnyCompat", nodes=[a, b], edges=[edge])
        errors = ex.validate(w)
        assert not any("incompatible" in e for e in errors)


# ── WorkflowExecutor.execute ───────────────────────────────────────────────────

class TestWorkflowExecution:
    def test_execute_simple(self):
        results = run(make_executor().execute(simple_workflow()))
        assert results["start"].status == "success"
        assert results["end"].status == "success"

    def test_execute_empty_returns_empty(self):
        results = run(make_executor().execute(Workflow(name="Empty")))
        assert results == {}

    def test_execute_parallel_independent_nodes(self):
        """Deux branches indépendantes depuis start s'exécutent toutes les deux."""
        start = make_node("control.start", "s")
        var_a = make_node("data.variable", "va", config={"value": "alpha"})
        var_b = make_node("data.variable", "vb", config={"value": "beta"})
        end = make_node("control.end", "end")
        edges = [
            make_edge("s", "trigger", "va", "value"),
            make_edge("s", "trigger", "vb", "value"),
            make_edge("va", "value", "end", "result"),
        ]
        w = Workflow(name="Parallel", nodes=[start, var_a, var_b, end], edges=edges)
        results = run(make_executor().execute(w))
        assert results["va"].status == "success"
        assert results["vb"].status == "success"

    def test_output_propagation(self):
        """La valeur d'un nœud est transmise au nœud suivant."""
        var = make_node("data.variable", "v", config={"value": "propagated"})
        end = make_node("control.end", "e")
        edge = make_edge("v", "value", "e", "result")
        w = Workflow(name="Prop", nodes=[var, end], edges=[edge])
        results = run(make_executor().execute(w))
        assert results["v"].status == "success"
        assert results["v"].outputs["value"] == "propagated"
        assert results["e"].outputs["result"] == "propagated"

    def test_execute_condition_branch_true(self):
        start = make_node("control.start", "s")
        cond = make_node("control.condition", "c", config={"expression": "value == True"})
        end = make_node("control.end", "e")
        edges = [
            make_edge("s", "trigger", "c", "value"),
            make_edge("c", "branch", "e", "result"),
        ]
        w = Workflow(name="CondTrue", nodes=[start, cond, end], edges=edges)
        results = run(make_executor().execute(w))
        assert results["c"].status == "success"
        assert results["c"].outputs["branch"] == "true"

    def test_execute_condition_branch_false(self):
        var = make_node("data.variable", "v", config={"value": 3})
        cond = make_node("control.condition", "c", config={"expression": "value > 10"})
        end = make_node("control.end", "e")
        edges = [
            make_edge("v", "value", "c", "value"),
            make_edge("c", "branch", "e", "result"),
        ]
        w = Workflow(name="CondFalse", nodes=[var, cond, end], edges=edges)
        results = run(make_executor().execute(w))
        assert results["c"].outputs["branch"] == "false"

    def test_execute_for_each(self):
        start = make_node("control.start", "s")
        fe = make_node("control.for_each", "fe")
        end = make_node("control.end", "e")
        edges = [
            make_edge("s", "trigger", "fe", "items"),
            make_edge("fe", "count", "e", "result"),
        ]
        w = Workflow(name="ForEach", nodes=[start, fe, end], edges=edges)
        results = run(make_executor().execute(w))
        assert results["fe"].status == "success"
        assert "count" in results["fe"].outputs
        # trigger=True → wrapped in list → count=1
        assert results["fe"].outputs["count"] == 1

    def test_execute_for_each_with_list(self):
        var = make_node("data.variable", "v", config={"value": [1, 2, 3]})
        fe = make_node("control.for_each", "fe")
        end = make_node("control.end", "e")
        edges = [
            make_edge("v", "value", "fe", "items"),
            make_edge("fe", "count", "e", "result"),
        ]
        w = Workflow(name="ForEachList", nodes=[var, fe, end], edges=edges)
        results = run(make_executor().execute(w))
        assert results["fe"].outputs["count"] == 3
        assert results["fe"].outputs["item"] == 1

    def test_execute_wait_node(self):
        start = make_node("control.start", "s")
        wait = make_node("control.wait", "w", config={"seconds": 0.05})
        end = make_node("control.end", "e")
        edges = [
            make_edge("s", "trigger", "w", "trigger"),
            make_edge("w", "done", "e", "result"),
        ]
        w = Workflow(name="Wait", nodes=[start, wait, end], edges=edges)
        t0 = time.monotonic()
        results = run(make_executor().execute(w))
        elapsed = time.monotonic() - t0
        assert results["w"].status == "success"
        assert elapsed >= 0.05

    def test_execute_llm_no_provider_returns_error(self):
        start = make_node("control.start", "s")
        llm = make_node("llm.generate", "l")
        end = make_node("control.end", "e")
        edges = [
            make_edge("s", "trigger", "l", "prompt"),
            make_edge("l", "text", "e", "result"),
        ]
        w = Workflow(name="LLMNoProvider", nodes=[start, llm, end], edges=edges)
        results = run(make_executor().execute(w))
        assert results["l"].status == "error"
        assert "Provider" in (results["l"].error or "")

    def test_execute_llm_with_mock_provider(self):
        class MockProvider:
            def generate(self, prompt, system=None, model=None,
                         temperature=None, max_tokens=None):
                return f"response:{prompt}"

        start = make_node("control.start", "s")
        llm = make_node("llm.generate", "l", config={"prompt": "hello"})
        end = make_node("control.end", "e")
        edges = [
            make_edge("s", "trigger", "l", "prompt"),
            make_edge("l", "text", "e", "result"),
        ]
        w = Workflow(name="LLMMock", nodes=[start, llm, end], edges=edges)
        results = run(make_executor(provider=MockProvider()).execute(w))
        assert results["l"].status == "success"
        assert results["l"].outputs["text"].startswith("response:")

    def test_node_error_does_not_block_independent_nodes(self):
        """Un nœud en erreur n'empêche pas les nœuds indépendants de s'exécuter."""
        start = make_node("control.start", "s")
        llm = make_node("llm.generate", "l")  # erreur: pas de provider
        var = make_node("data.variable", "v", config={"value": "ok"})
        end = make_node("control.end", "e")
        edges = [
            make_edge("s", "trigger", "l", "prompt"),
            make_edge("s", "trigger", "v", "value"),
            make_edge("v", "value", "e", "result"),
        ]
        w = Workflow(name="ErrorIsolation", nodes=[start, llm, var, end], edges=edges)
        results = run(make_executor().execute(w))
        assert results["l"].status == "error"
        assert results["v"].status == "success"
        assert results["e"].status == "success"

    def test_unknown_node_type_is_skipped(self):
        start = make_node("control.start", "s")
        unknown = make_node("unknown.xyz", "u")
        end = make_node("control.end", "e")
        edges = [
            make_edge("s", "trigger", "u", "in"),
            make_edge("u", "out", "e", "result"),
        ]
        w = Workflow(name="Unknown", nodes=[start, unknown, end], edges=edges)
        results = run(make_executor().execute(w))
        assert results["u"].status == "skipped"

    def test_duration_ms_recorded(self):
        results = run(make_executor().execute(simple_workflow()))
        for result in results.values():
            assert result.duration_ms >= 0.0

    def test_agent_not_found_returns_error(self):
        start = make_node("control.start", "s")
        agent_node = make_node("agent.file_agent", "a")
        end = make_node("control.end", "e")
        edges = [
            make_edge("s", "trigger", "a", "query"),
            make_edge("a", "response", "e", "result"),
        ]
        w = Workflow(name="AgentMissing", nodes=[start, agent_node, end], edges=edges)
        results = run(make_executor(agents={}).execute(w))
        assert results["a"].status == "error"

    def test_agent_mock_called(self):
        class MockAgent:
            async def handle(self, query: str) -> str:
                return f"handled:{query}"

        start = make_node("control.start", "s")
        agent_node = make_node("agent.mock_agent", "a")
        end = make_node("control.end", "e")
        edges = [
            make_edge("s", "trigger", "a", "query"),
            make_edge("a", "response", "e", "result"),
        ]
        w = Workflow(name="AgentMock", nodes=[start, agent_node, end], edges=edges)
        results = run(make_executor(agents={"mock_agent": MockAgent()}).execute(w))
        assert results["a"].status == "success"
        assert results["a"].outputs["response"].startswith("handled:")

    def test_read_file_not_found(self, tmp_path):
        # Path from config — file does not exist
        read = make_node("data.read_file", "r",
                         config={"path": str(tmp_path / "nope.txt")})
        end = make_node("control.end", "e")
        edge = make_edge("r", "content", "e", "result")
        w = Workflow(name="ReadMissing", nodes=[read, end], edges=[edge])
        results = run(make_executor().execute(w))
        assert results["r"].status == "error"

    def test_read_file_success(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("bonjour", encoding="utf-8")
        # Path comes from config — read is a root node (no incoming path edge)
        read = make_node("data.read_file", "r", config={"path": str(f)})
        end = make_node("control.end", "e")
        edge = make_edge("r", "content", "e", "result")
        w = Workflow(name="ReadOK", nodes=[read, end], edges=[edge])
        results = run(make_executor().execute(w))
        assert results["r"].status == "success"
        assert results["r"].outputs["content"] == "bonjour"

    def test_write_file_success(self, tmp_path):
        out = str(tmp_path / "out.txt")
        # Path and content come from config
        write = make_node("data.write_file", "w",
                          config={"path": out, "content": "coucou"})
        end = make_node("control.end", "e")
        edge = make_edge("w", "path", "e", "result")
        w = Workflow(name="WriteOK", nodes=[write, end], edges=[edge])
        results = run(make_executor().execute(w))
        assert results["w"].status == "success"
        assert (tmp_path / "out.txt").read_text() == "coucou"

    def test_data_variable_config_default(self):
        """Sans input, la variable retourne sa valeur de config."""
        var = make_node("data.variable", "v", config={"value": 99})
        end = make_node("control.end", "e")
        edge = make_edge("v", "value", "e", "result")
        w = Workflow(name="VarConfig", nodes=[var, end], edges=[edge])
        results = run(make_executor().execute(w))
        assert results["v"].outputs["value"] == 99


# ── WorkflowStorage ────────────────────────────────────────────────────────────

class TestWorkflowStorage:
    def test_save_and_load(self, tmp_path):
        storage = WorkflowStorage(db_path=str(tmp_path / "wf.db"))
        w = Workflow(name="Saved", description="Desc")
        storage.save(w)
        loaded = storage.load(w.id)
        assert loaded is not None
        assert loaded.name == "Saved"
        assert loaded.description == "Desc"
        assert loaded.id == w.id

    def test_load_nonexistent_returns_none(self, tmp_path):
        storage = WorkflowStorage(db_path=str(tmp_path / "wf.db"))
        assert storage.load("ghost-id") is None

    def test_list_all(self, tmp_path):
        storage = WorkflowStorage(db_path=str(tmp_path / "wf.db"))
        storage.save(Workflow(name="W1"))
        storage.save(Workflow(name="W2"))
        listing = storage.list_all()
        assert len(listing) == 2
        names = {r["name"] for r in listing}
        assert names == {"W1", "W2"}

    def test_delete(self, tmp_path):
        storage = WorkflowStorage(db_path=str(tmp_path / "wf.db"))
        w = Workflow(name="ToDelete")
        storage.save(w)
        assert storage.delete(w.id) is True
        assert storage.load(w.id) is None

    def test_delete_nonexistent_returns_false(self, tmp_path):
        storage = WorkflowStorage(db_path=str(tmp_path / "wf.db"))
        assert storage.delete("ghost") is False

    def test_update_workflow_no_duplicate(self, tmp_path):
        storage = WorkflowStorage(db_path=str(tmp_path / "wf.db"))
        w = Workflow(name="Original")
        storage.save(w)
        w.name = "Updated"
        storage.save(w)
        assert storage.load(w.id).name == "Updated"
        assert len(storage.list_all()) == 1

    def test_save_with_nodes_and_edges(self, tmp_path):
        storage = WorkflowStorage(db_path=str(tmp_path / "wf.db"))
        w = simple_workflow()
        storage.save(w)
        loaded = storage.load(w.id)
        assert loaded is not None
        assert len(loaded.nodes) == 2
        assert len(loaded.edges) == 1
        assert loaded.edges[0].source_node == "start"
        assert loaded.edges[0].target_node == "end"

    def test_export_json(self, tmp_path):
        storage = WorkflowStorage(db_path=str(tmp_path / "wf.db"))
        w = simple_workflow()
        storage.save(w)
        out_path = str(tmp_path / "export.json")
        assert storage.export_json(w.id, out_path) is True
        data = json.loads(open(out_path).read())
        assert data["name"] == w.name
        assert len(data["nodes"]) == 2

    def test_export_nonexistent_returns_false(self, tmp_path):
        storage = WorkflowStorage(db_path=str(tmp_path / "wf.db"))
        assert storage.export_json("ghost", str(tmp_path / "x.json")) is False

    def test_import_json(self, tmp_path):
        storage = WorkflowStorage(db_path=str(tmp_path / "wf.db"))
        w = simple_workflow()
        json_path = str(tmp_path / "import.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(_workflow_to_dict(w), f)

        imported = storage.import_json(json_path)
        assert imported is not None
        assert imported.name == w.name
        assert storage.load(imported.id) is not None

    def test_import_invalid_json_returns_none(self, tmp_path):
        storage = WorkflowStorage(db_path=str(tmp_path / "wf.db"))
        bad_path = str(tmp_path / "bad.json")
        with open(bad_path, "w") as f:
            f.write("NOT JSON {{{")
        assert storage.import_json(bad_path) is None

    def test_list_empty(self, tmp_path):
        storage = WorkflowStorage(db_path=str(tmp_path / "wf.db"))
        assert storage.list_all() == []


# ── Edge Cases ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_workflow_with_single_node(self):
        """Un workflow avec un seul nœud start (aucune edge) est valide."""
        start = make_node("control.start", "s")
        w = Workflow(name="Single", nodes=[start], edges=[])
        errors = make_executor().validate(w)
        assert errors == []

    def test_workflow_with_single_end_node(self):
        """Un workflow avec un seul nœud end (aucune edge) est valide."""
        end = make_node("control.end", "e")
        w = Workflow(name="EndOnly", nodes=[end], edges=[])
        errors = make_executor().validate(w)
        assert errors == []

    def test_execute_start_outputs_trigger(self):
        start = make_node("control.start", "s")
        w = Workflow(name="StartOnly", nodes=[start], edges=[])
        results = run(make_executor().execute(w))
        assert results["s"].status == "success"
        assert results["s"].outputs.get("trigger") is True

    def test_multiple_cycles_detected(self):
        a = make_node("data.variable", "a")
        b = make_node("data.variable", "b")
        c = make_node("data.variable", "c")
        edges = [
            make_edge("a", "value", "b", "value"),
            make_edge("b", "value", "c", "value"),
            make_edge("c", "value", "a", "value"),
        ]
        w = Workflow(name="LongCycle", nodes=[a, b, c], edges=edges)
        errors = make_executor().validate(w)
        assert any("cycle" in e.lower() for e in errors)

    def test_variable_node_without_config_or_input(self):
        """Variable sans config ni input retourne value=None."""
        var = make_node("data.variable", "v")
        end = make_node("control.end", "e")
        edge = make_edge("v", "value", "e", "result")
        w = Workflow(name="VarNull", nodes=[var, end], edges=[edge])
        results = run(make_executor().execute(w))
        assert results["v"].status == "success"
        assert results["v"].outputs["value"] is None

    def test_for_each_empty_list(self):
        var = make_node("data.variable", "v", config={"value": []})
        fe = make_node("control.for_each", "fe")
        end = make_node("control.end", "e")
        edges = [
            make_edge("v", "value", "fe", "items"),
            make_edge("fe", "count", "e", "result"),
        ]
        w = Workflow(name="ForEachEmpty", nodes=[var, fe, end], edges=edges)
        results = run(make_executor().execute(w))
        assert results["fe"].outputs["count"] == 0
        assert results["fe"].outputs["item"] is None
