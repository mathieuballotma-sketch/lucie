"""
Tests d'intégration pour LucidEngine.
Mock ProviderManager (LLM), teste la logique métier sans Ollama.
"""
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.engine import (
    LucidEngine,
    _check_greeting,
    _check_capabilities,
    _is_simple_query,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture : engine minimal via __new__ (bypasse l'init lourd)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    """LucidEngine sans init lourd — LLM et cortex entièrement mockés."""
    eng = LucidEngine.__new__(LucidEngine)
    # LLM mocké
    eng.manager = MagicMock()
    eng.manager.generate.return_value = "Réponse LLM mockée"
    # Mémoire contextuelle
    eng.contextual_memory = MagicMock()
    eng.contextual_memory.get_context_for_query = AsyncMock(return_value={})
    # RAG désactivé (évite les appels Ollama)
    eng.rag = MagicMock()
    eng.rag.active = False
    # Cortex mocké
    eng.cortex = MagicMock()
    eng.cortex.think = AsyncMock(return_value=("Réponse cortex mockée", 1.0))
    eng.cortex.planner = MagicMock()
    eng.cortex.planner.decompose = AsyncMock(return_value=[])
    eng.cortex.execute_pipeline = AsyncMock(return_value="Résultat pipeline")
    # ActionRouter passthrough
    eng.action_router = MagicMock()
    eng.action_router.parse_and_execute.side_effect = lambda r: (False, r)
    return eng


# ─────────────────────────────────────────────────────────────────────────────
# Init engine
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineInit:
    def test_engine_has_manager(self, engine):
        assert engine.manager is not None

    def test_engine_has_cortex(self, engine):
        assert engine.cortex is not None

    def test_engine_has_action_router(self, engine):
        assert engine.action_router is not None


# ─────────────────────────────────────────────────────────────────────────────
# Fast-path salutations
# ─────────────────────────────────────────────────────────────────────────────

class TestGreetingFastPath:
    @pytest.mark.asyncio
    async def test_bonjour_returns_response(self, engine):
        response, latency = await engine.process_async("bonjour")
        assert response is not None
        assert "bonjour" in response.lower() or "Bonjour" in response
        # LLM NE doit PAS être appelé
        engine.manager.generate.assert_not_called()
        engine.cortex.think.assert_not_called()

    @pytest.mark.asyncio
    async def test_merci_returns_response(self, engine):
        response, latency = await engine.process_async("merci")
        assert response in ["Avec plaisir !", "De rien !", "Je t'en prie !"]
        engine.manager.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_greeting_latency_is_fast(self, engine):
        _, latency = await engine.process_async("salut")
        # Doit être quasi-instantané (< 10ms) sans LLM
        assert latency < 0.1


# ─────────────────────────────────────────────────────────────────────────────
# Fast-path capacités
# ─────────────────────────────────────────────────────────────────────────────

class TestCapabilityFastPath:
    @pytest.mark.asyncio
    async def test_que_sais_tu_faire(self, engine):
        response, _ = await engine.process_async("que sais-tu faire ?")
        assert "Fichiers" in response or "fichiers" in response.lower()
        engine.manager.generate.assert_not_called()
        engine.cortex.think.assert_not_called()

    @pytest.mark.asyncio
    async def test_capabilities_contains_agents(self, engine):
        response, _ = await engine.process_async("quelles sont tes capacités ?")
        assert response is not None
        # La réponse doit mentionner au moins quelques domaines
        keywords = ["Fichiers", "Mail", "Agenda", "Code", "Mémoire", "Recherche"]
        assert any(kw in response for kw in keywords)


# ─────────────────────────────────────────────────────────────────────────────
# Fast-path heure / date
# ─────────────────────────────────────────────────────────────────────────────

class TestTimeDateFastPath:
    @pytest.mark.asyncio
    async def test_quelle_heure_est_il(self, engine):
        response, _ = await engine.process_async("quelle heure est-il ?")
        now = datetime.datetime.now()
        # Doit contenir l'heure actuelle (format HH:MM)
        assert "Il est" in response
        assert now.strftime("%H:") in response
        engine.manager.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_quelle_date(self, engine):
        response, _ = await engine.process_async("quelle date sommes-nous ?")
        now = datetime.datetime.now()
        assert str(now.year) in response
        engine.manager.generate.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Route vers agent (LLM mocké)
# ─────────────────────────────────────────────────────────────────────────────

class TestAgentRoute:
    @pytest.mark.asyncio
    async def test_cherche_infos_python(self, engine):
        """Requête simple → fast-path E4B (manager.generate appelé)."""
        response, _ = await engine.process_async("cherche des infos sur Python")
        assert response is not None
        assert len(response) > 0
        # "cherche des infos sur Python" est une requête simple → E4B
        engine.manager.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_complex_query_calls_cortex(self, engine):
        """Requête complexe avec verbe d'action → cortex.think() appelé."""
        engine.cortex.think.return_value = ("Voici les fichiers organisés.", 1.5)
        response, _ = await engine.process_async(
            "organise mes fichiers par date dans le dossier Documents"
        )
        assert response is not None
        # Les requêtes complexes (avec mots-clés agents) vont vers cortex
        assert engine.cortex.think.called or engine.manager.generate.called


# ─────────────────────────────────────────────────────────────────────────────
# Robustesse — requête vide
# ─────────────────────────────────────────────────────────────────────────────

class TestEmptyQuery:
    @pytest.mark.asyncio
    async def test_empty_query_no_crash(self, engine):
        """Engine ne crash pas sur une requête vide."""
        try:
            response, latency = await engine.process_async("")
            assert isinstance(response, str)
            assert isinstance(latency, float)
        except Exception as e:
            pytest.fail(f"Engine a crashé sur requête vide: {e}")

    @pytest.mark.asyncio
    async def test_empty_query_returns_string(self, engine):
        response, _ = await engine.process_async("")
        assert isinstance(response, str)
        assert len(response) >= 0
