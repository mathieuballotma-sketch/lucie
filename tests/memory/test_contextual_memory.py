"""
Tests pour la memoire contextuelle persistante.
"""

import pytest

from app.memory.contextual_memory import ContextualMemory


@pytest.fixture
def memory(tmp_path: pytest.TempPathFactory) -> ContextualMemory:
    """Cree une instance ContextualMemory avec DB temporaire."""
    db = str(tmp_path / "ctx.db")  # type: ignore[operator]
    return ContextualMemory(db_path=db)


class TestPreferences:
    """Teste l'apprentissage et la recuperation de preferences."""

    @pytest.mark.asyncio
    async def test_learn_creates_entry(self, memory: ContextualMemory) -> None:
        await memory.learn_preference("communication", "tone", "formel")
        val = await memory.get_preference("communication", "tone")
        assert val == "formel"

    @pytest.mark.asyncio
    async def test_learn_same_key_increases_confidence(self, memory: ContextualMemory) -> None:
        await memory.learn_preference("communication", "tone", "formel", confidence=0.5)
        await memory.learn_preference("communication", "tone", "formel", confidence=0.5)
        # Confiance devrait etre > 0.5 apres confirmation
        prefs = await memory.get_preferences_by_category("communication")
        assert len(prefs) == 1
        assert prefs[0]["confidence"] > 0.5

    @pytest.mark.asyncio
    async def test_contradiction_decreases_confidence(self, memory: ContextualMemory) -> None:
        await memory.learn_preference("communication", "tone", "formel", confidence=0.5)
        await memory.learn_preference("communication", "tone", "informel", confidence=0.5)
        prefs = await memory.get_preferences_by_category("communication")
        assert len(prefs) == 1
        assert prefs[0]["value"] == "informel"
        assert prefs[0]["confidence"] < 0.5

    @pytest.mark.asyncio
    async def test_get_preference_none_if_low_confidence(self, memory: ContextualMemory) -> None:
        await memory.learn_preference("test", "key", "val", confidence=0.2)
        val = await memory.get_preference("test", "key")
        assert val is None

    @pytest.mark.asyncio
    async def test_get_preference_nonexistent(self, memory: ContextualMemory) -> None:
        val = await memory.get_preference("nope", "nope")
        assert val is None


class TestPatterns:
    """Teste l'apprentissage de patterns."""

    @pytest.mark.asyncio
    async def test_learn_pattern(self, memory: ContextualMemory) -> None:
        await memory.learn_pattern("hourly", {"hour": 9, "action": "check_mail"})
        patterns = await memory.get_patterns("hourly")
        assert len(patterns) == 1
        assert patterns[0]["data"]["hour"] == 9

    @pytest.mark.asyncio
    async def test_learn_pattern_increases_frequency(self, memory: ContextualMemory) -> None:
        data = {"hour": 9, "action": "check_mail"}
        await memory.learn_pattern("hourly", data)
        await memory.learn_pattern("hourly", data)
        patterns = await memory.get_patterns("hourly")
        assert patterns[0]["frequency"] == 2


class TestContext:
    """Teste la generation de contexte."""

    @pytest.mark.asyncio
    async def test_get_context_for_query(self, memory: ContextualMemory) -> None:
        await memory.learn_preference("communication", "tone", "formel")
        await memory.learn_preference("content", "domaine", "cybersecurite")
        ctx = await memory.get_context_for_query("test")
        assert isinstance(ctx, dict)

    @pytest.mark.asyncio
    async def test_get_context_empty(self, memory: ContextualMemory) -> None:
        ctx = await memory.get_context_for_query("test")
        assert isinstance(ctx, dict)
        assert len(ctx) == 0
