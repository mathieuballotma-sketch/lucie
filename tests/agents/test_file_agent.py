"""
Tests unitaires et end-to-end pour FileAgent.

Couverture :
  - can_handle : détection des requêtes fichiers
  - do_action  : liste, écriture, copie, déplacement, suppression, renommage
  - handle     : flow complet avec LLM mocké → JSON → action
  - search     : avec/sans moteur de recherche
  - Routing    : FileAgent bien enregistré dans l'AgentRegistry

Ces tests ne nécessitent PAS Ollama — le LLM est toujours mocké.
"""

from __future__ import annotations

import json
import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.file_agent import FileAgent


# ── Fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture
def agent(tmp_path: Path) -> FileAgent:
    """FileAgent avec LLM mocké et dossier de travail temporaire."""
    llm = MagicMock()
    llm.generate = MagicMock(return_value='{"action": "list", "params": {}}')
    bus = MagicMock()
    return FileAgent(llm, bus, {"working_directory": str(tmp_path)})


# ── can_handle ─────────────────────────────────────────────────────────────────


def test_can_handle_liste(agent: FileAgent) -> None:
    assert agent.can_handle("liste mes fichiers") is True


def test_can_handle_fichier(agent: FileAgent) -> None:
    assert agent.can_handle("ouvre ce fichier") is True


def test_can_handle_dossier(agent: FileAgent) -> None:
    assert agent.can_handle("crée un dossier") is True


def test_can_handle_copie(agent: FileAgent) -> None:
    assert agent.can_handle("copie ce fichier") is True


def test_can_handle_supprime(agent: FileAgent) -> None:
    assert agent.can_handle("supprime le fichier test.txt") is True


def test_can_handle_recherche(agent: FileAgent) -> None:
    assert agent.can_handle("recherche mon contrat") is True


def test_can_handle_trouve(agent: FileAgent) -> None:
    assert agent.can_handle("trouve le fichier budget") is True


def test_can_handle_no_match(agent: FileAgent) -> None:
    assert agent.can_handle("quelle heure est-il ?") is False


def test_can_handle_empty(agent: FileAgent) -> None:
    assert agent.can_handle("") is False


# ── do_action : list ───────────────────────────────────────────────────────────


def test_do_action_list_empty_dir(agent: FileAgent, tmp_path: Path) -> None:
    result = agent.do_action("list", {"path": str(tmp_path)})
    assert "vide" in result.lower()


def test_do_action_list_with_files(agent: FileAgent, tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
    result = agent.do_action("list", {"path": str(tmp_path)})
    assert "hello.txt" in result


def test_do_action_list_nonexistent_dir(agent: FileAgent) -> None:
    result = agent.do_action("list", {"path": "/chemin/qui/nexiste/pas"})
    assert "n'existe pas" in result


def test_do_action_list_defaults_to_working_dir(agent: FileAgent, tmp_path: Path) -> None:
    (tmp_path / "fichier.py").write_text("# code", encoding="utf-8")
    result = agent.do_action("list", {})
    assert "fichier.py" in result


# ── do_action : write ──────────────────────────────────────────────────────────


def test_do_action_write_creates_file(agent: FileAgent, tmp_path: Path) -> None:
    target = str(tmp_path / "test.txt")
    result = agent.do_action("write", {"path": target, "content": "bonjour"})
    assert "✅" in result
    assert Path(target).read_text(encoding="utf-8") == "bonjour"


def test_do_action_write_missing_path(agent: FileAgent) -> None:
    result = agent.do_action("write", {"content": "x"})
    assert "manquant" in result.lower()


def test_do_action_write_missing_content(agent: FileAgent, tmp_path: Path) -> None:
    result = agent.do_action("write", {"path": str(tmp_path / "x.txt")})
    assert "manquant" in result.lower()


def test_do_action_write_creates_parent_dirs(agent: FileAgent, tmp_path: Path) -> None:
    target = str(tmp_path / "subdir" / "deep" / "note.txt")
    result = agent.do_action("write", {"path": target, "content": "profond"})
    assert "✅" in result
    assert Path(target).exists()


# ── do_action : copy ───────────────────────────────────────────────────────────


def test_do_action_copy_success(agent: FileAgent, tmp_path: Path) -> None:
    src = tmp_path / "source.txt"
    dst = str(tmp_path / "destination.txt")
    src.write_text("contenu", encoding="utf-8")
    result = agent.do_action("copy", {"source": str(src), "destination": dst})
    assert "✅" in result
    assert Path(dst).exists()


def test_do_action_copy_missing_source(agent: FileAgent, tmp_path: Path) -> None:
    result = agent.do_action("copy", {
        "source": str(tmp_path / "nope.txt"),
        "destination": str(tmp_path / "dst.txt"),
    })
    assert "n'existe pas" in result


def test_do_action_copy_missing_params(agent: FileAgent) -> None:
    result = agent.do_action("copy", {})
    assert "manquant" in result.lower()


# ── do_action : move ───────────────────────────────────────────────────────────


def test_do_action_move_success(agent: FileAgent, tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    dst = str(tmp_path / "b.txt")
    src.write_text("data", encoding="utf-8")
    result = agent.do_action("move", {"source": str(src), "destination": dst})
    assert "✅" in result
    assert not src.exists()
    assert Path(dst).exists()


def test_do_action_move_missing_source(agent: FileAgent, tmp_path: Path) -> None:
    result = agent.do_action("move", {
        "source": str(tmp_path / "ghost.txt"),
        "destination": str(tmp_path / "dst.txt"),
    })
    assert "n'existe pas" in result


# ── do_action : delete ─────────────────────────────────────────────────────────


def test_do_action_delete_success(agent: FileAgent, tmp_path: Path) -> None:
    f = tmp_path / "to_delete.txt"
    f.write_text("bye", encoding="utf-8")
    result = agent.do_action("delete", {"path": str(f)})
    assert "✅" in result
    assert not f.exists()


def test_do_action_delete_nonexistent(agent: FileAgent, tmp_path: Path) -> None:
    result = agent.do_action("delete", {"path": str(tmp_path / "ghost.txt")})
    assert "n'existe pas" in result


def test_do_action_delete_refuses_directory(agent: FileAgent, tmp_path: Path) -> None:
    result = agent.do_action("delete", {"path": str(tmp_path)})
    assert "dossier" in result.lower() or "autorisé" in result.lower()


# ── do_action : rename ─────────────────────────────────────────────────────────


def test_do_action_rename_success(agent: FileAgent, tmp_path: Path) -> None:
    old = tmp_path / "ancien.txt"
    new = str(tmp_path / "nouveau.txt")
    old.write_text("contenu", encoding="utf-8")
    result = agent.do_action("rename", {"old": str(old), "new": new})
    assert "✅" in result
    assert not old.exists()
    assert Path(new).exists()


def test_do_action_rename_nonexistent(agent: FileAgent, tmp_path: Path) -> None:
    result = agent.do_action("rename", {
        "old": str(tmp_path / "fantome.txt"),
        "new": str(tmp_path / "nouveau.txt"),
    })
    assert "n'existe pas" in result


# ── do_action : unknown ────────────────────────────────────────────────────────


def test_do_action_unknown(agent: FileAgent) -> None:
    result = agent.do_action("teleport", {})
    assert "inconnue" in result.lower()


# ── handle : flow end-to-end avec LLM mocké ───────────────────────────────────


@pytest.mark.asyncio
async def test_handle_list_via_llm(agent: FileAgent, tmp_path: Path) -> None:
    """handle() → LLM retourne JSON list → liste les fichiers."""
    (tmp_path / "rapport.md").write_text("# rapport", encoding="utf-8")

    agent.llm.generate = MagicMock(
        return_value=json.dumps({"action": "list", "params": {"path": str(tmp_path)}})
    )

    result = await agent.handle("liste mes fichiers")
    assert "rapport.md" in result


@pytest.mark.asyncio
async def test_handle_write_via_llm(agent: FileAgent, tmp_path: Path) -> None:
    """handle() → LLM retourne JSON write → crée le fichier."""
    target = str(tmp_path / "note.txt")
    agent.llm.generate = MagicMock(
        return_value=json.dumps({
            "action": "write",
            "params": {"path": target, "content": "hello"},
        })
    )

    result = await agent.handle("crée un fichier note.txt avec hello")
    assert "✅" in result
    assert Path(target).read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_handle_llm_returns_invalid_json_fallback(
    agent: FileAgent, tmp_path: Path
) -> None:
    """Si le LLM répond du texte non-JSON avec 'liste', fallback vers list."""
    (tmp_path / "docs.txt").write_text("contenu", encoding="utf-8")
    agent.working_directory = str(tmp_path)

    agent.llm.generate = MagicMock(return_value="Je vais lister vos fichiers")

    result = await agent.handle("liste les fichiers")
    # Le fallback keyword "liste" → action list → doit afficher le dossier
    assert "docs.txt" in result


@pytest.mark.asyncio
async def test_handle_unknown_action(agent: FileAgent) -> None:
    """LLM retourne action 'unknown' → message explicatif."""
    agent.llm.generate = MagicMock(
        return_value=json.dumps({"action": "unknown", "params": {}})
    )
    result = await agent.handle("fais quelque chose de vague")
    assert "compris" in result.lower() or "unknown" in result.lower()


@pytest.mark.asyncio
async def test_handle_llm_error_graceful(agent: FileAgent) -> None:
    """Si le LLM lève une exception, handle() ne plante pas et retourne une str."""
    agent.llm.generate = MagicMock(side_effect=RuntimeError("Ollama down"))
    # Query sans mot-clé "liste/copie" pour éviter le fallback keyword → retourne
    # soit le message d'erreur LLM soit "Désolé, je n'ai pas compris"
    result = await agent.handle("analyse mon système de fichiers")
    assert isinstance(result, str)
    assert len(result) > 0


# ── search : avec/sans moteur ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_without_engine(agent: FileAgent) -> None:
    """Sans moteur de recherche, search() retourne un message explicatif."""
    result = await agent.search("mon contrat")
    assert "moteur" in result.lower() or "disponible" in result.lower()


@pytest.mark.asyncio
async def test_search_with_mock_engine(agent: FileAgent) -> None:
    """Avec un moteur mocké qui retourne des résultats, search() formate correctement."""
    mock_engine = MagicMock()
    mock_engine.search = AsyncMock(return_value=[
        {"score": 0.92, "file_name": "contrat.pdf", "summary": "Contrat de location", "file_path": "/home/user/docs/contrat.pdf"},
    ])
    agent.search_engine = mock_engine

    result = await agent.search("mon contrat")
    assert "contrat.pdf" in result
    assert "92" in result


@pytest.mark.asyncio
async def test_search_with_no_results(agent: FileAgent) -> None:
    """Moteur disponible mais aucun résultat → message approprié."""
    mock_engine = MagicMock()
    mock_engine.search = AsyncMock(return_value=[])
    agent.search_engine = mock_engine

    result = await agent.search("fichier inexistant xyz")
    assert "aucun" in result.lower() or "trouvé" in result.lower()


# ── Intégration registre : FileAgent bien enregistré ─────────────────────────


def test_file_agent_in_registry() -> None:
    """
    Vérifie que FileAgent est bien déclaré dans AgentRegistry.
    Test sans Ollama : on mock ProviderManager et EventBus.
    """
    pytest.importorskip("ollama", reason="package ollama non installé")
    from app.brain.cortex.registry import AgentRegistry, CRITICAL_AGENTS

    # FileAgent doit être dans les agents critiques
    assert "FileAgent" in CRITICAL_AGENTS

    manager = MagicMock()
    bus = MagicMock()
    event_bus = MagicMock()
    # register_source doit être awaitable
    event_bus.register_source = AsyncMock(return_value="tok-test")

    config = {
        "profile": {"active": "personal"},
        "profiles": {
            "personal": {
                "active_agents": ["FileAgent"],
            }
        },
        "web_search": False,
    }

    registry = AgentRegistry(
        manager=manager,
        bus=bus,
        event_bus=event_bus,
        config=config,
        custom_agents_dir=Path("/tmp/custom_agents_test"),
        cortex_token="test-token",
    )

    assert "FileAgent" in registry.agents
    agent = registry.agents["FileAgent"]
    assert agent.name == "FileAgent"
    assert agent.stability == "core"
