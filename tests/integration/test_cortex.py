# tests/integration/test_cortex.py
"""
Tests d'intégration pour le cortex frontal (FrontalCortex).
Vérifie la classification, le routage et l'exécution des chemins.
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
    """Remplace le vrai EmbeddingClassifier par un mock synchrone."""

    class MockEmbeddingClassifier:
        def __init__(self, *args, **kwargs):
            self.confidence_threshold = 0.7
            self.is_trained = True

        async def predict(self, query: str):
            q = query.lower()
            if "bonjour" in q or "salut" in q:
                return "greeting", 0.95
            if "ouvre" in q or "lance" in q:
                if " et " in q or " puis " in q:
                    return "multi_action", 0.85
                return "action", 0.9
            if "mail" in q or "email" in q:
                return "mail", 0.8
            if "safari" in q or "internet" in q:
                return "safari", 0.8
            if "organise" in q or "côte à côte" in q:
                return "arrange", 0.8
            if len(q.split()) > 5:
                return "complex", 0.6
            return "simple", 0.5

        def _fallback(self, query: str):
            q = query.lower()
            if "ouvre" in q:
                return "action"
            return "simple"

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
    memory.add_episode = AsyncMock()  # async — requis par asyncio.run_coroutine_threadsafe
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

    # Les noms doivent être des chaînes pour que le registre les indexe correctement
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
        "app.brain.cortex.ReminderAgent", lambda *args, **kwargs: mock_reminder
    )
    monkeypatch.setattr(
        "app.brain.cortex.KnowledgeAgent", lambda *args, **kwargs: mock_knowledge
    )
    monkeypatch.setattr(
        "app.brain.cortex.DocumentAgent", lambda *args, **kwargs: mock_document
    )
    monkeypatch.setattr(
        "app.brain.cortex.TextExtractorAgent", lambda *args, **kwargs: mock_text_extractor
    )
    monkeypatch.setattr(
        "app.brain.cortex.ComputerControlAgent", lambda *args, **kwargs: mock_computer_control
    )

    return {
        "reminder": mock_reminder,
        "knowledge": mock_knowledge,
        "document": mock_document,
        "text_extractor": mock_text_extractor,
        "computer_control": mock_computer_control,
    }


@pytest.fixture
def cortex_with_mock_classifier(
    mock_provider_manager,
    mock_bus,
    mock_event_bus,
    mock_prompt_cache,
    mock_memory_service,
    mock_elasticity_engine,
    mock_agents,
):
    """Crée un cortex avec un classifieur mocké pour tester le routage."""
    mock_classifier = MagicMock()
    mock_classifier.predict = AsyncMock(return_value=("action", 0.95))
    mock_classifier.confidence_threshold = 0.7
    mock_classifier._fallback = MagicMock(return_value="action")
    mock_classifier.is_trained = True

    cortex = FrontalCortex(
        manager=mock_provider_manager,
        bus=mock_bus,
        event_bus=mock_event_bus,
        prompt_cache=mock_prompt_cache,
        memory_service=mock_memory_service,
        elasticity_engine=mock_elasticity_engine,
        config={},
    )
    # Remplacer le classifieur par notre mock
    cortex.classifier = mock_classifier
    cortex.action_selector.classifier = mock_classifier
    cortex.path_manager.classifier = mock_classifier
    return cortex


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
        "web_search": True,
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
    # 5 mocked agents + FileAgent + CreatorAgent = 7
    assert len(cortex.agent_registry.agents) == 7
    assert cortex.classifier is not None


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
    """Teste qu'une requête de salutation retourne une réponse du LLM."""
    mock_provider_manager.generate.return_value = "Salut !"
    cortex = FrontalCortex(
        manager=mock_provider_manager,
        bus=mock_bus,
        event_bus=mock_event_bus,
        prompt_cache=mock_prompt_cache,
        memory_service=mock_memory_service,
        elasticity_engine=mock_elasticity_engine,
        config={},
    )
    # Désactiver l'exploration aléatoire pour avoir un comportement déterministe
    cortex.action_selector.epsilon = 0

    response, duration = await cortex.think("bonjour")

    # llm_nano est priorité 1 pour "greeting" → appelle manager.generate
    mock_provider_manager.generate.assert_called()
    assert "Salut !" in response
    assert duration < 5.0


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
    """Teste qu'une requête d'action simple (ouvre notes) passe par direct_action."""
    cortex = FrontalCortex(
        manager=mock_provider_manager,
        bus=mock_bus,
        event_bus=mock_event_bus,
        prompt_cache=mock_prompt_cache,
        memory_service=mock_memory_service,
        elasticity_engine=mock_elasticity_engine,
        config={},
    )
    # Désactiver l'exploration aléatoire
    cortex.action_selector.epsilon = 0
    # Configurer le mock ComputerControlAgent pour retourner une réponse spécifique
    mock_agents["computer_control"].execute_tool = AsyncMock(return_value="Application ouverte")

    response, duration = await cortex.think("ouvre notes")

    # direct_action est priorité 1 pour "action" → ComputerControlAgent.open_application
    mock_agents["computer_control"].execute_tool.assert_called()
    assert response == "Application ouverte"


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
        config={},
    )
    cortex._safe_fallback = MagicMock(return_value="fallback exécuté")

    async def failing_path(query: str) -> str:
        raise Exception("fail")

    # Remplacer select_paths pour que tous les chemins échouent
    cortex.path_manager.select_paths = AsyncMock(return_value=[
        ("direct_action", failing_path),
        ("llm_nano", failing_path),
    ])

    response, duration = await cortex.think("n'importe quoi")

    cortex._safe_fallback.assert_called_once_with("n'importe quoi")
    assert response == "fallback exécuté"


@pytest.mark.asyncio
async def test_cortex_routing_with_mock_classifier(cortex_with_mock_classifier, mock_agents):
    """Teste que le cortex utilise le classifieur pour router vers direct_action."""
    cortex = cortex_with_mock_classifier
    cortex.action_selector.epsilon = 0

    # Le classifieur retourne "action" → "direct_action" est priorité 1
    # direct_action → ComputerControlAgent.open_application pour "ouvre notes"
    mock_agents["computer_control"].execute_tool = AsyncMock(return_value="direct")

    # Simuler que le classifieur retourne "action"
    cortex.classifier.predict.return_value = ("action", 0.95)

    response, duration = await cortex.think("ouvre notes")

    # Vérifier que ComputerControlAgent.execute_tool a été appelé
    mock_agents["computer_control"].execute_tool.assert_called()
    assert response == "direct"
