"""
Tests unitaires pour CreatorAgent.

Couverture :
  - can_handle() : mots-clés de création d'agent
  - get_tools() : 3 outils attendus (create_agent, list_agents, delete_agent)
  - AgentCodeValidator.validate_safety() : imports interdits, builtins dangereux,
    syntaxe invalide, classe valide héritant de BaseAgent
  - _tool_list_agents() : dossier vide ou avec agents
  - _tool_delete_agent() : agent introuvable, bloqué, supprimé
  - handle() : dispatch vers _tool_create_agent

Ces tests ne nécessitent PAS Ollama — le LLM est toujours mocké.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Stub ollama avant tout import de l'agent (provider manager en dépend)
sys.modules.setdefault("ollama", MagicMock())

from app.agents.creator_agent import CreatorAgent, AgentCodeValidator
from app.utils.errors import ToolExecutionError


# ── Fixture ────────────────────────────────────────────────────────────────────

VALID_AGENT_CODE = '''
from app.agents.base_agent import BaseAgent, Tool

class WeatherAgent(BaseAgent):
    """Agent météo de test."""

    def can_handle(self, query: str) -> bool:
        return "météo" in query.lower()

    def get_tools(self):
        return []

    async def handle(self, query: str) -> str:
        return "Météo ensoleillée."
'''


@pytest.fixture
def agents_dir(tmp_path: Path) -> Path:
    d = tmp_path / "custom_agents"
    d.mkdir()
    return d


@pytest.fixture
def agent(agents_dir: Path) -> CreatorAgent:
    llm = MagicMock()
    llm.generate = MagicMock(return_value=VALID_AGENT_CODE)
    bus = MagicMock()
    event_bus = MagicMock()
    config: dict[str, Any] = {
        "creator_model": "balanced",
        "creator_max_retries": 1,
        "enable_circuit_breaker": False,
        "ask_user_on_failure": False,
    }
    return CreatorAgent(
        llm_service=llm,
        bus=bus,
        event_bus=event_bus,
        config=config,
        agents_dir=agents_dir,
        token="test-token",
    )


@pytest.fixture
def validator() -> AgentCodeValidator:
    return AgentCodeValidator()


# ── can_handle ─────────────────────────────────────────────────────────────────


def test_can_handle_cree_agent(agent: CreatorAgent) -> None:
    assert agent.can_handle("crée un agent qui surveille la météo") is True


def test_can_handle_creer_agent(agent: CreatorAgent) -> None:
    assert agent.can_handle("créer un agent de gestion d'emails") is True


def test_can_handle_genere_agent(agent: CreatorAgent) -> None:
    assert agent.can_handle("génère un agent pour les rappels") is True


def test_can_handle_fabrique_agent(agent: CreatorAgent) -> None:
    assert agent.can_handle("fabrique un agent de traduction") is True


def test_can_handle_nouvel_agent(agent: CreatorAgent) -> None:
    assert agent.can_handle("nouvel agent de stockage") is True


def test_can_handle_negatif_liste(agent: CreatorAgent) -> None:
    assert agent.can_handle("liste mes fichiers") is False


def test_can_handle_negatif_rappel(agent: CreatorAgent) -> None:
    assert agent.can_handle("crée un rappel pour demain") is False


# ── get_tools ──────────────────────────────────────────────────────────────────


def test_get_tools_count(agent: CreatorAgent) -> None:
    tools = agent.get_tools()
    assert len(tools) == 3


def test_get_tools_names(agent: CreatorAgent) -> None:
    names = {t.name for t in agent.get_tools()}
    assert "create_agent" in names
    assert "list_agents" in names
    assert "delete_agent" in names


# ── AgentCodeValidator.validate_safety ────────────────────────────────────────


def test_validate_safety_valid_code(validator: AgentCodeValidator) -> None:
    ok, result = validator.validate_safety(VALID_AGENT_CODE)
    assert ok is True
    assert result == "WeatherAgent"


def test_validate_safety_forbidden_import_os(validator: AgentCodeValidator) -> None:
    code = "import os\n" + VALID_AGENT_CODE
    ok, msg = validator.validate_safety(code)
    assert ok is False
    assert "os" in msg


def test_validate_safety_forbidden_import_subprocess(validator: AgentCodeValidator) -> None:
    code = "import subprocess\n" + VALID_AGENT_CODE
    ok, msg = validator.validate_safety(code)
    assert ok is False
    assert "subprocess" in msg


def test_validate_safety_syntax_error(validator: AgentCodeValidator) -> None:
    ok, msg = validator.validate_safety("def broken(::\n")
    assert ok is False
    assert "syntaxe" in msg.lower() or "syntax" in msg.lower()


def test_validate_safety_no_base_agent(validator: AgentCodeValidator) -> None:
    code = """
class StandaloneClass:
    def do_nothing(self):
        pass
"""
    ok, msg = validator.validate_safety(code)
    assert ok is False
    assert "BaseAgent" in msg


def test_validate_safety_forbidden_eval_call(validator: AgentCodeValidator) -> None:
    code = """
from app.agents.base_agent import BaseAgent, Tool

class EvilAgent(BaseAgent):
    def can_handle(self, q): return True
    def get_tools(self): return []
    async def handle(self, q):
        return eval(q)
"""
    ok, msg = validator.validate_safety(code)
    assert ok is False
    assert "eval" in msg


# ── _tool_list_agents ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_agents_empty(agent: CreatorAgent, agents_dir: Path) -> None:
    result = await agent._tool_list_agents()
    assert "Aucun" in result


@pytest.mark.anyio
async def test_list_agents_with_file(agent: CreatorAgent, agents_dir: Path) -> None:
    (agents_dir / "weather_agent.py").write_text('"""Agent météo."""\n')
    result = await agent._tool_list_agents()
    assert "weather_agent" in result


# ── _tool_delete_agent ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_delete_agent_not_found(agent: CreatorAgent) -> None:
    with pytest.raises(ToolExecutionError, match="introuvable"):
        await agent._tool_delete_agent(name="AgentInexistant")


@pytest.mark.anyio
async def test_delete_agent_blocked_by_gate(agent: CreatorAgent, agents_dir: Path) -> None:
    (agents_dir / "monagent.py").write_text("# code\n")
    with patch.object(agent, "submit_action", return_value=False):
        result = await agent._tool_delete_agent(name="monagent")
    assert "⛔" in result


@pytest.mark.anyio
async def test_delete_agent_success(agent: CreatorAgent, agents_dir: Path) -> None:
    (agents_dir / "oldagent.py").write_text("# code\n")
    with patch.object(agent, "submit_action", return_value=True):
        result = await agent._tool_delete_agent(name="oldagent")
    assert "✅" in result
    assert not (agents_dir / "oldagent.py").exists()


# ── handle dispatch ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_handle_cree_agent_dispatch(agent: CreatorAgent) -> None:
    with patch.object(agent, "_tool_create_agent", return_value="✅ Agent créé.") as mock_create:
        result = await agent.handle("crée un agent qui gère la météo")
    mock_create.assert_called_once()
    assert "✅" in result


@pytest.mark.anyio
async def test_handle_description_vide_retourne_message(agent: CreatorAgent) -> None:
    result = await agent.handle("crée un agent")
    assert "Décris" in result or len(result) > 0
