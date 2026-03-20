# tests/integration/test_cortex.py
"""
Tests d'intégration pour le cortex frontal (FrontalCortex).
Vérifie l'initialisation, le routage et les fallbacks.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.brain.cortex import (
    EmbeddingClassifier,
    FrontalCortex,
)
from app.brain.synapses.event_bus import EventBus
from app.memory import MemoryService
from app.providers.manager import ProviderManager
from app.services.prompt_cache import PromptCache
from app.core.elasticity import ElasticityEngine


# -----------------------------------------------------------------------------
# Mocks pour les dépendances lourdes
# -----------------------------------------------------------------------------
@pytest.fixture
def mock_embedding_classifier(monkeypatch):
    """Remplace le vrai EmbeddingClassifier par un mock."""

    class MockEmbeddingClassifier:
        def __init__(self, *args, **kwargs):
            self.confidence_threshold = 0.7
            self._ready = True
            self._examples = []
            self._model = MagicMock()

        def initialize(self):
            return True

        @property
        def is_ready(self):
            return self._ready

        @property
        def example_count(self):
            return len(self._examples)

        def classify(self, query: str):
            return None, 0.0

    monkeypatch.setattr("app.brain.cortex.EmbeddingClassifier", MockEmbeddingClassifier)


@pytest.fixture
def mock_provider_manager():
    """Mock du ProviderManager (LLM)."""
    manager = MagicMock(spec=ProviderManager)
    manager.generate.return_value = "Réponse simulée du LLM"
    return manager


@pytest.fixture
def mock_bus():
    """Mock du bus synaptique."""
    bus = MagicMock()
    bus.set = MagicMock()
    return bus


@pytest.fixture
def mock_event_bus():
    """Mock du bus d'événements."""
    event_bus = AsyncMock(spec=EventBus)
    event_bus.publish = AsyncMock()
    event_bus.register_source = AsyncMock(return_value="mock-token")
    event_bus.subscribe = AsyncMock()
    return event_bus


@pytest.fixture
def mock_prompt_cache():
    """Mock du cache de prompts."""
    cache = MagicMock(spec=PromptCache)
    cache.get.return_value = None
    cache.put = MagicMock()
    cache.get_plan = MagicMock(return_value=None)
    cache.put_plan = MagicMock()
    return cache


@pytest.fixture
def mock_memory_service():
    """Mock du service de mémoire."""
    memory = MagicMock(spec=MemoryService)
    memory.get_working_context.return_value = "contexte factice"
    memory.add_to_working = MagicMock()
    memory.add_episode = AsyncMock()
    return memory


@pytest.fixture
def mock_elasticity_engine():
    """Mock du moteur d'élasticité."""
    engine = MagicMock(spec=ElasticityEngine)
    return engine


@pytest.fixture
def mock_agents(monkeypatch):
    """Mock des agents pour éviter de les instancier réellement."""
    mock_reminder = MagicMock()
    mock_knowledge = MagicMock()
    mock_document = MagicMock()
    mock_text_extractor = MagicMock()
    mock_computer_control = MagicMock()

    mock_reminder.name = "ReminderAgent"
    mock_knowledge.name = "KnowledgeAgent"
    mock_document.name = "DocumentAgent"
    mock_text_extractor.name = "TextExtractorAgent"
    mock_computer_control.name = "ComputerControlAgent"

    mock_reminder.get_tools.return_value = []
    mock_knowledge.get_tools.return_value = []
    mock_document.get_tools.return_value = []
    mock_text_extractor.get_tools.return_value = []
    mock_computer_control.get_tools.return_value = []

    mock_reminder.execute_tool = AsyncMock(return_value="ok")
    mock_knowledge.execute_tool = AsyncMock(return_value="ok")
    mock_document.execute_tool = AsyncMock(return_value="ok")
    mock_text_extractor.execute_tool = AsyncMock(return_value="ok")
    mock_computer_control.execute_tool = AsyncMock(return_value="ok")

    monkeypatch.setattr(
        "app.brain.cortex.registry.ReminderAgent", lambda *args, **kwargs: mock_reminder
    )
    monkeypatch.setattr(
        "app.brain.cortex.registry.KnowledgeAgent", lambda *args, **kwargs: mock_knowledge
    )
    monkeypatch.setattr(
        "app.brain.cortex.registry.DocumentAgent", lambda *args, **kwargs: mock_document
    )
    monkeypatch.setattr(
        "app.brain.cortex.registry.TextExtractorAgent", lambda *args, **kwargs: mock_text_extractor
    )
    monkeypatch.setattr(
        "app.brain.cortex.registry.ComputerControlAgent", lambda *args, **kwargs: mock_computer_control
    )

    return {
        "reminder": mock_reminder,
        "knowledge": mock_knowledge,
        "document": mock_document,
        "text_extractor": mock_text_extractor,
        "computer_control": mock_computer_control,
    }


# -----------------------------------------------------------------------------
# Tests du cortex
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cortex_initialization(
    mock_provider_manager,
    mock_bus,
    mock_event_bus,
    mock_prompt_cache,
    mock_memory_service,
    mock_elasticity_engine,
    mock_agents,
    mock_embedding_classifier,
):
    """Teste que le cortex s'initialise correctement avec les mocks."""
    config = {
        "web_search": False,
        "api_keys": {},
        "vision": {},
        "enable_memory": True,
        "enable_elasticity": True,
        "plan_timeout": 30.0,
        "max_plan_retries": 1,
        "retrain_classifier": False,
    }
    cortex = FrontalCortex(
        manager=mock_provider_manager,
        bus=mock_bus,
        event_bus=mock_event_bus,
        prompt_cache=mock_prompt_cache,
        memory_service=mock_memory_service,
        elasticity_engine=mock_elasticity_engine,
        config=config,
    )
    assert cortex is not None
    assert len(cortex.agent_registry.agents) > 0
    assert cortex.classifier is not None
    assert cortex.path_manager is not None


@pytest.mark.asyncio
async def test_cortex_think_greeting(
    mock_provider_manager,
    mock_bus,
    mock_event_bus,
    mock_prompt_cache,
    mock_memory_service,
    mock_elasticity_engine,
    mock_agents,
    mock_embedding_classifier,
):
    """Teste que think() retourne un tuple (str, float)."""
    mock_provider_manager.generate.return_value = "Salut !"
    cortex = FrontalCortex(
        manager=mock_provider_manager,
        bus=mock_bus,
        event_bus=mock_event_bus,
        prompt_cache=mock_prompt_cache,
        memory_service=mock_memory_service,
        elasticity_engine=mock_elasticity_engine,
        config={"web_search": False},
    )

    # Forcer tous les chemins à appeler llm directement
    async def mock_llm_path(q=None):
        return mock_provider_manager.generate(q)

    cortex.path_manager.select_paths = AsyncMock(return_value=[("llm", mock_llm_path)])

    response, duration = await cortex.think("bonjour")

    assert isinstance(response, str)
    assert isinstance(duration, float)
    assert duration >= 0.0


@pytest.mark.asyncio
async def test_cortex_think_direct_action(
    mock_provider_manager,
    mock_bus,
    mock_event_bus,
    mock_prompt_cache,
    mock_memory_service,
    mock_elasticity_engine,
    mock_agents,
    mock_embedding_classifier,
):
    """Teste qu'un chemin direct retourne la bonne réponse."""
    cortex = FrontalCortex(
        manager=mock_provider_manager,
        bus=mock_bus,
        event_bus=mock_event_bus,
        prompt_cache=mock_prompt_cache,
        memory_service=mock_memory_service,
        elasticity_engine=mock_elasticity_engine,
        config={"web_search": False},
    )

    async def mock_direct_path(q=None):
        return "Application ouverte"

    cortex.path_manager.select_paths = AsyncMock(return_value=[("direct", mock_direct_path)])

    response, duration = await cortex.think("ouvre notes")

    assert response == "Application ouverte"
    assert isinstance(duration, float)


@pytest.mark.asyncio
async def test_cortex_think_all_paths_fail(
    mock_provider_manager,
    mock_bus,
    mock_event_bus,
    mock_prompt_cache,
    mock_memory_service,
    mock_elasticity_engine,
    mock_agents,
    mock_embedding_classifier,
):
    """Teste que si tous les chemins échouent, le fallback sécurisé est utilisé."""
    cortex = FrontalCortex(
        manager=mock_provider_manager,
        bus=mock_bus,
        event_bus=mock_event_bus,
        prompt_cache=mock_prompt_cache,
        memory_service=mock_memory_service,
        elasticity_engine=mock_elasticity_engine,
        config={"web_search": False},
    )
    cortex._safe_fallback = MagicMock(return_value="fallback exécuté")

    async def failing_path(q=None):
        raise Exception("fail")

    cortex.path_manager.select_paths = AsyncMock(return_value=[
        ("direct", failing_path),
        ("llm", failing_path),
    ])

    response, duration = await cortex.think("n'importe quoi")

    cortex._safe_fallback.assert_called_once_with("n'importe quoi")
    assert response == "fallback exécuté"


@pytest.mark.asyncio
async def test_cortex_routing_with_mock_classifier(
    mock_provider_manager,
    mock_bus,
    mock_event_bus,
    mock_prompt_cache,
    mock_memory_service,
    mock_elasticity_engine,
    mock_agents,
    mock_embedding_classifier,
):
    """Teste que path_manager.select_paths peut être mocké pour contrôler le routage."""
    cortex = FrontalCortex(
        manager=mock_provider_manager,
        bus=mock_bus,
        event_bus=mock_event_bus,
        prompt_cache=mock_prompt_cache,
        memory_service=mock_memory_service,
        elasticity_engine=mock_elasticity_engine,
        config={"web_search": False},
    )

    async def mock_action_path(q=None):
        return "direct"

    cortex.path_manager.select_paths = AsyncMock(return_value=[("direct", mock_action_path)])

    response, duration = await cortex.think("ouvre notes")

    assert response == "direct"
    assert isinstance(duration, float)
