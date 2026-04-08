"""
Tests unitaires pour KnowledgeAgent — recherche web + synthèse LLM.

Pilier #3 BMAD — Recherche Web.

Couverture :
  - can_handle() avec différents patterns FR/EN
  - _tool_web_search() avec mock WebSearch
  - _tool_fetch_page() avec mock HTML (pas de vrais appels réseau)
  - _tool_answer_question() avec mock LLM
  - handle() flow complet (4 étapes)
  - Gestion d'erreurs (timeout, réseau down, page introuvable)
  - Troncature du contenu long

Ces tests ne nécessitent PAS Ollama — le LLM est toujours mocké.
Pas de vrais appels réseau — requests.get est toujours patché.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.knowledge_agent import KnowledgeAgent


# ── Fixtures ───────────────────────────────────────────────────────────────────

FAKE_HTML = """<html>
<head><title>Test Page</title></head>
<body>
  <nav>Navigation menu inutile</nav>
  <script>console.log('js interdit');</script>
  <style>.hidden { display: none; }</style>
  <header>En-tête à supprimer</header>
  <main>
    <h1>Article principal de test</h1>
    <p>Contenu utile de la page web pour les tests unitaires.</p>
    <p>Deuxième paragraphe avec davantage d'information pertinente.</p>
  </main>
  <footer>Pied de page à supprimer</footer>
</body>
</html>
"""

FAKE_SEARCH_RESULTS = [
    {
        "title": "Python (langage de programmation)",
        "body": "Python est un langage de programmation interprété, multi-paradigme...",
        "url": "https://fr.wikipedia.org/wiki/Python_(langage)",
    },
    {
        "title": "Apprendre Python",
        "body": "Guide complet pour apprendre Python en partant de zéro.",
        "url": "https://example.com/python-guide",
    },
    {
        "title": "Python documentation officielle",
        "body": "Documentation officielle du langage Python.",
        "url": "https://docs.python.org/fr/",
    },
]


@pytest.fixture
def web_search_mock() -> MagicMock:
    """Service WebSearch mocké qui retourne des résultats fictifs."""
    mock = MagicMock()
    mock.search = AsyncMock(return_value=FAKE_SEARCH_RESULTS)
    return mock


@pytest.fixture
def agent(web_search_mock: MagicMock) -> KnowledgeAgent:
    """KnowledgeAgent avec LLM et WebSearch mockés, sans Ollama ni réseau."""
    llm = MagicMock()
    llm.generate = MagicMock(return_value="Réponse synthétisée par le LLM mocké.")
    bus = MagicMock()
    config: dict[str, Any] = {
        "max_results": 3,
        "web_search": web_search_mock,
    }
    return KnowledgeAgent(llm, bus, config)


@pytest.fixture
def agent_no_web() -> KnowledgeAgent:
    """KnowledgeAgent sans WebSearch pour tester les fallbacks."""
    llm = MagicMock()
    llm.generate = MagicMock(return_value="Réponse Wikipedia de secours.")
    bus = MagicMock()
    return KnowledgeAgent(llm, bus, {"max_results": 3})


def _make_mock_response(html: str = FAKE_HTML) -> MagicMock:
    """Crée une réponse requests mockée avec le HTML fourni."""
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock()
    return resp


# ── can_handle : patterns français ────────────────────────────────────────────


def test_can_handle_recherche(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("recherche Python") is True


def test_can_handle_cherche(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("cherche des infos sur l'intelligence artificielle") is True


def test_can_handle_trouve(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("trouve des informations sur Python") is True


def test_can_handle_cest_quoi(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("c'est quoi l'intelligence artificielle ?") is True


def test_can_handle_quest_ce_que(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("qu'est-ce que le machine learning ?") is True


def test_can_handle_actualite(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("actualité technologie") is True


def test_can_handle_actualites(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("actualités du sport") is True


def test_can_handle_news(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("news sur l'économie") is True


def test_can_handle_wikipedia(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("wikipédia python") is True


def test_can_handle_explique(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("explique le deep learning") is True


def test_can_handle_definition(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("définition de l'entropie") is True


def test_can_handle_savoir(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("je veux savoir comment fonctionne Python") is True


def test_can_handle_infos_sur(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("infos sur les trous noirs") is True


# ── can_handle : patterns anglais ─────────────────────────────────────────────


def test_can_handle_what_is(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("what is quantum computing?") is True


def test_can_handle_who_is(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("who is Elon Musk?") is True


def test_can_handle_search(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("search for Python tutorials") is True


def test_can_handle_find(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("find information about AI") is True


def test_can_handle_look_up(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("look up the weather in Paris") is True


def test_can_handle_google(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("google Python programming") is True


# ── can_handle : exclusions (pas de faux positifs) ────────────────────────────


def test_can_handle_no_match_heure(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("quelle heure est-il ?") is False


def test_can_handle_no_match_musique(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("joue de la musique") is False


def test_can_handle_no_match_doc_word(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("crée un document word") is False


def test_can_handle_no_match_resume_word(agent: KnowledgeAgent) -> None:
    assert agent.can_handle("fais un résumé word") is False


# ── _tool_web_search ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_web_search_retourne_resultats(agent: KnowledgeAgent) -> None:
    result = await agent._tool_web_search(query="Python")
    assert "Python" in result
    assert "Résultats web pour 'Python'" in result


@pytest.mark.anyio
async def test_web_search_contient_urls(
    agent: KnowledgeAgent, web_search_mock: MagicMock
) -> None:
    result = await agent._tool_web_search(query="Python")
    assert "wikipedia" in result.lower() or "example.com" in result.lower()


@pytest.mark.anyio
async def test_web_search_appelle_service(
    agent: KnowledgeAgent, web_search_mock: MagicMock
) -> None:
    await agent._tool_web_search(query="test")
    web_search_mock.search.assert_called_once_with("test", 3)


@pytest.mark.anyio
async def test_web_search_aucun_resultat(
    agent: KnowledgeAgent, web_search_mock: MagicMock
) -> None:
    web_search_mock.search = AsyncMock(return_value=[])
    result = await agent._tool_web_search(query="xyzzy impossible")
    assert "Aucun résultat" in result


@pytest.mark.anyio
async def test_web_search_sans_service(agent_no_web: KnowledgeAgent) -> None:
    result = await agent_no_web._tool_web_search(query="Python")
    assert "non disponible" in result


@pytest.mark.anyio
async def test_web_search_erreur_service(
    agent: KnowledgeAgent, web_search_mock: MagicMock
) -> None:
    web_search_mock.search = AsyncMock(side_effect=Exception("Connexion refusée"))
    result = await agent._tool_web_search(query="Python")
    assert "Erreur" in result


# ── _tool_fetch_page ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_fetch_page_extrait_texte_principal(agent: KnowledgeAgent) -> None:
    with patch("app.agents.knowledge_agent.requests.get", return_value=_make_mock_response()):
        result = await agent._tool_fetch_page(url="https://example.com")
    assert "Article principal de test" in result
    assert "Contenu utile" in result


@pytest.mark.anyio
async def test_fetch_page_supprime_scripts(agent: KnowledgeAgent) -> None:
    with patch("app.agents.knowledge_agent.requests.get", return_value=_make_mock_response()):
        result = await agent._tool_fetch_page(url="https://example.com")
    assert "console.log" not in result
    assert "js interdit" not in result


@pytest.mark.anyio
async def test_fetch_page_supprime_nav(agent: KnowledgeAgent) -> None:
    with patch("app.agents.knowledge_agent.requests.get", return_value=_make_mock_response()):
        result = await agent._tool_fetch_page(url="https://example.com")
    assert "Navigation menu inutile" not in result


@pytest.mark.anyio
async def test_fetch_page_supprime_footer(agent: KnowledgeAgent) -> None:
    with patch("app.agents.knowledge_agent.requests.get", return_value=_make_mock_response()):
        result = await agent._tool_fetch_page(url="https://example.com")
    assert "Pied de page à supprimer" not in result


@pytest.mark.anyio
async def test_fetch_page_supprime_styles(agent: KnowledgeAgent) -> None:
    with patch("app.agents.knowledge_agent.requests.get", return_value=_make_mock_response()):
        result = await agent._tool_fetch_page(url="https://example.com")
    assert "display: none" not in result


@pytest.mark.anyio
async def test_fetch_page_header_url_present(agent: KnowledgeAgent) -> None:
    with patch("app.agents.knowledge_agent.requests.get", return_value=_make_mock_response()):
        result = await agent._tool_fetch_page(url="https://example.com")
    assert "📄" in result
    assert "example.com" in result


@pytest.mark.anyio
async def test_fetch_page_timeout(agent: KnowledgeAgent) -> None:
    import requests as req

    with patch(
        "app.agents.knowledge_agent.requests.get",
        side_effect=req.exceptions.Timeout(),
    ):
        result = await agent._tool_fetch_page(url="https://example.com")
    assert "❌" in result
    assert "Timeout" in result or "timeout" in result


@pytest.mark.anyio
async def test_fetch_page_connexion_error(agent: KnowledgeAgent) -> None:
    import requests as req

    with patch(
        "app.agents.knowledge_agent.requests.get",
        side_effect=req.exceptions.ConnectionError(),
    ):
        result = await agent._tool_fetch_page(url="https://nonexistent.example.com")
    assert "❌" in result
    assert "connecter" in result.lower() or "connexion" in result.lower()


@pytest.mark.anyio
async def test_fetch_page_http_error(agent: KnowledgeAgent) -> None:
    import requests as req

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    http_error = req.exceptions.HTTPError(response=mock_resp)

    with patch("app.agents.knowledge_agent.requests.get", side_effect=http_error):
        result = await agent._tool_fetch_page(url="https://example.com/notfound")
    assert "❌" in result
    assert "404" in result


@pytest.mark.anyio
async def test_fetch_page_troncature_max_chars(agent: KnowledgeAgent) -> None:
    long_html = f"<html><body><p>{'A' * 10000}</p></body></html>"
    with patch(
        "app.agents.knowledge_agent.requests.get",
        return_value=_make_mock_response(long_html),
    ):
        result = await agent._tool_fetch_page(url="https://example.com")
    # Contenu tronqué à _MAX_PAGE_CHARS (4000) + header ~50 chars
    assert len(result) <= agent._MAX_PAGE_CHARS + 100


# ── _tool_answer_question ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_answer_question_avec_contexte_appelle_llm(agent: KnowledgeAgent) -> None:
    agent._web_context = "Python est un langage créé par Guido van Rossum en 1991."
    agent._web_sources = ["https://fr.wikipedia.org/wiki/Python_(langage)"]
    agent.ask_llm = MagicMock(return_value="Python est un langage polyvalent.")

    result = await agent._tool_answer_question(question="C'est quoi Python ?")

    agent.ask_llm.assert_called_once()
    assert "Python" in result


@pytest.mark.anyio
async def test_answer_question_ajoute_sources_footer(agent: KnowledgeAgent) -> None:
    agent._web_context = "Contexte de test."
    agent._web_sources = [
        "https://example.com/source1",
        "https://example.com/source2",
    ]
    agent.ask_llm = MagicMock(return_value="Réponse synthétisée.")

    result = await agent._tool_answer_question(question="Question test")

    assert "📚" in result or "Sources" in result
    assert "source1" in result or "source2" in result


@pytest.mark.anyio
async def test_answer_question_sans_sources_pas_de_footer(agent: KnowledgeAgent) -> None:
    agent._web_context = "Contexte de test sans sources."
    agent._web_sources = []
    agent.ask_llm = MagicMock(return_value="Réponse synthétisée.")

    result = await agent._tool_answer_question(question="Question test")

    assert result == "Réponse synthétisée."


@pytest.mark.anyio
async def test_answer_question_sans_contexte_fallback_wikipedia(
    agent: KnowledgeAgent,
) -> None:
    agent._web_context = ""
    agent._web_sources = []

    with patch.object(
        agent,
        "_tool_wikipedia_summary",
        new=AsyncMock(return_value="Résumé Wikipedia sur Python."),
    ) as mock_wiki:
        result = await agent._tool_answer_question(question="Qu'est-ce que Python ?")
        mock_wiki.assert_called_once()
    assert "Wikipedia" in result or "Python" in result


@pytest.mark.anyio
async def test_answer_question_erreur_llm(agent: KnowledgeAgent) -> None:
    agent._web_context = "Contexte de test."
    agent._web_sources = []
    agent.ask_llm = MagicMock(side_effect=Exception("LLM non disponible"))

    result = await agent._tool_answer_question(question="Question test")
    assert "❌" in result or "Erreur" in result


# ── handle() — flow complet ───────────────────────────────────────────────────


@pytest.mark.anyio
async def test_handle_retourne_string(
    agent: KnowledgeAgent, web_search_mock: MagicMock
) -> None:
    agent.ask_llm = MagicMock(return_value="Réponse sur Python.")
    with patch(
        "app.agents.knowledge_agent.requests.get", return_value=_make_mock_response()
    ):
        result = await agent.handle("c'est quoi Python ?")
    assert isinstance(result, str)
    assert len(result) > 5


@pytest.mark.anyio
async def test_handle_appelle_web_search(
    agent: KnowledgeAgent, web_search_mock: MagicMock
) -> None:
    agent.ask_llm = MagicMock(return_value="Python")
    with patch(
        "app.agents.knowledge_agent.requests.get", return_value=_make_mock_response()
    ):
        await agent.handle("recherche Python")
    web_search_mock.search.assert_called()


@pytest.mark.anyio
async def test_handle_sans_web_search_fallback_wikipedia(
    agent_no_web: KnowledgeAgent,
) -> None:
    agent_no_web.ask_llm = MagicMock(return_value="Python")
    with patch.object(
        agent_no_web,
        "_tool_wikipedia_summary",
        new=AsyncMock(return_value="Résumé Wikipedia sur Python."),
    ) as mock_wiki:
        result = await agent_no_web.handle("recherche Python")
        mock_wiki.assert_called_once()
    assert "Wikipedia" in result or "Python" in result


@pytest.mark.anyio
async def test_handle_aucun_resultat_web_fallback_wikipedia(
    agent: KnowledgeAgent, web_search_mock: MagicMock
) -> None:
    web_search_mock.search = AsyncMock(return_value=[])
    agent.ask_llm = MagicMock(return_value="Python")
    with patch.object(
        agent,
        "_tool_wikipedia_summary",
        new=AsyncMock(return_value="Résumé Wikipedia."),
    ) as mock_wiki:
        result = await agent.handle("recherche sujet introuvable")
        mock_wiki.assert_called_once()


@pytest.mark.anyio
async def test_handle_erreur_web_search_fallback_wikipedia(
    agent: KnowledgeAgent, web_search_mock: MagicMock
) -> None:
    web_search_mock.search = AsyncMock(side_effect=Exception("Network error"))
    agent.ask_llm = MagicMock(return_value="Python")
    with patch.object(
        agent,
        "_tool_wikipedia_summary",
        new=AsyncMock(return_value="Résumé Wikipedia."),
    ) as mock_wiki:
        result = await agent.handle("cherche des infos")
        mock_wiki.assert_called_once()


@pytest.mark.anyio
async def test_handle_utilise_snippets_si_fetch_echoue(
    agent: KnowledgeAgent, web_search_mock: MagicMock
) -> None:
    agent.ask_llm = MagicMock(return_value="Réponse basée sur snippets.")
    import requests as req

    with patch(
        "app.agents.knowledge_agent.requests.get",
        side_effect=req.exceptions.ConnectionError(),
    ):
        result = await agent.handle("recherche Python")
    assert isinstance(result, str)


# ── get_tools ─────────────────────────────────────────────────────────────────


def test_get_tools_count(agent: KnowledgeAgent) -> None:
    tools = agent.get_tools()
    assert len(tools) == 7


def test_get_tools_inclut_web_search(agent: KnowledgeAgent) -> None:
    names = {t.name for t in agent.get_tools()}
    assert "web_search" in names


def test_get_tools_inclut_fetch_page(agent: KnowledgeAgent) -> None:
    names = {t.name for t in agent.get_tools()}
    assert "fetch_page" in names


def test_get_tools_inclut_answer_question(agent: KnowledgeAgent) -> None:
    names = {t.name for t in agent.get_tools()}
    assert "answer_question" in names


def test_get_tools_inclut_wikipedia_summary(agent: KnowledgeAgent) -> None:
    names = {t.name for t in agent.get_tools()}
    assert "wikipedia_summary" in names


def test_get_tools_inclut_arxiv(agent: KnowledgeAgent) -> None:
    names = {t.name for t in agent.get_tools()}
    assert "arxiv_search" in names


# ── Propriétés de l'agent ─────────────────────────────────────────────────────


def test_stability_core(agent: KnowledgeAgent) -> None:
    assert agent.stability == "core"


def test_agent_name(agent: KnowledgeAgent) -> None:
    assert agent.name == "KnowledgeAgent"


def test_max_page_chars_valeur(agent: KnowledgeAgent) -> None:
    assert agent._MAX_PAGE_CHARS == 4000
