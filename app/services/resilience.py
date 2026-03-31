"""
ResiliencePolicy — Circuit Breaker + Retry + Fallback pour les services Lucie.

Architecture:
    CircuitBreaker    : 3 états (CLOSED → OPEN → HALF_OPEN → CLOSED)
                        avec asyncio.Lock pour sécurité asynchrone.
    RetryPolicy       : backoff exponentiel + full jitter, exceptions configurables.
    ResiliencePolicy  : composition Circuit + Retry + Fallback.
    with_resilience() : décorateur qui wraps toute coroutine asynchrone.
    ResilienceRegistry: registre centralisé, publie les métriques sur EventBus.

Intégrations pré-configurées:
    batching_policy      : 3 tentatives, fallback gemma2:2b
    parser_policy        : 2 tentatives, fallback PDF-only analysis
    memory_sync_policy   : 5 tentatives, pas de fallback

Usage:
    @with_resilience(parser_policy, fallback=_fallback_pdf_only_analysis)
    async def parse_document(pdf_bytes: bytes) -> dict: ...

    policy = ResiliencePolicy("my_svc", circuit, retry)
    result = await policy.execute(my_coroutine_fn, arg1, arg2)
"""
from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional, Tuple, Type

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


class CircuitState(Enum):
    CLOSED    = "CLOSED"
    OPEN      = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """Raised when a call is attempted on an OPEN circuit with no fallback."""


@dataclass
class CircuitBreakerMetrics:
    total_calls:       int   = 0
    successful_calls:  int   = 0
    failed_calls:      int   = 0
    fallback_used:     int   = 0
    open_count:        int   = 0
    half_open_probes:  int   = 0


class CircuitBreaker:
    """
    Async-safe circuit breaker backed by asyncio.Lock.

    State machine:
        CLOSED    → normal; accumulates failures up to failure_threshold
        OPEN      → all calls rejected; transitions to HALF_OPEN after recovery_timeout
        HALF_OPEN → probe allowed; success × half_open_success_threshold → CLOSED,
                    any failure → OPEN

    The Lock is held only for state inspection/mutation — never across the actual
    async call — so the breaker does not serialize concurrent callers.
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int         = 5,
        recovery_timeout: float        = 60.0,
        half_open_success_threshold: int = 2,
    ) -> None:
        self.name                        = name
        self.failure_threshold           = failure_threshold
        self.recovery_timeout            = recovery_timeout
        self.half_open_success_threshold = half_open_success_threshold

        self._state              = CircuitState.CLOSED
        self._failure_count      = 0
        self._half_open_wins     = 0
        self._last_failure_time  = 0.0
        self._lock               = asyncio.Lock()
        self.metrics             = CircuitBreakerMetrics()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def _transition(self, new_state: CircuitState) -> None:
        """Apply a state transition (must be called under self._lock)."""
        if new_state == CircuitState.OPEN:
            self.metrics.open_count   += 1
            self._last_failure_time    = time.monotonic()
            self._half_open_wins       = 0
        elif new_state == CircuitState.HALF_OPEN:
            self.metrics.half_open_probes += 1
            self._half_open_wins       = 0
        elif new_state == CircuitState.CLOSED:
            self._failure_count        = 0
        self._state = new_state
        logger.info("CircuitBreaker '%s' → %s", self.name, new_state.value)

    async def call(
        self,
        coro_fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        fallback: Optional[Callable[..., Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Execute coro_fn under circuit protection.

        - OPEN  → invoke fallback if provided, else raise CircuitOpenError.
        - CLOSED/HALF_OPEN → execute coro_fn; update state on success/failure.
        """
        async with self._lock:
            self.metrics.total_calls += 1

            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    await self._transition(CircuitState.HALF_OPEN)
                else:
                    self.metrics.fallback_used += 1
                    if fallback is not None:
                        return (
                            await fallback(*args, **kwargs)
                            if asyncio.iscoroutinefunction(fallback)
                            else fallback(*args, **kwargs)
                        )
                    raise CircuitOpenError(
                        f"Circuit '{self.name}' is OPEN "
                        f"({self.recovery_timeout - elapsed:.1f}s until probe)"
                    )

        # Execute the call outside the lock
        try:
            result = await coro_fn(*args, **kwargs)
        except Exception as exc:
            async with self._lock:
                self.metrics.failed_calls += 1
                self._failure_count += 1
                if self._state == CircuitState.HALF_OPEN:
                    await self._transition(CircuitState.OPEN)
                elif (
                    self._state == CircuitState.CLOSED
                    and self._failure_count >= self.failure_threshold
                ):
                    await self._transition(CircuitState.OPEN)
            raise

        async with self._lock:
            self.metrics.successful_calls += 1
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_wins += 1
                if self._half_open_wins >= self.half_open_success_threshold:
                    await self._transition(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

        return result


# ---------------------------------------------------------------------------
# Retry Policy
# ---------------------------------------------------------------------------


class RetryExhaustedError(Exception):
    """Raised when all retry attempts have been exhausted."""


@dataclass
class RetryPolicy:
    """
    Exponential backoff with full jitter.

    Formula (AWS full-jitter):
        delay = random.uniform(0, min(max_delay, base_delay × 2^attempt))

    Fields:
        max_attempts           : total attempts (1 = no retry)
        base_delay             : initial backoff in seconds
        max_delay              : upper bound on computed delay
        jitter                 : True → full jitter, False → deterministic cap
        retryable_exceptions   : exception types that trigger a retry
        non_retryable_exceptions: exception types that short-circuit immediately
    """

    max_attempts:             int   = 3
    base_delay:               float = 0.5
    max_delay:                float = 30.0
    jitter:                   bool  = True
    retryable_exceptions:     Tuple[Type[Exception], ...] = field(
        default_factory=lambda: (Exception,)
    )
    non_retryable_exceptions: Tuple[Type[Exception], ...] = field(
        default_factory=tuple
    )

    def _compute_delay(self, attempt: int) -> float:
        cap = min(self.max_delay, self.base_delay * (2 ** attempt))
        return random.uniform(0, cap) if self.jitter else cap

    async def execute(
        self,
        coro_fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute coro_fn with retry logic.

        Non-retryable exceptions bypass the retry loop entirely.
        Retryable exceptions trigger exponential backoff.
        After max_attempts, raises RetryExhaustedError.
        """
        last_exc: Optional[Exception] = None

        for attempt in range(self.max_attempts):
            try:
                return await coro_fn(*args, **kwargs)

            except self.non_retryable_exceptions as exc:
                # Immediately re-raise — no retry for these
                raise exc from exc

            except self.retryable_exceptions as exc:
                last_exc = exc
                if attempt < self.max_attempts - 1:
                    delay = self._compute_delay(attempt)
                    logger.warning(
                        "Attempt %d/%d failed (%s: %s). Retrying in %.3fs.",
                        attempt + 1,
                        self.max_attempts,
                        type(exc).__name__,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

        raise RetryExhaustedError(
            f"All {self.max_attempts} attempt(s) failed. "
            f"Last exception: {type(last_exc).__name__}: {last_exc}"
        ) from last_exc


# ---------------------------------------------------------------------------
# ResiliencePolicy — Circuit + Retry + Fallback
# ---------------------------------------------------------------------------


class ResiliencePolicy:
    """
    Combines CircuitBreaker + RetryPolicy + optional Fallback.

    Execution order:
        1. Ask the circuit breaker (OPEN → fallback or CircuitOpenError)
        2. The circuit wraps a retry loop around the actual coroutine
        3. On persistent failure: circuit state is updated, fallback invoked
        4. RetryExhaustedError / CircuitOpenError → fallback if available, else raise
    """

    def __init__(
        self,
        name: str,
        circuit_breaker: CircuitBreaker,
        retry_policy: RetryPolicy,
        fallback: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.name            = name
        self.circuit_breaker = circuit_breaker
        self.retry_policy    = retry_policy
        self.fallback        = fallback

    async def execute(
        self,
        coro_fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        async def _with_retry() -> Any:
            return await self.retry_policy.execute(coro_fn, *args, **kwargs)

        try:
            return await self.circuit_breaker.call(
                _with_retry,
                fallback=self.fallback,
            )
        except (RetryExhaustedError, CircuitOpenError) as exc:
            if self.fallback is not None:
                logger.warning(
                    "ResiliencePolicy '%s': activating fallback after %s",
                    self.name,
                    type(exc).__name__,
                )
                if asyncio.iscoroutinefunction(self.fallback):
                    return await self.fallback(*args, **kwargs)
                return self.fallback(*args, **kwargs)
            raise


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def with_resilience(
    policy: ResiliencePolicy,
    fallback: Optional[Callable[..., Any]] = None,
) -> Callable[
    [Callable[..., Coroutine[Any, Any, Any]]],
    Callable[..., Coroutine[Any, Any, Any]],
]:
    """
    Decorator that wraps an async function with a ResiliencePolicy.

    If `fallback` is provided it overrides policy.fallback for this decoration.

    Usage:
        @with_resilience(parser_policy, fallback=_fallback_pdf_only_analysis)
        async def parse_facturx(pdf_bytes: bytes) -> dict:
            ...
    """
    def decorator(
        fn: Callable[..., Coroutine[Any, Any, Any]],
    ) -> Callable[..., Coroutine[Any, Any, Any]]:
        effective_fallback = fallback if fallback is not None else policy.fallback
        effective_policy = ResiliencePolicy(
            name=policy.name,
            circuit_breaker=policy.circuit_breaker,
            retry_policy=policy.retry_policy,
            fallback=effective_fallback,
        )

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await effective_policy.execute(fn, *args, **kwargs)

        # Expose the policy on the wrapper for introspection
        wrapper.__resilience_policy__ = effective_policy  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# ResilienceRegistry
# ---------------------------------------------------------------------------


class ResilienceRegistry:
    """
    Central registry of ResiliencePolicies.

    Aggregates metrics from all registered policies and can publish a snapshot
    to the EventBus on demand (e.g. for observability dashboards).
    """

    def __init__(self, event_bus: Any = None) -> None:
        self._policies:  Dict[str, ResiliencePolicy] = {}
        self._event_bus = event_bus

    def register(self, policy: ResiliencePolicy) -> None:
        self._policies[policy.name] = policy

    def get(self, name: str) -> Optional[ResiliencePolicy]:
        return self._policies.get(name)

    def metrics_snapshot(self) -> Dict[str, Any]:
        """Return a point-in-time snapshot of all circuit breaker metrics."""
        return {
            name: {
                "state":            policy.circuit_breaker.state.value,
                "total_calls":      policy.circuit_breaker.metrics.total_calls,
                "successful_calls": policy.circuit_breaker.metrics.successful_calls,
                "failed_calls":     policy.circuit_breaker.metrics.failed_calls,
                "fallback_used":    policy.circuit_breaker.metrics.fallback_used,
                "open_count":       policy.circuit_breaker.metrics.open_count,
                "half_open_probes": policy.circuit_breaker.metrics.half_open_probes,
            }
            for name, policy in self._policies.items()
        }

    async def publish_metrics(self, source: str = "resilience.registry") -> None:
        """Publish a metrics snapshot to EventBus if configured."""
        if self._event_bus is None:
            return
        snapshot = self.metrics_snapshot()
        try:
            await self._event_bus.publish(
                "resilience.metrics",
                snapshot,
                source=source,
                token=None,
            )
        except Exception as exc:
            logger.warning("ResilienceRegistry.publish_metrics failed: %s", exc)


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------


async def _fallback_small_model(
    model: str,
    prompt: str,
    *args: Any,
    **kwargs: Any,
) -> str:
    """
    LLM fallback: downgrade from the primary model to gemma2:2b.

    Used by batching_policy when Ollama is unavailable or overloaded.
    """
    import aiohttp

    fallback_model = "gemma2:2b"
    logger.warning(
        "LLM fallback: demoting from '%s' to '%s'", model, fallback_model
    )
    payload = {"model": fallback_model, "prompt": prompt, "stream": False}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:11434/api/generate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return str(data.get("response", ""))
    except Exception as exc:
        logger.error("_fallback_small_model also failed: %s", exc)
        return ""


async def _fallback_pdf_only_analysis(
    pdf_bytes: bytes,
    *args: Any,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Parser fallback: extract raw text from the PDF without XML processing.

    Used by parser_policy when FacturXSecureParser raises or the circuit is OPEN.
    Returns a result dict with safe=False so callers know this is a degraded path.
    """
    logger.warning("Parser fallback: PDF-only text extraction (no XML validation)")
    result: Dict[str, Any] = {
        "safe":     False,
        "fallback": True,
        "alerts":   ["XML parsing failed — PDF-only analysis applied"],
        "data":     {},
    }
    try:
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        result["data"] = {"raw_text": text[:2000]}
    except Exception as exc:
        logger.error("_fallback_pdf_only_analysis: pdfplumber failed: %s", exc)
    return result


# ---------------------------------------------------------------------------
# Pre-configured policies (module-level singletons)
# ---------------------------------------------------------------------------


def _batching_circuit() -> CircuitBreaker:
    return CircuitBreaker(
        "batching",
        failure_threshold=5,
        recovery_timeout=30.0,
        half_open_success_threshold=2,
    )


def _parser_circuit() -> CircuitBreaker:
    return CircuitBreaker(
        "parser",
        failure_threshold=3,
        recovery_timeout=60.0,
        half_open_success_threshold=1,
    )


def _memory_sync_circuit() -> CircuitBreaker:
    return CircuitBreaker(
        "memory_sync",
        failure_threshold=10,
        recovery_timeout=15.0,
        half_open_success_threshold=3,
    )


batching_policy: ResiliencePolicy = ResiliencePolicy(
    name="batching",
    circuit_breaker=_batching_circuit(),
    retry_policy=RetryPolicy(
        max_attempts=3,
        base_delay=0.5,
        max_delay=10.0,
        jitter=True,
        non_retryable_exceptions=(ValueError, TypeError),
    ),
    fallback=_fallback_small_model,
)

parser_policy: ResiliencePolicy = ResiliencePolicy(
    name="parser",
    circuit_breaker=_parser_circuit(),
    retry_policy=RetryPolicy(
        max_attempts=2,
        base_delay=0.2,
        max_delay=5.0,
        jitter=False,
        non_retryable_exceptions=(ValueError,),
    ),
    fallback=_fallback_pdf_only_analysis,
)

memory_sync_policy: ResiliencePolicy = ResiliencePolicy(
    name="memory_sync",
    circuit_breaker=_memory_sync_circuit(),
    retry_policy=RetryPolicy(
        max_attempts=5,
        base_delay=0.1,
        max_delay=5.0,
        jitter=True,
    ),
    fallback=None,
)
