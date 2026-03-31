"""
Tests unitaires pour LucieOrchestrator et ServiceRegistry — Phase 6.

Couverture:
    - Ordre topologique vérifié (Kahn's algorithm)
    - Détection de dépendance circulaire
    - Workflow macro EventBus : process_excel() → excel.macros_blocked
    - Workflow facturx : process_facturx() → facturx.accepted / facturx.rejected
    - Pression critique : événement memory.pressure_changed propagé
    - Startup / shutdown en ordre correct (services démarrés puis arrêtés inversement)
    - register_parser / register_loader par extension
    - process_file() routage par extension
    - request_llm() via BatchingOrchestrator ou EventBus fallback
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.services.orchestrator import (
    Capability,
    CyclicDependencyError,
    LucieOrchestrator,
    ServiceDescriptor,
    ServiceRegistry,
    create_lucie_orchestrator,
)


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


class MockEventBus:
    def __init__(self) -> None:
        self.published: List[Tuple[str, Any]] = []
        self.subscriptions: List[Tuple[str, Any]] = []

    async def publish(self, channel: str, data: Any, **kwargs: Any) -> None:
        self.published.append((channel, data))

    async def subscribe(self, channel: str, callback: Any, **kwargs: Any) -> None:
        self.subscriptions.append((channel, callback))

    def channels(self) -> List[str]:
        return [ch for ch, _ in self.published]

    def data_for(self, channel: str) -> List[Any]:
        return [d for ch, d in self.published if ch == channel]


class MockAuditTrail:
    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def record(self, action: str, **kwargs: Any) -> None:
        self.records.append({"action": action, **kwargs})


class MockService:
    """Service générique avec tracking de start/stop."""

    def __init__(self, name: str) -> None:
        self.name  = name
        self.calls: List[str] = []

    async def start(self) -> None:
        self.calls.append("start")

    async def stop(self) -> None:
        self.calls.append("stop")


class MockParser:
    """Parser stub : parse() retourne ParseResult configurable."""

    def __init__(self, *, has_critical: bool = False) -> None:
        self._has_critical = has_critical
        self._alerts       = []
        if has_critical:
            alert = MagicMock()
            alert.__str__ = lambda _: "CRITICAL: XXE detected"
            self._alerts.append(alert)

    def parse(self, pdf_bytes: bytes) -> Any:
        result = MagicMock()
        result.has_critical.return_value = self._has_critical
        result.alerts                    = self._alerts
        result.data                      = {}
        return result


class MockLoader:
    """Loader stub : load() retourne (rows, report) configurable."""

    def __init__(self, *, safe: bool = True) -> None:
        self._safe = safe

    def load(self, path: Any) -> Tuple[List[List[Any]], Any]:
        report = MagicMock()
        report.is_safe.return_value = self._safe
        report.threats              = [] if self._safe else ["macro detected"]
        return [[["col_a", "col_b"], ["val1", "val2"]]], report


# ---------------------------------------------------------------------------
# ServiceRegistry — topological sort
# ---------------------------------------------------------------------------


class TestServiceRegistry:

    def test_startup_order_single_node(self) -> None:
        reg = ServiceRegistry()
        reg.register(ServiceDescriptor("a", [Capability.AUDIT]))
        assert reg.startup_order() == ["a"]

    def test_startup_order_linear_chain(self) -> None:
        """a → b → c : l'ordre doit être [a, b, c]."""
        reg = ServiceRegistry()
        reg.register(ServiceDescriptor("a", [Capability.MEMORY]))
        reg.register(ServiceDescriptor("b", [Capability.BATCH],   dependencies=["a"]))
        reg.register(ServiceDescriptor("c", [Capability.PREDICT], dependencies=["b"]))
        order = reg.startup_order()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_startup_order_diamond(self) -> None:
        """
        Dépendances en diamant :
            a
           / \\
          b   c
           \\ /
            d
        a doit précéder b et c ; b et c doivent précéder d.
        """
        reg = ServiceRegistry()
        reg.register(ServiceDescriptor("a", [Capability.MEMORY]))
        reg.register(ServiceDescriptor("b", [Capability.BATCH],   dependencies=["a"]))
        reg.register(ServiceDescriptor("c", [Capability.PREDICT], dependencies=["a"]))
        reg.register(ServiceDescriptor("d", [Capability.SAGA],    dependencies=["b", "c"]))
        order = reg.startup_order()
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_cyclic_dependency_raises(self) -> None:
        """a → b → a doit lever CyclicDependencyError."""
        reg = ServiceRegistry()
        reg.register(ServiceDescriptor("a", [Capability.MEMORY], dependencies=["b"]))
        reg.register(ServiceDescriptor("b", [Capability.BATCH],  dependencies=["a"]))
        with pytest.raises(CyclicDependencyError):
            reg.startup_order()

    def test_self_dependency_raises(self) -> None:
        """a → a (auto-cycle) doit lever CyclicDependencyError."""
        reg = ServiceRegistry()
        reg.register(ServiceDescriptor("a", [Capability.AUDIT], dependencies=["a"]))
        with pytest.raises(CyclicDependencyError):
            reg.startup_order()

    def test_unknown_dependency_raises_value_error(self) -> None:
        """Dépendance vers un service inconnu → ValueError."""
        reg = ServiceRegistry()
        reg.register(ServiceDescriptor("a", [Capability.BATCH], dependencies=["missing"]))
        with pytest.raises(ValueError, match="unknown service 'missing'"):
            reg.startup_order()

    def test_empty_registry(self) -> None:
        reg = ServiceRegistry()
        assert reg.startup_order() == []

    def test_overwrite_logs_warning(self, caplog: Any) -> None:
        import logging
        reg = ServiceRegistry()
        reg.register(ServiceDescriptor("a", [Capability.AUDIT]))
        with caplog.at_level(logging.WARNING):
            reg.register(ServiceDescriptor("a", [Capability.MEMORY]))
        assert "already registered" in caplog.text.lower()


# ---------------------------------------------------------------------------
# LucieOrchestrator — lifecycle
# ---------------------------------------------------------------------------


class TestOrchestratorLifecycle:

    @pytest.mark.asyncio
    async def test_start_calls_services_in_order(self) -> None:
        """
        Les services doivent être démarrés dans l'ordre topologique.
        memory (aucune dep) → batch (dep: memory).
        """
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)

        call_order: List[str] = []

        svc_a = MagicMock()
        svc_a.start = AsyncMock(side_effect=lambda: call_order.append("memory"))
        svc_a.stop  = AsyncMock()

        svc_b = MagicMock()
        svc_b.start = AsyncMock(side_effect=lambda: call_order.append("batch"))
        svc_b.stop  = AsyncMock()

        orch.register_service(ServiceDescriptor("memory", [Capability.MEMORY], instance=svc_a))
        orch.register_service(ServiceDescriptor("batch",  [Capability.BATCH],  dependencies=["memory"], instance=svc_b))

        await orch.start()
        assert call_order.index("memory") < call_order.index("batch")
        await orch.stop()

    @pytest.mark.asyncio
    async def test_stop_calls_services_in_reverse_order(self) -> None:
        """Les services doivent être arrêtés dans l'ordre inverse de démarrage."""
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)

        stop_order: List[str] = []

        svc_a = MagicMock()
        svc_a.start = AsyncMock()
        svc_a.stop  = AsyncMock(side_effect=lambda: stop_order.append("memory"))

        svc_b = MagicMock()
        svc_b.start = AsyncMock()
        svc_b.stop  = AsyncMock(side_effect=lambda: stop_order.append("batch"))

        orch.register_service(ServiceDescriptor("memory", [Capability.MEMORY], instance=svc_a))
        orch.register_service(ServiceDescriptor("batch",  [Capability.BATCH],  dependencies=["memory"], instance=svc_b))

        await orch.start()
        await orch.stop()

        assert stop_order.index("batch") < stop_order.index("memory"), (
            "batch must stop before memory (reverse topological order)"
        )

    @pytest.mark.asyncio
    async def test_duplicate_start_is_idempotent(self) -> None:
        """Un double start() ne doit pas relancer les services."""
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)

        svc = MagicMock()
        svc.start = AsyncMock()
        svc.stop  = AsyncMock()
        orch.register_service(ServiceDescriptor("a", [Capability.AUDIT], instance=svc))

        await orch.start()
        await orch.start()   # second call — must be no-op

        assert svc.start.call_count == 1

        await orch.stop()

    @pytest.mark.asyncio
    async def test_stop_timeout_does_not_propagate(self) -> None:
        """Un service qui dépasse le timeout de stop ne doit pas bloquer les autres."""
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit, stop_timeout=0.05)

        slow_svc = MagicMock()
        slow_svc.start = AsyncMock()
        slow_svc.stop  = AsyncMock(side_effect=lambda: asyncio.sleep(10))  # Too slow

        orch.register_service(ServiceDescriptor("slow", [Capability.AUDIT], instance=slow_svc))

        await orch.start()
        # Should not raise despite the timeout
        await orch.stop()

    @pytest.mark.asyncio
    async def test_cyclic_dependency_prevents_start(self) -> None:
        """start() doit lever CyclicDependencyError si le graphe contient un cycle."""
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)

        orch.register_service(ServiceDescriptor("a", [Capability.MEMORY], dependencies=["b"]))
        orch.register_service(ServiceDescriptor("b", [Capability.BATCH],  dependencies=["a"]))

        with pytest.raises(CyclicDependencyError):
            await orch.start()

    @pytest.mark.asyncio
    async def test_auto_audit_subscribes_to_critical_channels(self) -> None:
        """start() doit abonner l'orchestrateur à tous les canaux critiques."""
        from app.services.orchestrator import _CRITICAL_CHANNELS

        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)

        await orch.start()

        subscribed_channels = [ch for ch, _ in bus.subscriptions]
        for channel in _CRITICAL_CHANNELS:
            assert channel in subscribed_channels, (
                f"Expected subscription on '{channel}', got: {subscribed_channels}"
            )

        await orch.stop()


# ---------------------------------------------------------------------------
# LucieOrchestrator — API façade EventBus
# ---------------------------------------------------------------------------


class TestOrchestratorFacade:

    @pytest.mark.asyncio
    async def test_process_facturx_rejected_publishes_event(self) -> None:
        """Un fichier dangereux publie 'facturx.rejected' sur le bus."""
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)
        orch.register_parser(".pdf", MockParser(has_critical=True))

        result = await orch.process_facturx(b"fake-pdf-bytes")

        assert result["safe"] is False
        assert "facturx.rejected" in bus.channels()

    @pytest.mark.asyncio
    async def test_process_facturx_accepted_publishes_event(self) -> None:
        """Un fichier sain publie 'facturx.accepted' sur le bus."""
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)
        orch.register_parser(".pdf", MockParser(has_critical=False))

        result = await orch.process_facturx(b"valid-facturx-bytes")

        assert result["safe"] is True
        assert "facturx.accepted" in bus.channels()

    @pytest.mark.asyncio
    async def test_process_facturx_includes_input_hash(self) -> None:
        """Le résultat de process_facturx() inclut le hash SHA-256 de l'entrée."""
        import hashlib

        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)
        orch.register_parser(".pdf", MockParser(has_critical=False))

        pdf_bytes = b"test-document-content"
        result    = await orch.process_facturx(pdf_bytes)

        assert result["input_hash"] == hashlib.sha256(pdf_bytes).hexdigest()

    @pytest.mark.asyncio
    async def test_process_excel_safe_publishes_accepted(self, tmp_path: Any) -> None:
        """Un Excel sain publie 'excel.accepted'."""
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)
        orch.register_loader(".xlsx", MockLoader(safe=True))

        xlsx_file = tmp_path / "test.xlsx"
        xlsx_file.write_bytes(b"fake-xlsx")

        result = await orch.process_excel(xlsx_file)

        assert result["safe"] is True
        assert "excel.accepted" in bus.channels()

    @pytest.mark.asyncio
    async def test_process_excel_macro_publishes_blocked(self, tmp_path: Any) -> None:
        """Un Excel avec macros publie 'excel.macros_blocked'."""
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)
        orch.register_loader(".xlsx", MockLoader(safe=False))
        orch.register_loader(".xlsm", MockLoader(safe=False))

        xlsm_file = tmp_path / "macro.xlsm"
        xlsm_file.write_bytes(b"fake-xlsm")

        result = await orch.process_excel(xlsm_file)

        assert result["safe"] is False
        assert "excel.macros_blocked" in bus.channels()

    @pytest.mark.asyncio
    async def test_process_file_routes_pdf(self, tmp_path: Any) -> None:
        """process_file() délègue les .pdf à process_facturx()."""
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)
        orch.register_parser(".pdf", MockParser(has_critical=False))

        pdf_file = tmp_path / "invoice.pdf"
        pdf_file.write_bytes(b"minimal-pdf-content")

        result = await orch.process_file(pdf_file)

        assert "facturx.accepted" in bus.channels() or "facturx.rejected" in bus.channels()
        assert "input_hash" in result

    @pytest.mark.asyncio
    async def test_process_file_routes_xlsx(self, tmp_path: Any) -> None:
        """process_file() délègue les .xlsx à process_excel()."""
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)
        orch.register_loader(".xlsx", MockLoader(safe=True))

        xlsx_file = tmp_path / "data.xlsx"
        xlsx_file.write_bytes(b"fake-xlsx")

        result = await orch.process_file(xlsx_file)

        assert result["safe"] is True

    @pytest.mark.asyncio
    async def test_process_file_unsupported_extension_raises(self, tmp_path: Any) -> None:
        """process_file() lève ValueError pour une extension non supportée."""
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)

        unknown_file = tmp_path / "data.parquet"
        unknown_file.write_bytes(b"fake-parquet")

        with pytest.raises(ValueError, match="Unsupported file extension"):
            await orch.process_file(unknown_file)

    @pytest.mark.asyncio
    async def test_process_facturx_no_parser_raises(self) -> None:
        """process_facturx() sans parser enregistré lève ValueError."""
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)

        with pytest.raises(ValueError, match="No PDF parser registered"):
            await orch.process_facturx(b"pdf-bytes")

    @pytest.mark.asyncio
    async def test_request_llm_via_eventbus_fallback(self) -> None:
        """
        Sans BatchingOrchestrator, request_llm() publie 'llm.request'
        sur le bus (chemin EventBus fallback).
        """
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)

        result = await orch.request_llm("mistral:7b", "Résume ce texte.")

        assert "llm.request" in bus.channels()
        payload = bus.data_for("llm.request")[0]
        assert payload["model"]  == "mistral:7b"
        assert payload["prompt"] == "Résume ce texte."
        assert result == ""   # Fallback retourne chaîne vide


# ---------------------------------------------------------------------------
# LucieOrchestrator — pression mémoire critique
# ---------------------------------------------------------------------------


class TestMemoryPressurePropagation:

    @pytest.mark.asyncio
    async def test_memory_pressure_event_subscribed(self) -> None:
        """
        Après start(), l'orchestrateur est abonné au canal 'memory.pressure_changed'.
        Simuler la publication de cet événement doit déclencher le callback d'audit.
        """
        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)

        await orch.start()

        # Vérifier l'abonnement
        subscribed = [ch for ch, _ in bus.subscriptions]
        assert "memory.pressure_changed" in subscribed

        # Simuler l'invocation du callback auto-audit
        event = MagicMock()
        event.channel = "memory.pressure_changed"
        event.source  = "memory_guardian"
        event.data    = {"pressure": "CRITICAL", "free_gb": 0.5}

        # Trouver et appeler le callback de l'orchestrateur
        callbacks = [cb for ch, cb in bus.subscriptions if ch == "memory.pressure_changed"]
        assert callbacks, "No callback found for memory.pressure_changed"

        await callbacks[0](event)

        # L'AuditTrail doit avoir reçu un enregistrement
        assert audit.records, "AuditTrail should have received a record"
        assert audit.records[0]["action"] == "memory.pressure_changed"

        await orch.stop()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestCreateLucieOrchestrator:

    @pytest.mark.asyncio
    async def test_factory_without_optional_services(self) -> None:
        """create_lucie_orchestrator() fonctionne sans services optionnels."""
        bus   = MockEventBus()
        audit = MockAuditTrail()

        orch = await create_lucie_orchestrator(bus, audit)
        assert isinstance(orch, LucieOrchestrator)

    @pytest.mark.asyncio
    async def test_factory_registers_batching_after_memory(self) -> None:
        """Si memory et batching sont fournis, batch dépend de memory (ordre correct)."""
        bus   = MockEventBus()
        audit = MockAuditTrail()

        memory_svc  = MagicMock(); memory_svc.start = AsyncMock(); memory_svc.stop = AsyncMock()
        batching_svc = MagicMock(); batching_svc.start = AsyncMock(); batching_svc.stop = AsyncMock()

        orch = await create_lucie_orchestrator(
            bus, audit,
            batching=batching_svc,
            memory_guardian=memory_svc,
        )

        order = orch._registry.startup_order()
        assert order.index("memory") < order.index("batching")
