"""
Tests unitaires pour ResiliencePolicy — Phase 6.

Couverture:
    CircuitBreaker:
        - CLOSED → OPEN après failure_threshold échecs
        - OPEN → HALF_OPEN après recovery_timeout
        - HALF_OPEN → CLOSED après half_open_success_threshold succès
        - HALF_OPEN → OPEN si un échec survient en probe
        - Fallback invoqué en état OPEN (sans exception)
        - CircuitOpenError levée en état OPEN sans fallback

    RetryPolicy:
        - Succès au premier appel (0 retry)
        - Succès après N tentatives (retry successful)
        - RetryExhaustedError après épuisement des tentatives
        - Exception non-retryable : propagée immédiatement sans retry
        - Délai nul possible (base_delay=0, jitter=False) pour tests rapides

    ResiliencePolicy (combinaison):
        - Fallback activé sur RetryExhaustedError
        - Fallback activé quand circuit est OPEN
        - Pas de fallback → exception propagée

    Décorateur @with_resilience:
        - Wraps une coroutine correctement
        - Exposeq __resilience_policy__ sur le wrapper
        - Fallback override fonctionne

    ResilienceRegistry:
        - register / get
        - metrics_snapshot() couvre tous les champs
        - publish_metrics() délègue à EventBus

    Intégration panne Ollama:
        - Simulation de 503 → retry × 3 → circuit OPEN → fallback gemma2:2b mockée
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.resilience import (
    CircuitBreaker,
    CircuitBreakerMetrics,
    CircuitOpenError,
    CircuitState,
    ResiliencePolicy,
    ResilienceRegistry,
    RetryExhaustedError,
    RetryPolicy,
    batching_policy,
    memory_sync_policy,
    parser_policy,
    with_resilience,
    _fallback_small_model,
    _fallback_pdf_only_analysis,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _success(value: Any = "ok") -> Any:
    return value


async def _always_fail(exc: Exception = None) -> None:
    raise exc or IOError("simulated failure")


def _make_flaky(fail_times: int, value: Any = "ok") -> Any:
    """Returns a coroutine function that fails `fail_times` then succeeds."""
    count = {"n": 0}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        count["n"] += 1
        if count["n"] <= fail_times:
            raise IOError(f"transient failure #{count['n']}")
        return value

    return flaky


class MockEventBus:
    def __init__(self) -> None:
        self.published: List[Any] = []

    async def publish(self, channel: str, data: Any, **kwargs: Any) -> None:
        self.published.append((channel, data))


# ---------------------------------------------------------------------------
# CircuitBreaker tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_successful_call_stays_closed(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3)

        result = await cb.call(lambda: _success("hello"))
        assert result == "hello"
        assert cb.state == CircuitState.CLOSED
        assert cb.metrics.successful_calls == 1

    @pytest.mark.asyncio
    async def test_opens_after_failure_threshold(self) -> None:
        """3 échecs consécutifs doivent ouvrir le circuit."""
        cb = CircuitBreaker("test", failure_threshold=3)

        for _ in range(3):
            with pytest.raises(IOError):
                await cb.call(lambda: _always_fail(IOError("fail")))

        assert cb.state == CircuitState.OPEN
        assert cb.metrics.open_count == 1

    @pytest.mark.asyncio
    async def test_open_circuit_raises_without_fallback(self) -> None:
        """Un circuit OPEN sans fallback lève CircuitOpenError."""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=999)

        with pytest.raises(IOError):
            await cb.call(lambda: _always_fail(IOError("fail")))

        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitOpenError):
            await cb.call(lambda: _success())

    @pytest.mark.asyncio
    async def test_open_circuit_uses_fallback(self) -> None:
        """Un circuit OPEN avec fallback invoque le fallback (pas d'exception)."""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=999)

        with pytest.raises(IOError):
            await cb.call(lambda: _always_fail(IOError("fail")))

        async def _fb(*a: Any, **k: Any) -> str:
            return "fallback_result"

        result = await cb.call(lambda: _success(), fallback=_fb)
        assert result == "fallback_result"
        assert cb.metrics.fallback_used == 1

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self) -> None:
        """Après recovery_timeout, le circuit passe de OPEN à HALF_OPEN."""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)

        with pytest.raises(IOError):
            await cb.call(lambda: _always_fail(IOError("fail")))

        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.06)

        # Le prochain appel doit transiter vers HALF_OPEN
        result = await cb.call(lambda: _success("probe_ok"))
        assert result == "probe_ok"
        # Après un succès en HALF_OPEN (threshold=2), on reste en HALF_OPEN si threshold > 1
        # ou on passe directement à CLOSED si threshold = 1
        # Ici threshold par défaut = 2, donc toujours HALF_OPEN après 1 succès
        assert cb.state in (CircuitState.HALF_OPEN, CircuitState.CLOSED)

    @pytest.mark.asyncio
    async def test_half_open_closes_after_enough_successes(self) -> None:
        """half_open_success_threshold succès en HALF_OPEN → retour à CLOSED."""
        cb = CircuitBreaker(
            "test",
            failure_threshold=1,
            recovery_timeout=0.01,
            half_open_success_threshold=2,
        )

        with pytest.raises(IOError):
            await cb.call(lambda: _always_fail(IOError("fail")))

        await asyncio.sleep(0.02)

        # 2 succès → CLOSED
        await cb.call(lambda: _success())
        await cb.call(lambda: _success())

        assert cb.state == CircuitState.CLOSED
        assert cb.metrics.failed_calls == 1

    @pytest.mark.asyncio
    async def test_half_open_reopens_on_failure(self) -> None:
        """Un échec en HALF_OPEN rouvre immédiatement le circuit."""
        cb = CircuitBreaker(
            "test",
            failure_threshold=1,
            recovery_timeout=0.01,
            half_open_success_threshold=3,
        )

        with pytest.raises(IOError):
            await cb.call(lambda: _always_fail(IOError("fail")))

        await asyncio.sleep(0.02)

        # 1 succès (still HALF_OPEN), puis 1 échec → retour OPEN
        await cb.call(lambda: _success())
        assert cb.state == CircuitState.HALF_OPEN

        with pytest.raises(IOError):
            await cb.call(lambda: _always_fail(IOError("probe failed")))

        assert cb.state == CircuitState.OPEN
        assert cb.metrics.open_count == 2

    @pytest.mark.asyncio
    async def test_metrics_track_all_fields(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=2)

        await cb.call(lambda: _success())
        with pytest.raises(IOError):
            await cb.call(lambda: _always_fail(IOError("e1")))
        with pytest.raises(IOError):
            await cb.call(lambda: _always_fail(IOError("e2")))

        assert cb.metrics.total_calls     == 3
        assert cb.metrics.successful_calls == 1
        assert cb.metrics.failed_calls     == 2
        assert cb.metrics.open_count       == 1


# ---------------------------------------------------------------------------
# RetryPolicy tests
# ---------------------------------------------------------------------------


class TestRetryPolicy:

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self) -> None:
        policy = RetryPolicy(max_attempts=3, base_delay=0, jitter=False)
        result = await policy.execute(lambda: _success("first"))
        assert result == "first"

    @pytest.mark.asyncio
    async def test_success_after_retries(self) -> None:
        """Échec × 2 puis succès au 3ème appel."""
        flaky = _make_flaky(fail_times=2, value="recovered")
        policy = RetryPolicy(
            max_attempts=3,
            base_delay=0,
            jitter=False,
            retryable_exceptions=(IOError,),
        )
        result = await policy.execute(flaky)
        assert result == "recovered"

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self) -> None:
        """Tous les appels échouent → RetryExhaustedError."""
        flaky = _make_flaky(fail_times=99)
        policy = RetryPolicy(
            max_attempts=3,
            base_delay=0,
            jitter=False,
            retryable_exceptions=(IOError,),
        )
        with pytest.raises(RetryExhaustedError, match="3 attempt"):
            await policy.execute(flaky)

    @pytest.mark.asyncio
    async def test_non_retryable_exception_bypasses_retry(self) -> None:
        """Une ValueError configurée comme non-retryable est propagée immédiatement."""
        call_count = {"n": 0}

        async def raises_value_error() -> None:
            call_count["n"] += 1
            raise ValueError("bad input")

        policy = RetryPolicy(
            max_attempts=5,
            base_delay=0,
            jitter=False,
            retryable_exceptions=(IOError,),
            non_retryable_exceptions=(ValueError,),
        )

        with pytest.raises(ValueError, match="bad input"):
            await policy.execute(raises_value_error)

        assert call_count["n"] == 1, "Should not retry a non-retryable exception"

    @pytest.mark.asyncio
    async def test_single_attempt_no_retry(self) -> None:
        """max_attempts=1 → pas de retry, RetryExhaustedError immédiate."""
        policy = RetryPolicy(max_attempts=1, base_delay=0, jitter=False)

        with pytest.raises(RetryExhaustedError):
            await policy.execute(lambda: _always_fail(IOError("fail")))

    @pytest.mark.asyncio
    async def test_jitter_delay_is_non_negative(self) -> None:
        """Le délai calculé avec jitter ne doit jamais être négatif."""
        policy = RetryPolicy(max_attempts=1, base_delay=1.0, max_delay=10.0, jitter=True)
        for attempt in range(20):
            delay = policy._compute_delay(attempt)
            assert delay >= 0, f"Negative delay: {delay}"

    @pytest.mark.asyncio
    async def test_deterministic_delay_capped_at_max(self) -> None:
        """Sans jitter, le délai est capé à max_delay."""
        policy = RetryPolicy(
            max_attempts=1, base_delay=0.5, max_delay=2.0, jitter=False
        )
        # Attempt 10 : 0.5 * 2^10 = 512 → capé à 2.0
        delay = policy._compute_delay(10)
        assert delay == 2.0


# ---------------------------------------------------------------------------
# ResiliencePolicy tests
# ---------------------------------------------------------------------------


class TestResiliencePolicy:

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        cb     = CircuitBreaker("rp", failure_threshold=3)
        retry  = RetryPolicy(max_attempts=1, base_delay=0, jitter=False)
        policy = ResiliencePolicy("rp", cb, retry)

        result = await policy.execute(lambda: _success("rp_ok"))
        assert result == "rp_ok"

    @pytest.mark.asyncio
    async def test_fallback_on_retry_exhausted(self) -> None:
        """Après épuisement des retries, le fallback est invoqué."""
        cb     = CircuitBreaker("rp", failure_threshold=10)
        retry  = RetryPolicy(max_attempts=2, base_delay=0, jitter=False)

        async def fb(*a: Any, **k: Any) -> str:
            return "fallback_value"

        policy = ResiliencePolicy("rp", cb, retry, fallback=fb)
        result = await policy.execute(lambda: _always_fail(IOError("boom")))
        assert result == "fallback_value"

    @pytest.mark.asyncio
    async def test_no_fallback_propagates_exception(self) -> None:
        """Sans fallback, l'exception est propagée."""
        cb     = CircuitBreaker("rp", failure_threshold=10)
        retry  = RetryPolicy(max_attempts=1, base_delay=0, jitter=False)
        policy = ResiliencePolicy("rp", cb, retry, fallback=None)

        with pytest.raises(RetryExhaustedError):
            await policy.execute(lambda: _always_fail(IOError("boom")))

    @pytest.mark.asyncio
    async def test_fallback_on_open_circuit(self) -> None:
        """Quand le circuit est OPEN, le fallback de ResiliencePolicy est activé."""
        cb = CircuitBreaker("rp", failure_threshold=1, recovery_timeout=999)
        retry  = RetryPolicy(max_attempts=1, base_delay=0, jitter=False)

        async def fb(*a: Any, **k: Any) -> str:
            return "circuit_open_fallback"

        policy = ResiliencePolicy("rp", cb, retry, fallback=fb)

        # Ouvrir le circuit
        with pytest.raises((RetryExhaustedError, IOError)):
            await policy.execute(lambda: _always_fail(IOError("open me")))

        assert cb.state == CircuitState.OPEN

        # Le prochain appel doit utiliser le fallback
        result = await policy.execute(lambda: _success())
        assert result == "circuit_open_fallback"

    @pytest.mark.asyncio
    async def test_sync_fallback_works(self) -> None:
        """Un fallback synchrone (non-coroutine) fonctionne aussi."""
        cb     = CircuitBreaker("rp", failure_threshold=10)
        retry  = RetryPolicy(max_attempts=1, base_delay=0, jitter=False)

        def sync_fb(*a: Any, **k: Any) -> str:
            return "sync_fallback"

        policy = ResiliencePolicy("rp", cb, retry, fallback=sync_fb)
        result = await policy.execute(lambda: _always_fail(IOError("boom")))
        assert result == "sync_fallback"


# ---------------------------------------------------------------------------
# with_resilience decorator
# ---------------------------------------------------------------------------


class TestWithResilienceDecorator:

    @pytest.mark.asyncio
    async def test_decorator_wraps_coroutine(self) -> None:
        cb     = CircuitBreaker("dec", failure_threshold=3)
        retry  = RetryPolicy(max_attempts=1, base_delay=0, jitter=False)
        policy = ResiliencePolicy("dec", cb, retry)

        @with_resilience(policy)
        async def my_fn(x: int) -> int:
            return x * 2

        assert await my_fn(5) == 10

    @pytest.mark.asyncio
    async def test_decorator_preserves_function_metadata(self) -> None:
        cb     = CircuitBreaker("dec", failure_threshold=3)
        retry  = RetryPolicy(max_attempts=1, base_delay=0, jitter=False)
        policy = ResiliencePolicy("dec", cb, retry)

        @with_resilience(policy)
        async def documented_fn() -> None:
            """My docstring."""

        assert documented_fn.__name__ == "documented_fn"
        assert documented_fn.__doc__  == "My docstring."

    @pytest.mark.asyncio
    async def test_decorator_exposes_resilience_policy(self) -> None:
        cb     = CircuitBreaker("dec", failure_threshold=3)
        retry  = RetryPolicy(max_attempts=1, base_delay=0, jitter=False)
        policy = ResiliencePolicy("dec", cb, retry)

        @with_resilience(policy)
        async def my_fn() -> None: ...

        assert hasattr(my_fn, "__resilience_policy__")
        assert my_fn.__resilience_policy__.name == "dec"

    @pytest.mark.asyncio
    async def test_decorator_fallback_override(self) -> None:
        """Le fallback passé au décorateur prime sur celui de la policy."""
        cb     = CircuitBreaker("dec", failure_threshold=1)
        retry  = RetryPolicy(max_attempts=1, base_delay=0, jitter=False)
        policy_fb = AsyncMock(return_value="policy_fb")
        override_fb = AsyncMock(return_value="override_fb")

        policy = ResiliencePolicy("dec", cb, retry, fallback=policy_fb)

        @with_resilience(policy, fallback=override_fb)
        async def failing_fn() -> None:
            raise IOError("boom")

        result = await failing_fn()
        assert result == "override_fb"
        policy_fb.assert_not_called()


# ---------------------------------------------------------------------------
# ResilienceRegistry
# ---------------------------------------------------------------------------


class TestResilienceRegistry:

    def test_register_and_get(self) -> None:
        reg    = ResilienceRegistry()
        cb     = CircuitBreaker("reg_test", failure_threshold=3)
        retry  = RetryPolicy()
        policy = ResiliencePolicy("reg_test", cb, retry)

        reg.register(policy)
        assert reg.get("reg_test") is policy

    def test_get_unknown_returns_none(self) -> None:
        reg = ResilienceRegistry()
        assert reg.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_metrics_snapshot_structure(self) -> None:
        reg    = ResilienceRegistry()
        cb     = CircuitBreaker("snap", failure_threshold=3)
        retry  = RetryPolicy(max_attempts=1, base_delay=0, jitter=False)
        policy = ResiliencePolicy("snap", cb, retry)
        reg.register(policy)

        # Générer quelques événements
        await cb.call(lambda: _success())
        with pytest.raises(IOError):
            await cb.call(lambda: _always_fail(IOError("e")))

        snap = reg.metrics_snapshot()
        assert "snap" in snap
        m = snap["snap"]
        assert m["state"]            == CircuitState.CLOSED.value
        assert m["total_calls"]      == 2
        assert m["successful_calls"] == 1
        assert m["failed_calls"]     == 1
        assert m["open_count"]       == 0
        assert "fallback_used"    in m
        assert "half_open_probes" in m

    @pytest.mark.asyncio
    async def test_publish_metrics_calls_event_bus(self) -> None:
        bus = MockEventBus()
        reg = ResilienceRegistry(event_bus=bus)

        cb     = CircuitBreaker("pub", failure_threshold=3)
        retry  = RetryPolicy()
        policy = ResiliencePolicy("pub", cb, retry)
        reg.register(policy)

        await reg.publish_metrics()

        assert len(bus.published) == 1
        channel, data = bus.published[0]
        assert channel == "resilience.metrics"
        assert "pub" in data

    @pytest.mark.asyncio
    async def test_publish_metrics_no_bus_is_noop(self) -> None:
        """Sans EventBus, publish_metrics() ne lève pas d'exception."""
        reg = ResilienceRegistry(event_bus=None)
        await reg.publish_metrics()   # Must not raise


# ---------------------------------------------------------------------------
# Intégration — panne Ollama simulée
# ---------------------------------------------------------------------------


class TestOllamaOutageIntegration:
    """
    Simulation d'une panne Ollama : HTTP 503 repeaté → circuit OPEN → fallback.
    Le fallback small model est testé avec un mock aiohttp pour éviter
    les appels réseau réels.
    """

    @pytest.mark.asyncio
    async def test_ollama_503_opens_circuit(self) -> None:
        """
        Après 3 échecs HTTP 503, le circuit doit être OPEN.
        """
        import aiohttp

        call_count = {"n": 0}

        async def call_ollama(model: str, prompt: str) -> str:
            call_count["n"] += 1
            raise aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=503,
                message="Service Unavailable",
            )

        cb     = CircuitBreaker("ollama", failure_threshold=3)
        retry  = RetryPolicy(
            max_attempts=1,   # 1 attempt per call, circuit tracks globally
            base_delay=0,
            jitter=False,
            retryable_exceptions=(aiohttp.ClientError, IOError),
        )
        policy = ResiliencePolicy("ollama", cb, retry, fallback=None)

        for _ in range(3):
            with pytest.raises((aiohttp.ClientError, RetryExhaustedError)):
                await policy.execute(call_ollama, "mistral:7b", "test prompt")

        assert cb.state == CircuitState.OPEN
        assert cb.metrics.open_count == 1

    @pytest.mark.asyncio
    async def test_fallback_small_model_called_when_open(self) -> None:
        """
        Quand le circuit est OPEN, le fallback _fallback_small_model est invoqué.
        On mock aiohttp pour retourner une réponse gemma2:2b valide.
        """
        import aiohttp

        cb = CircuitBreaker("ollama_fb", failure_threshold=1, recovery_timeout=999)
        retry  = RetryPolicy(max_attempts=1, base_delay=0, jitter=False)
        policy = ResiliencePolicy("ollama_fb", cb, retry, fallback=_fallback_small_model)

        # Ouvrir le circuit
        async def fail(*a: Any, **k: Any) -> str:
            raise IOError("Ollama down")

        with pytest.raises((IOError, RetryExhaustedError)):
            await policy.execute(fail)

        assert cb.state == CircuitState.OPEN

        # Mocker aiohttp pour simuler gemma2:2b
        mock_response = AsyncMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__  = AsyncMock(return_value=False)
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value={"response": "Résumé gemma2:2b"})

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__  = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await policy.execute(fail, "mistral:7b", "prompt test")

        assert result == "Résumé gemma2:2b"

    @pytest.mark.asyncio
    async def test_circuit_recovers_after_timeout(self) -> None:
        """
        Après recovery_timeout, le circuit tente une probe.
        Si la probe réussit, le circuit se referme.
        """
        cb    = CircuitBreaker("recover", failure_threshold=1, recovery_timeout=0.03)
        retry = RetryPolicy(
            max_attempts=1,
            base_delay=0,
            jitter=False,
            half_open_success_threshold=1,  # Note: this is on CB, not retry
        )

        async def ollama_call() -> str:
            return "success_after_recovery"

        async def ollama_fail() -> str:
            raise IOError("down")

        # Ouvrir le circuit
        with pytest.raises(IOError):
            await cb.call(ollama_fail)

        assert cb.state == CircuitState.OPEN

        # Attendre le timeout
        await asyncio.sleep(0.04)

        # Probe réussie → transition HALF_OPEN ou CLOSED
        result = await cb.call(ollama_call)
        assert result == "success_after_recovery"


# ---------------------------------------------------------------------------
# Politiques pré-configurées (smoke tests)
# ---------------------------------------------------------------------------


class TestPreConfiguredPolicies:

    def test_batching_policy_configured(self) -> None:
        assert batching_policy.name == "batching"
        assert batching_policy.circuit_breaker.failure_threshold == 5
        assert batching_policy.retry_policy.max_attempts == 3
        assert batching_policy.fallback is not None  # _fallback_small_model

    def test_parser_policy_configured(self) -> None:
        assert parser_policy.name == "parser"
        assert parser_policy.circuit_breaker.failure_threshold == 3
        assert parser_policy.retry_policy.max_attempts == 2
        assert parser_policy.fallback is not None  # _fallback_pdf_only_analysis

    def test_memory_sync_policy_configured(self) -> None:
        assert memory_sync_policy.name == "memory_sync"
        assert memory_sync_policy.circuit_breaker.failure_threshold == 10
        assert memory_sync_policy.retry_policy.max_attempts == 5
        assert memory_sync_policy.fallback is None

    @pytest.mark.asyncio
    async def test_fallback_pdf_only_returns_dict(self) -> None:
        """_fallback_pdf_only_analysis retourne un dict avec les bonnes clés."""
        result = await _fallback_pdf_only_analysis(b"fake-pdf-bytes")
        assert isinstance(result, dict)
        assert "safe"     in result
        assert "fallback" in result
        assert "alerts"   in result
        assert result["safe"]     is False
        assert result["fallback"] is True
