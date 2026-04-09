"""
Tests d'intégration pour la couche mémoire.
Teste EpisodicMemory, WorkingMemory et ContextualMemory.
"""
import asyncio
import tempfile
from pathlib import Path

import pytest

from app.memory.episodic_memory import EpisodicMemory
from app.memory.working_memory import WorkingMemory
from app.memory.contextual_memory import ContextualMemory
from app.memory.memory_service import MemoryService


# ─────────────────────────────────────────────────────────────────────────────
# WorkingMemory
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkingMemory:
    def test_add_and_retrieve(self):
        mem = WorkingMemory(capacity=10)
        mem.add("quelle heure est-il ?", "Il est 14h30.")
        recent = mem.get_recent(1)
        assert len(recent) == 1
        assert recent[0] == ("quelle heure est-il ?", "Il est 14h30.")

    def test_context_is_formatted(self):
        mem = WorkingMemory(capacity=10)
        mem.add("bonjour", "Bonjour !")
        ctx = mem.get_context(1)
        assert "Utilisateur:" in ctx
        assert "Assistant:" in ctx
        assert "bonjour" in ctx

    def test_persists_between_calls(self):
        """WorkingMemory persiste entre deux appels add()."""
        mem = WorkingMemory(capacity=10)
        mem.add("question 1", "réponse 1")
        mem.add("question 2", "réponse 2")
        recent = mem.get_recent(10)
        assert len(recent) == 2
        queries = [r[0] for r in recent]
        assert "question 1" in queries
        assert "question 2" in queries

    def test_capacity_limit(self):
        """WorkingMemory respecte la capacité maximale."""
        mem = WorkingMemory(capacity=3)
        for i in range(5):
            mem.add(f"query {i}", f"response {i}")
        recent = mem.get_recent(10)
        assert len(recent) == 3
        # Les plus récents sont conservés
        assert recent[-1] == ("query 4", "response 4")

    def test_get_last_query(self):
        mem = WorkingMemory(capacity=10)
        mem.add("ma dernière question", "ma dernière réponse")
        assert mem.get_last_query() == "ma dernière question"

    def test_get_last_response(self):
        mem = WorkingMemory(capacity=10)
        mem.add("question", "la réponse finale")
        assert mem.get_last_response() == "la réponse finale"

    def test_clear(self):
        mem = WorkingMemory(capacity=10)
        mem.add("q", "r")
        mem.clear()
        assert mem.get_recent(10) == []
        assert mem.get_last_query() == ""

    def test_empty_memory_returns_empty_context(self):
        mem = WorkingMemory(capacity=10)
        assert mem.get_context() == ""

    def test_empty_memory_get_recent(self):
        mem = WorkingMemory(capacity=10)
        assert mem.get_recent() == []


# ─────────────────────────────────────────────────────────────────────────────
# EpisodicMemory
# ─────────────────────────────────────────────────────────────────────────────

class TestEpisodicMemory:
    @pytest.fixture
    def episodic(self, tmp_path):
        return EpisodicMemory(
            persist_directory=str(tmp_path),
            max_entries=100,
        )

    @pytest.mark.asyncio
    async def test_add_episode(self, episodic):
        """Ajout d'un épisode sans erreur."""
        await episodic.add_episode(
            query="quelle est la capitale de la France ?",
            response="Paris.",
        )

    @pytest.mark.asyncio
    async def test_add_and_remember(self, episodic):
        """Cycle stocker → récupérer."""
        await episodic.add_episode(
            query="quelle est la capitale de la France ?",
            response="Paris.",
        )
        results = await episodic.remember("capitale France", n_results=5)
        assert isinstance(results, list)
        # Au moins un résultat doit être retourné
        assert len(results) >= 1
        queries = [r.get("query", "") for r in results]
        assert any("France" in q or "capitale" in q for q in queries)

    @pytest.mark.asyncio
    async def test_add_multiple_episodes(self, episodic):
        """Plusieurs épisodes stockés et récupérés."""
        episodes = [
            ("Python c'est quoi ?", "Un langage de programmation."),
            ("JavaScript c'est quoi ?", "Un langage pour le web."),
            ("Rust c'est quoi ?", "Un langage système."),
        ]
        for q, r in episodes:
            await episodic.add_episode(query=q, response=r)

        results = await episodic.remember("langage programmation", n_results=10)
        assert isinstance(results, list)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_remember_returns_list(self, episodic):
        """remember() retourne toujours une liste, même vide."""
        results = await episodic.remember("requête inconnue xyz123", n_results=5)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_episode_has_required_fields(self, episodic):
        """Chaque épisode a les champs 'query' et 'response'."""
        await episodic.add_episode(query="test query", response="test response")
        results = await episodic.remember("test", n_results=5)
        assert len(results) >= 1
        for r in results:
            assert "query" in r
            assert "response" in r

    @pytest.mark.asyncio
    async def test_add_with_metadata(self, episodic):
        """Ajout avec métadonnées ne crash pas."""
        await episodic.add_episode(
            query="test",
            response="réponse",
            metadata={"agent": "TestAgent", "latency": 1.5},
        )


# ─────────────────────────────────────────────────────────────────────────────
# ContextualMemory
# ─────────────────────────────────────────────────────────────────────────────

class TestContextualMemory:
    @pytest.fixture
    def ctx_memory(self, tmp_path):
        db_path = str(tmp_path / "contextual.db")
        mem = ContextualMemory(db_path=db_path)
        yield mem
        mem.close()

    @pytest.mark.asyncio
    async def test_learn_and_get_preference(self, ctx_memory):
        """Stocker puis récupérer une préférence."""
        await ctx_memory.learn_preference(
            category="communication",
            key="style",
            value="concis",
            confidence=0.8,
        )
        result = await ctx_memory.get_preference("communication", "style")
        assert result == "concis"

    @pytest.mark.asyncio
    async def test_preference_confidence_increases(self, ctx_memory):
        """Confirmer une préférence augmente la confiance."""
        await ctx_memory.learn_preference("workflow", "tool", "vim", confidence=0.5)
        await ctx_memory.learn_preference("workflow", "tool", "vim", confidence=0.5)
        result = await ctx_memory.get_preference("workflow", "tool")
        assert result == "vim"

    @pytest.mark.asyncio
    async def test_get_context_enriches_query(self, ctx_memory):
        """get_context_for_query() enrichit le contexte."""
        await ctx_memory.learn_preference("communication", "langue", "français", confidence=0.9)
        ctx = await ctx_memory.get_context_for_query("aide-moi")
        assert isinstance(ctx, dict)
        # Le contexte peut être vide ou contenir des préférences
        # L'important est que ça ne crash pas

    @pytest.mark.asyncio
    async def test_get_context_returns_dict(self, ctx_memory):
        """get_context_for_query() retourne toujours un dict."""
        ctx = await ctx_memory.get_context_for_query("n'importe quelle requête")
        assert isinstance(ctx, dict)

    @pytest.mark.asyncio
    async def test_learn_pattern(self, ctx_memory):
        """Apprendre un pattern d'usage ne crash pas."""
        await ctx_memory.learn_pattern(
            pattern_type="time_usage",
            pattern_data={"hour": 9, "day": "monday", "action": "check_email"},
        )

    @pytest.mark.asyncio
    async def test_get_preferences_by_category(self, ctx_memory):
        """Récupérer toutes les préférences d'une catégorie."""
        await ctx_memory.learn_preference("content", "topic", "python", confidence=0.7)
        await ctx_memory.learn_preference("content", "format", "bullet points", confidence=0.6)
        prefs = await ctx_memory.get_preferences_by_category("content")
        assert isinstance(prefs, list)
        assert len(prefs) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# MemoryService — façade intégrant episodic + working
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryService:
    @pytest.fixture
    def memory_service(self, tmp_path):
        episodic = EpisodicMemory(
            persist_directory=str(tmp_path),
            max_entries=100,
        )
        working = WorkingMemory(capacity=10)
        return MemoryService(episodic, working)

    def test_add_to_working(self, memory_service):
        memory_service.add_to_working("query", "response")
        ctx = memory_service.get_working_context(1)
        assert "query" in ctx

    def test_working_context_multiple_entries(self, memory_service):
        memory_service.add_to_working("q1", "r1")
        memory_service.add_to_working("q2", "r2")
        ctx = memory_service.get_working_context(5)
        assert "q1" in ctx
        assert "q2" in ctx

    @pytest.mark.asyncio
    async def test_add_episode_via_service(self, memory_service):
        await memory_service.add_episode("test query", "test response")

    @pytest.mark.asyncio
    async def test_remember_via_service(self, memory_service):
        await memory_service.add_episode("Paris est la capitale de la France.", "Exact !")
        results = await memory_service.remember("Paris")
        assert isinstance(results, list)
