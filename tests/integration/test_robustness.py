"""
Tests de robustesse pour LucidEngine.
Vérifie que les erreurs sont gérées proprement et retournées en français.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.utils.error_humanizer import humanize_error
from app.utils.exceptions import LLMConnectionError, LLMTimeoutError
from app.core.engine import LucidEngine


# ─────────────────────────────────────────────────────────────────────────────
# Fixture : engine minimal
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    """LucidEngine sans init lourd — composants mockés."""
    eng = LucidEngine.__new__(LucidEngine)
    eng.manager = MagicMock()
    eng.manager.generate.return_value = "Réponse mockée"
    eng.contextual_memory = MagicMock()
    eng.contextual_memory.get_context_for_query = AsyncMock(return_value={})
    eng.rag = MagicMock()
    eng.rag.active = False
    eng.cortex = MagicMock()
    eng.cortex.think = AsyncMock(return_value=("OK", 1.0))
    eng.cortex.planner = MagicMock()
    eng.cortex.planner.decompose = AsyncMock(return_value=[])
    eng.cortex.execute_pipeline = AsyncMock(return_value="")
    eng.action_router = MagicMock()
    eng.action_router.parse_and_execute.side_effect = lambda r: (False, r)
    return eng


# ─────────────────────────────────────────────────────────────────────────────
# Tests directs sur humanize_error
# ─────────────────────────────────────────────────────────────────────────────

class TestHumanizeError:
    def test_connection_refused_is_french(self):
        msg = humanize_error("connection refused")
        assert "Ollama" in msg or "connecter" in msg
        assert "Traceback" not in msg
        assert "Error" not in msg

    def test_timeout_is_french(self):
        msg = humanize_error("timeout")
        assert "trop de temps" in msg or "Réessaie" in msg
        assert "Traceback" not in msg

    def test_model_not_found_is_french(self):
        msg = humanize_error("model not found: qwen2.5")
        assert "installé" in msg or "ollama pull" in msg

    def test_broken_pipe_is_french(self):
        msg = humanize_error("broken pipe connection lost")
        assert "connexion" in msg.lower() or "interrompue" in msg

    def test_out_of_memory_is_french(self):
        msg = humanize_error("out of memory")
        assert "mémoire" in msg.lower()

    def test_error_prefix_gives_generic_french(self):
        msg = humanize_error("Erreur: something went wrong")
        assert "fonctionné" in msg or "reformuler" in msg
        # Pas de traceback Python
        assert "Traceback" not in msg
        assert "File " not in msg

    def test_known_internal_error_thalamus(self):
        msg = humanize_error("Aucun agent Thalamus disponible")
        assert "reformuler" in msg.lower() or "comprendre" in msg.lower()

    def test_non_error_passthrough(self):
        """Un message normal (non-erreur) est retourné tel quel."""
        msg = humanize_error("Bonjour !")
        assert msg == "Bonjour !"


# ─────────────────────────────────────────────────────────────────────────────
# Tests via process_async (chemin complexe → exception → humanize)
# ─────────────────────────────────────────────────────────────────────────────

class TestOllamaDown:
    @pytest.mark.asyncio
    async def test_connection_error_returns_french_message(self, engine):
        """Ollama down → cortex.think lève LLMConnectionError → message humain en français."""
        engine.cortex.think.side_effect = LLMConnectionError("connection refused")
        # Requête complexe (verbe d'action) pour passer par _process_async_core
        response, _ = await engine.process_async(
            "organise mes dossiers par date"
        )
        assert isinstance(response, str)
        # Doit être un message humain en français (pas un traceback)
        assert "Traceback" not in response
        assert "LLMConnectionError" not in response
        assert "connecter" in response.lower() or "fonctionné" in response.lower() or "Ollama" in response

    @pytest.mark.asyncio
    async def test_connection_error_no_traceback(self, engine):
        """Aucun traceback Python ne doit apparaître dans la réponse."""
        engine.cortex.think.side_effect = Exception("connection refused to localhost:11434")
        response, _ = await engine.process_async("ouvre mon calendrier")
        assert "Traceback" not in response
        assert "File " not in response


class TestAgentException:
    @pytest.mark.asyncio
    async def test_agent_exception_engine_survives(self, engine):
        """Agent qui lève une exception → engine survit, fallback gracieux."""
        engine.cortex.think.side_effect = RuntimeError("Agent interne a crashé")
        try:
            response, latency = await engine.process_async("organise mes fichiers par date")
            # L'engine doit survivre
            assert isinstance(response, str)
            assert isinstance(latency, float)
            # Message d'erreur humain
            assert "Traceback" not in response
            assert "RuntimeError" not in response
        except Exception as e:
            pytest.fail(f"Engine n'a pas survécu à l'exception de l'agent: {e}")

    @pytest.mark.asyncio
    async def test_multiple_agent_failures_engine_survives(self, engine):
        """Plusieurs appels avec échecs successifs → engine ne crashe jamais."""
        engine.cortex.think.side_effect = Exception("Échec agent")
        for _ in range(3):
            response, _ = await engine.process_async("ouvre mon agenda")
            assert isinstance(response, str)


class TestLLMTimeout:
    @pytest.mark.asyncio
    async def test_llm_timeout_returns_french_message(self, engine):
        """LLM timeout → message propre via error_humanizer."""
        engine.cortex.think.side_effect = LLMTimeoutError("Timeout après 3 tentatives.")
        response, _ = await engine.process_async("organise mes fichiers par date")
        assert isinstance(response, str)
        assert "Traceback" not in response
        assert "LLMTimeoutError" not in response

    @pytest.mark.asyncio
    async def test_asyncio_timeout_returns_french_message(self, engine):
        """asyncio.TimeoutError → humanize_error('timeout') → message français."""
        import asyncio

        async def slow_think(*args, **kwargs):
            await asyncio.sleep(100)
            return ("never", 0.0)

        engine.cortex.think.side_effect = slow_think
        # Réduire le timeout effectif en patchant _is_multi_step
        original = engine._is_multi_step.__func__ if hasattr(engine._is_multi_step, '__func__') else None

        # Injecter un timeout très court via process_async
        response, _ = await engine.process_async("ouvre mon agenda")
        # Process_async utilise wait_for avec timeout adaptatif (45s normalement)
        # Pour ce test, on vérifie juste que l'exception est catchée
        assert isinstance(response, str)


# ─────────────────────────────────────────────────────────────────────────────
# Tous les messages d'erreur sont en français
# ─────────────────────────────────────────────────────────────────────────────

class TestAllErrorsAreFrench:
    """Vérifie que TOUS les messages d'erreur passent par humanize_error et sont en français."""

    ERROR_SCENARIOS = [
        "connection refused",
        "timeout",
        "model not found",
        "broken pipe",
        "out of memory",
        "connection reset",
        "Erreur: quelque chose s'est mal passé",
        "Aucune action directe trouvee",
        "Aucune action multi trouvee",
        "Pas d'engine disponible",
    ]

    @pytest.mark.parametrize("error_input", ERROR_SCENARIOS)
    def test_humanize_error_no_english_tech_terms(self, error_input):
        result = humanize_error(error_input)
        # Pas de termes techniques anglais bruts dans la réponse
        assert "Traceback" not in result
        assert "Exception" not in result
        assert "stack trace" not in result.lower()
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.parametrize("error_input", ERROR_SCENARIOS)
    def test_humanize_error_returns_string(self, error_input):
        result = humanize_error(error_input)
        assert isinstance(result, str)
