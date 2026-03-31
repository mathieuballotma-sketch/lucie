"""
LucieOrchestrator — façade unifiée de l'écosystème Lucie.

Architecture:
    ServiceRegistry   : inventaire des services + tri topologique (Kahn's algorithm)
    LucieOrchestrator : démarre/arrête les services en ordre, route les fichiers,
                        abonne automatiquement l'AuditTrail aux canaux critiques,
                        expose une API façade 100 % EventBus.

Composants:
    Capability            — enum des capacités déclarées par un service
    ServiceDescriptor     — description d'un service (nom, capacités, dépendances)
    ServiceRegistry       — registre avec détection de cycles + tri topologique
    CyclicDependencyError — levée si un cycle est détecté
    LucieOrchestrator     — orchestrateur principal
    create_lucie_orchestrator() — factory prête-à-l'emploi

Usage:
    orchestrator = await create_lucie_orchestrator(event_bus, audit_trail)
    await orchestrator.start()
    result = await orchestrator.process_facturx(pdf_bytes)
    await orchestrator.stop()
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Capability & ServiceDescriptor
# ---------------------------------------------------------------------------


class Capability(Enum):
    PARSE_XML     = auto()
    PARSE_EXCEL   = auto()
    LOAD_EXCEL    = auto()
    LLM_INFERENCE = auto()
    AUDIT         = auto()
    MEMORY        = auto()
    BATCH         = auto()
    PREDICT       = auto()
    SAGA          = auto()


@dataclass
class ServiceDescriptor:
    name: str
    capabilities: List[Capability]
    dependencies: List[str] = field(default_factory=list)
    instance: Any = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# ServiceRegistry — Kahn's topological sort
# ---------------------------------------------------------------------------


class CyclicDependencyError(Exception):
    """Raised when a circular dependency is detected in the service graph."""


class ServiceRegistry:
    """
    Registre de services avec tri topologique par l'algorithme de Kahn.

    Usage:
        reg = ServiceRegistry()
        reg.register(ServiceDescriptor("memory", [Capability.MEMORY]))
        reg.register(ServiceDescriptor("batch",  [Capability.BATCH], dependencies=["memory"]))
        order = reg.startup_order()   # ["memory", "batch"]
    """

    def __init__(self) -> None:
        self._descriptors: Dict[str, ServiceDescriptor] = {}

    def register(self, descriptor: ServiceDescriptor) -> None:
        if descriptor.name in self._descriptors:
            logger.warning("Service '%s' already registered — overwriting", descriptor.name)
        self._descriptors[descriptor.name] = descriptor

    def get(self, name: str) -> Optional[ServiceDescriptor]:
        return self._descriptors.get(name)

    def all_names(self) -> List[str]:
        return list(self._descriptors.keys())

    def startup_order(self) -> List[str]:
        """
        Returns service names in dependency-first order using Kahn's algorithm.

        Raises:
            ValueError:            if a dependency references an unknown service.
            CyclicDependencyError: if a cycle is detected.
        """
        in_degree: Dict[str, int] = {name: 0 for name in self._descriptors}
        adj: Dict[str, List[str]] = defaultdict(list)

        for name, desc in self._descriptors.items():
            for dep in desc.dependencies:
                if dep not in self._descriptors:
                    raise ValueError(
                        f"Service '{name}' depends on unknown service '{dep}'"
                    )
                adj[dep].append(name)
                in_degree[name] += 1

        # Queue: all nodes with in-degree 0
        queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
        order: List[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self._descriptors):
            cycle_nodes = [n for n, d in in_degree.items() if d > 0]
            raise CyclicDependencyError(
                f"Circular dependency detected among services: {sorted(cycle_nodes)}"
            )

        return order


# ---------------------------------------------------------------------------
# Critical channels for auto-audit
# ---------------------------------------------------------------------------

_CRITICAL_CHANNELS: List[str] = [
    "security.alert",
    "security.threat",
    "invoice.approved",
    "invoice.rejected",
    "audit.action",
    "excel.macros_blocked",
    "excel.threat_detected",
    "excel.accepted",
    "facturx.rejected",
    "facturx.accepted",
    "memory.pressure_changed",
    "llm.request",
    "llm.response",
    "resilience.circuit_open",
    "resilience.metrics",
]


# ---------------------------------------------------------------------------
# LucieOrchestrator
# ---------------------------------------------------------------------------


class LucieOrchestrator:
    """
    Point d'entrée unique de l'écosystème Lucie.

    Responsabilités:
    - Démarrage ordonné des services (ordre topologique) et arrêt inversé.
    - Enregistrement des parsers/loaders par extension de fichier.
    - Abonnement automatique de l'AuditTrail à tous les canaux critiques.
    - API façade (process_excel, process_facturx, process_file, request_llm)
      communiquant exclusivement via EventBus.
    """

    def __init__(
        self,
        event_bus: Any,
        audit_trail: Any,
        *,
        stop_timeout: float = 10.0,
    ) -> None:
        self._bus = event_bus
        self._audit = audit_trail
        self._stop_timeout = stop_timeout

        self._registry = ServiceRegistry()
        self._parsers: Dict[str, Any] = {}   # ext → FacturXSecureParser-like
        self._loaders: Dict[str, Any] = {}   # ext → ExcelSecureLoader-like

        self._started = False
        self._startup_order: List[str] = []

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    def register_service(self, descriptor: ServiceDescriptor) -> None:
        """Register a service descriptor into the registry."""
        self._registry.register(descriptor)

    def register_parser(self, ext: str, parser: Any) -> None:
        """Register a file parser for a given extension (e.g. '.pdf')."""
        self._parsers[ext.lower()] = parser
        logger.info("Parser registered for extension '%s'", ext)

    def register_loader(self, ext: str, loader: Any) -> None:
        """Register a file loader for a given extension (e.g. '.xlsx')."""
        self._loaders[ext.lower()] = loader
        logger.info("Loader registered for extension '%s'", ext)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Start all registered services in topological dependency order,
        then subscribe the AuditTrail to all critical channels.

        Raises CyclicDependencyError if the service graph has cycles.
        """
        if self._started:
            logger.warning("Orchestrator already started — ignoring duplicate start()")
            return

        self._startup_order = self._registry.startup_order()
        logger.info("Service startup order: %s", self._startup_order)

        for name in self._startup_order:
            desc = self._registry.get(name)
            if desc and desc.instance and hasattr(desc.instance, "start"):
                logger.info("Starting service '%s'", name)
                await desc.instance.start()

        await self._audit.start()
        await self._subscribe_audit_channels()

        self._started = True
        logger.info(
            "LucieOrchestrator started — %d service(s), %d audit channel(s)",
            len(self._startup_order),
            len(_CRITICAL_CHANNELS),
        )

    async def stop(self) -> None:
        """
        Stop all services in reverse topological order.
        Each service gets at most `stop_timeout` seconds before being abandoned.
        """
        if not self._started:
            return

        await self._audit.stop()

        for name in reversed(self._startup_order):
            desc = self._registry.get(name)
            if desc and desc.instance and hasattr(desc.instance, "stop"):
                logger.info("Stopping service '%s'", name)
                try:
                    await asyncio.wait_for(
                        desc.instance.stop(), timeout=self._stop_timeout
                    )
                except asyncio.TimeoutError:
                    logger.error(
                        "Service '%s' did not stop within %.1fs — abandoned",
                        name,
                        self._stop_timeout,
                    )
                except Exception as exc:
                    logger.error("Service '%s' stop() raised: %s", name, exc)

        self._started = False
        logger.info("LucieOrchestrator stopped")

    # ------------------------------------------------------------------
    # Auto-audit subscription
    # ------------------------------------------------------------------

    async def _subscribe_audit_channels(self) -> None:
        """Subscribe the orchestrator's audit callback to every critical channel."""
        for channel in _CRITICAL_CHANNELS:
            try:
                await self._bus.subscribe(
                    channel=channel,
                    callback=self._on_critical_event,
                    source="lucie.orchestrator",
                    token=None,
                )
                logger.debug("Auto-audit subscribed to channel '%s'", channel)
            except Exception as exc:
                logger.warning(
                    "Could not subscribe to critical channel '%s': %s", channel, exc
                )

    async def _on_critical_event(self, event: Any) -> None:
        """Forward any critical EventBus event to the AuditTrail automatically."""
        try:
            channel = getattr(event, "channel", "unknown")
            source  = getattr(event, "source",  "system")
            data    = getattr(event, "data",    {}) or {}
            await self._audit.record(
                action=channel,
                user=source,
                justification="auto-audit via LucieOrchestrator",
                data=dict(data) if isinstance(data, dict) else {"payload": str(data)},
            )
        except Exception as exc:
            logger.error("_on_critical_event failed: %s", exc)

    # ------------------------------------------------------------------
    # API façade — 100 % EventBus
    # ------------------------------------------------------------------

    async def process_excel(self, path: str | Path) -> Dict[str, Any]:
        """
        Load and security-scan an Excel file via the registered loader.

        Publishes 'excel.accepted' or 'excel.macros_blocked' on the EventBus.
        Returns a dict summarising the result.
        """
        path = Path(path)
        ext  = path.suffix.lower()
        loader = self._loaders.get(ext) or self._loaders.get(".xlsx")
        if loader is None:
            raise ValueError(f"No loader registered for extension '{ext}'")

        loop = asyncio.get_event_loop()
        rows, report = await loop.run_in_executor(None, loader.load, path)

        is_safe = report.is_safe() if hasattr(report, "is_safe") else True
        threats = []
        if hasattr(report, "threats"):
            threats = [str(t) for t in (report.threats or [])]

        result: Dict[str, Any] = {
            "path":    str(path),
            "rows":    len(rows),
            "safe":    is_safe,
            "threats": threats,
        }

        channel = "excel.accepted" if is_safe else "excel.macros_blocked"
        await self._bus.publish(channel, result, source="lucie.orchestrator", token=None)
        return result

    async def process_facturx(self, pdf_bytes: bytes) -> Dict[str, Any]:
        """
        Parse and security-scan a Factur-X PDF via the registered parser.

        Publishes 'facturx.accepted' or 'facturx.rejected' on the EventBus.
        Returns a dict with safe flag, alerts, extracted data, and input hash.
        """
        parser = self._parsers.get(".pdf")
        if parser is None:
            raise ValueError("No PDF parser registered — call register_parser('.pdf', ...)")

        loop = asyncio.get_event_loop()
        try:
            result_obj = await loop.run_in_executor(None, parser.parse, pdf_bytes)
        except Exception as exc:
            logger.error("FacturXSecureParser raised: %s", exc)
            result_obj = None

        if result_obj is None:
            has_critical = True
            alerts_str   = ["Parser error — could not process document"]
            data         = {}
        else:
            has_critical = (
                result_obj.has_critical()
                if hasattr(result_obj, "has_critical")
                else bool(getattr(result_obj, "alerts", []))
            )
            alerts_str = [str(a) for a in getattr(result_obj, "alerts", [])]
            data       = getattr(result_obj, "data", {}) or {}

        input_hash = hashlib.sha256(pdf_bytes).hexdigest()
        result: Dict[str, Any] = {
            "safe":       not has_critical,
            "alerts":     alerts_str,
            "data":       data,
            "input_hash": input_hash,
        }

        channel = "facturx.rejected" if has_critical else "facturx.accepted"
        await self._bus.publish(channel, result, source="lucie.orchestrator", token=None)
        return result

    async def process_file(self, path: str | Path) -> Dict[str, Any]:
        """
        Route a file to the appropriate handler based on its extension.

        .pdf           → process_facturx()
        .xlsx/.xls/... → process_excel()
        Other parsers  → process_facturx() (byte-level parsing)

        Raises ValueError for unsupported extensions.
        """
        path = Path(path)
        ext  = path.suffix.lower()

        if ext == ".pdf" or ext in self._parsers:
            pdf_bytes = await asyncio.get_event_loop().run_in_executor(
                None, path.read_bytes
            )
            return await self.process_facturx(pdf_bytes)

        if ext in (".xlsx", ".xls", ".xlsm", ".xlsb", ".csv") or ext in self._loaders:
            return await self.process_excel(path)

        raise ValueError(f"Unsupported file extension: '{ext}'")

    async def request_llm(
        self,
        model: str,
        prompt: str,
        *,
        priority: Any = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Submit an LLM inference request via the BatchingOrchestrator (if registered)
        or via a raw EventBus publication.

        Returns the generated text (empty string if EventBus-only path).
        """
        batching_desc = self._registry.get("batching")
        if batching_desc and batching_desc.instance:
            batching = batching_desc.instance
            try:
                from app.services.batching import LLMRequest, RequestPriority

                kwargs: Dict[str, Any] = {}
                if system_prompt is not None:
                    kwargs["system_prompt"] = system_prompt
                if temperature is not None:
                    kwargs["temperature"] = temperature
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens

                req = LLMRequest(
                    model=model,
                    prompt=prompt,
                    priority=priority or RequestPriority.NORMAL,
                    **kwargs,
                )
                return await batching.submit(req)
            except ImportError:
                logger.warning("BatchingOrchestrator import failed — falling back to EventBus")
            except Exception as exc:
                logger.error("BatchingOrchestrator.submit() raised: %s", exc)

        # EventBus fallback
        request_id = str(uuid.uuid4())
        payload: Dict[str, Any] = {
            "request_id":    request_id,
            "model":         model,
            "prompt":        prompt,
            "system_prompt": system_prompt,
            "temperature":   temperature,
            "max_tokens":    max_tokens,
        }
        await self._bus.publish("llm.request", payload, source="lucie.orchestrator", token=None)
        return ""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


async def create_lucie_orchestrator(
    event_bus: Any,
    audit_trail: Any,
    *,
    batching: Any           = None,
    memory_guardian: Any    = None,
    predictive_preloader: Any = None,
    stop_timeout: float     = 10.0,
) -> LucieOrchestrator:
    """
    Factory: assemble and return a configured LucieOrchestrator.

    Registers well-known services in dependency order and installs default
    parsers/loaders from Phase 5 if available.

    The caller must still invoke orchestrator.start() before use.

    Args:
        event_bus:            EventBus v3 instance.
        audit_trail:          AuditTrail v2 instance.
        batching:             Optional BatchingOrchestrator.
        memory_guardian:      Optional MemoryGuardian.
        predictive_preloader: Optional PredictivePreloader.
        stop_timeout:         Per-service shutdown timeout in seconds.
    """
    orchestrator = LucieOrchestrator(
        event_bus=event_bus,
        audit_trail=audit_trail,
        stop_timeout=stop_timeout,
    )

    # Register optional services in dependency-correct order
    if memory_guardian is not None:
        orchestrator.register_service(ServiceDescriptor(
            name="memory",
            capabilities=[Capability.MEMORY],
            dependencies=[],
            instance=memory_guardian,
        ))

    if batching is not None:
        orchestrator.register_service(ServiceDescriptor(
            name="batching",
            capabilities=[Capability.BATCH, Capability.LLM_INFERENCE],
            dependencies=["memory"] if memory_guardian is not None else [],
            instance=batching,
        ))

    if predictive_preloader is not None:
        orchestrator.register_service(ServiceDescriptor(
            name="predict",
            capabilities=[Capability.PREDICT],
            dependencies=["memory"] if memory_guardian is not None else [],
            instance=predictive_preloader,
        ))

    # Install Phase 5 parsers/loaders (graceful degradation if not importable)
    try:
        from app.services.facturx_parser import FacturXSecureParser
        orchestrator.register_parser(".pdf", FacturXSecureParser())
        logger.info("FacturXSecureParser installed for .pdf")
    except ImportError:
        logger.warning("FacturXSecureParser not available — PDF parsing disabled")

    try:
        from app.services.excel_secure import ExcelSecureLoader
        for ext in (".xlsx", ".xls", ".xlsm", ".xlsb", ".csv"):
            orchestrator.register_loader(ext, ExcelSecureLoader(event_bus=event_bus))
        logger.info("ExcelSecureLoader installed for Excel/CSV extensions")
    except ImportError:
        logger.warning("ExcelSecureLoader not available — Excel parsing disabled")

    return orchestrator
