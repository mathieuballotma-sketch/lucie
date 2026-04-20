"""
Tests d'isolation — AW-1 Foundations.

Valide que les 4 composants salvagés sont importables et fonctionnels
en isolation totale, sans dépendance au pipeline de production.

Run : pytest lucie_v1_standalone/tests/test_aw1_foundations.py -v
Temps attendu : < 2 s
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict

import pytest


# ── A. quantum_models ────────────────────────────────────────────────

def test_import_quantum_models() -> None:
    from lucie_v1_standalone.aw1.quantum_models import (
        CollapseResult,
        FusionStrategy,
        PathState,
        PathWeight,
        QuantumState,
    )
    assert PathWeight and QuantumState and CollapseResult
    assert FusionStrategy and PathState


def test_quantum_models_instanciation() -> None:
    from lucie_v1_standalone.aw1.quantum_models import (
        CollapseResult,
        FusionStrategy,
        PathState,
        PathWeight,
        QuantumState,
    )
    pw = PathWeight(agent="LecteurAgent", weight=0.8)
    assert pw.agent == "LecteurAgent"
    assert pw.weight == 0.8
    assert pw.state == PathState.PENDING
    assert not pw.is_terminal
    assert pw.effective_score == 0.0  # pas encore COMPLETED

    qs = QuantumState(query="test")
    qs.paths.append(pw)
    qs.normalize_weights()
    assert qs.paths[0].weight == pytest.approx(1.0)
    assert not qs.is_collapsed  # chemin pas terminal

    cr = CollapseResult(
        quantum_id="abc",
        query="test",
        selected_agent="LecteurAgent",
        result="réponse",
        confidence=0.9,
        strategy_used=FusionStrategy.FIRST_WINNER,
        total_latency_ms=42.0,
        paths_explored=1,
        paths_completed=1,
        paths_cancelled=0,
        fusion_detail="LecteurAgent gagnant (conf=0.9)",
    )
    audit = cr.to_audit_dict()
    assert audit["strategy"] == "first_winner"
    assert audit["fusion_detail"] == "LecteurAgent gagnant (conf=0.9)"


# ── B. waterflow ──────────────────────────────────────────────────────

def test_import_waterflow() -> None:
    from lucie_v1_standalone.aw1.waterflow import WaterDrop, WaterFlow, WaterGrain
    assert WaterFlow and WaterDrop and WaterGrain


def test_waterflow_pipeline_3grains_2stages() -> None:
    """
    3 grains répartis sur 2 stages :
      stage 0 : grain_a (×2) et grain_b (×3) en parallèle
      stage 1 : grain_c (str) séquentiel

    Vérifie que le drop est enrichi dans l'ordre attendu.
    """
    from lucie_v1_standalone.aw1.waterflow import WaterDrop, WaterFlow

    execution_order: list[str] = []

    def grain_a(drop: WaterDrop) -> Dict[str, Any]:
        execution_order.append("grain_a")
        return {"value_a": drop.context.get("init", 0) * 2}

    def grain_b(drop: WaterDrop) -> Dict[str, Any]:
        execution_order.append("grain_b")
        return {"value_b": drop.context.get("init", 0) * 3}

    def grain_c(drop: WaterDrop) -> str:
        execution_order.append("grain_c")
        return f"final:{drop.context.get('value_a', 0)}+{drop.context.get('value_b', 0)}"

    flow = (
        WaterFlow()
        .add_grain("grain_a", grain_a, stage=0)
        .add_grain("grain_b", grain_b, stage=0)
        .add_grain("grain_c", grain_c, stage=1)
    )

    assert flow.grain_count == 3

    drop = asyncio.run(flow.run("test", initial_context={"init": 5}))

    # grain_c doit s'exécuter APRÈS grain_a et grain_b
    assert execution_order.index("grain_c") > execution_order.index("grain_a")
    assert execution_order.index("grain_c") > execution_order.index("grain_b")

    # Les enrichissements de stage 0 sont disponibles pour stage 1
    assert drop.context.get("value_a") == 10  # 5 × 2
    assert drop.context.get("value_b") == 15  # 5 × 3
    assert drop.final_response == "final:10+15"
    assert drop.enrichment_count == 3
    assert drop.errors == []


# ── C. NodeRegistry + schemas ─────────────────────────────────────────

def test_import_node_registry() -> None:
    from lucie_v1_standalone.aw1.node_registry import NodeRegistry
    from lucie_v1_standalone.aw1.schemas import NodeDefinition, Port
    assert NodeRegistry and NodeDefinition and Port


def test_node_registry_thread_safe() -> None:
    """
    Enregistre 3 handlers depuis 2 threads simultanés.
    Vérifie que tous sont accessibles et que le singleton est préservé.
    """
    from lucie_v1_standalone.aw1.node_registry import NodeRegistry

    NodeRegistry.reset_singleton()
    registry = NodeRegistry()
    registry.clear()

    errors: list[str] = []

    def register_from_thread(names: list[str]) -> None:
        r = NodeRegistry()  # doit retourner le même singleton
        for n in names:
            try:
                r.register_manually(n, category="test")
            except Exception as exc:
                errors.append(str(exc))

    t1 = threading.Thread(target=register_from_thread, args=(["node_alpha", "node_beta"],))
    t2 = threading.Thread(target=register_from_thread, args=(["node_gamma"],))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == [], f"Erreurs thread : {errors}"

    all_ids = {d.id for d in registry.list_all()}
    assert "node_alpha" in all_ids
    assert "node_beta" in all_ids
    assert "node_gamma" in all_ids

    # Singleton : les deux threads ont opéré sur le même objet
    assert NodeRegistry() is registry


# ── D. Plasticity Protocol ────────────────────────────────────────────

def test_import_plasticity() -> None:
    from lucie_v1_standalone.aw1.plasticity import Plasticity
    assert Plasticity


def test_plasticity_protocol_isinstance() -> None:
    """
    Implémentation minimale conforme au Protocol.
    Vérifie isinstance() grâce à @runtime_checkable.
    """
    from lucie_v1_standalone.aw1.plasticity import Plasticity

    class MinimalPlasticity:
        def __init__(self) -> None:
            self._links: Dict[str, float] = {}

        def strengthen(self, link_id: str, delta: float = 0.1) -> None:
            self._links[link_id] = self._links.get(link_id, 0.0) + delta

        def weaken(self, link_id: str, delta: float = 0.1) -> None:
            self._links[link_id] = max(0.0, self._links.get(link_id, 0.0) - delta)

        def prune(self, threshold: float) -> int:
            before = len(self._links)
            self._links = {k: v for k, v in self._links.items() if v >= threshold}
            return before - len(self._links)

        def snapshot(self) -> Dict[str, Any]:
            return dict(self._links)

    impl = MinimalPlasticity()
    assert isinstance(impl, Plasticity)

    impl.strengthen("concept_a", 0.3)
    impl.strengthen("concept_a", 0.2)
    impl.strengthen("concept_b", 0.05)

    snap = impl.snapshot()
    assert snap["concept_a"] == pytest.approx(0.5)
    assert snap["concept_b"] == pytest.approx(0.05)

    pruned = impl.prune(threshold=0.1)
    assert pruned == 1  # concept_b élaguée
    assert "concept_b" not in impl.snapshot()
    assert "concept_a" in impl.snapshot()
