"""
Agent spécialisé dans la recherche d'informations web.

Pilier #3 BMAD — Recherche Web :
  - web_search      : recherche via DuckDuckGo (service WebSearch)
  - fetch_page      : récupère et nettoie le contenu texte d'une page web
  - answer_question : synthèse LLM avec contexte web et sources
  - wikipedia_summary, wikipedia_search, arxiv_search, news_headlines

Flow handle() en 4 étapes :
  1. Analyse la requête LLM → intention de recherche optimisée
  2. Recherche web via DuckDuckGo
  3. Fetch les 2-3 pages les plus pertinentes
  4. Synthétise une réponse sourcée via LLM
"""

import asyncio
import re
from typing import Any, List, Optional
from urllib.parse import quote as url_quote

import requests
from pydantic.v1 import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger


# ── Contrats Pydantic ─────────────────────────────────────────────────────────


class KnowledgeAgentWebSearchContract(BaseModel):
    query: str = Field(..., description="La requête de recherche")
    max_results: int = Field(3, description="Nombre maximum de résultats", ge=1, le=10)


class KnowledgeAgentFetchPageContract(BaseModel):
    url: str = Field(..., description="URL de la page à récupérer")


class KnowledgeAgentAnswerQuestionContract(BaseModel):
    question: str = Field(..., description="La question à répondre avec contexte web")


class KnowledgeAgentWikipediaSummaryContract(BaseModel):
    """Accepte 'query' ou 'title' comme nom de champ."""

    query: str = Field(..., alias="title", description="Le titre ou sujet de l'article")

    class Config:
        """Pydantic v1 : autoriser le nom de champ en plus de l'alias."""

        allow_population_by_field_name = True


class KnowledgeAgentWikipediaSearchContract(BaseModel):
    query: str = Field(..., description="La requête de recherche")


class KnowledgeAgentArxivSearchContract(BaseModel):
    query: str = Field(..., description="La requête de recherche")


class KnowledgeAgentNewsHeadlinesContract(BaseModel):
    query: str = Field(..., description="Sujet des actualités")


# ── Agent ─────────────────────────────────────────────────────────────────────


class KnowledgeAgent(BaseAgent):
    """
    Agent de connaissances : recherche web, Wikipedia, arXiv, actualités.
    """

    model_role = "lightweight"
    _MAX_PAGE_CHARS = 4000
    _FETCH_TIMEOUT = 10

    def __init__(self, llm_service: Any, bus: Any, config: dict[str, Any]) -> None:
        super().__init__("KnowledgeAgent", llm_service, bus)
        self.stability = "core"  # Agent prioritaire — recherche web et RAG
        self.user_agent = "LucidAgent/1.0 (contact@example.com)"
        self.news_api_key = config.get("news_api_key")
        self.max_results = config.get("max_results", 3)
        self.web_search = config.get("web_search")
        self.timeout = config.get("timeout", 10)
        # Contexte web interne pour answer_question (alimenté par handle)
        self._web_context: str = ""
        self._web_sources: List[str] = []

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="web_search",
                description="Recherche sur le web via DuckDuckGo",
                contract=KnowledgeAgentWebSearchContract,
            ),
            Tool(
                name="fetch_page",
                description="Récupère et nettoie le contenu texte d'une page web (tronqué à 4000 chars)",
                contract=KnowledgeAgentFetchPageContract,
            ),
            Tool(
                name="answer_question",
                description="Synthétise une réponse sourcée à partir du contexte web collecté",
                contract=KnowledgeAgentAnswerQuestionContract,
            ),
            Tool(
                name="wikipedia_summary",
                description="Résumé d'un article Wikipedia",
                contract=KnowledgeAgentWikipediaSummaryContract,
            ),
            Tool(
                name="wikipedia_search",
                description="Recherche d'articles Wikipedia",
                contract=KnowledgeAgentWikipediaSearchContract,
            ),
            Tool(
                name="arxiv_search",
                description="Recherche d'articles scientifiques sur arXiv",
                contract=KnowledgeAgentArxivSearchContract,
            ),
            Tool(
                name="news_headlines",
                description="Recherche d'actualités (nécessite une clé API NewsAPI)",
                contract=KnowledgeAgentNewsHeadlinesContract,
            ),
        ]

    # ── can_handle ────────────────────────────────────────────────────────────

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        # Exclure les requêtes de création de documents Word/PDF
        doc_keywords = [
            "document word", "crée un document", "fais un document",
            "résumé word", "fais un résumé", "word document",
        ]
        if any(kw in q for kw in doc_keywords):
            return False
        keywords = [
            # Français
            "cherche", "recherche", "trouve", "c'est quoi", "qu'est-ce que",
            "actualité", "actualités", "news", "infos sur", "information sur",
            "définition", "définir", "explique", "savoir", "wikipédia",
            "arxiv", "article", "donne moi des infos",
            # Anglais
            "who is", "what is", "search", "find", "google", "look up",
        ]
        return any(kw in q for kw in keywords)

    # ── Outils principaux ─────────────────────────────────────────────────────

    async def _tool_web_search(self, query: str, max_results: int = 3) -> str:
        """Recherche web via le service WebSearch (DuckDuckGo)."""
        if not self.web_search:
            return "Recherche web non disponible."
        try:
            results = await self.web_search.search(query, max_results)
            if not results:
                return f"Aucun résultat web trouvé pour '{query}'."
            output = f"Résultats web pour '{query}':\n"
            for r in results:
                title = r.get("title", "")
                body = r.get("body", "")[:200]
                url = r.get("url", "")
                output += f"- {title}\n  {body}...\n  ({url})\n\n"
            return output
        except Exception as e:
            logger.error(f"Erreur web_search: {e}")
            return f"Erreur lors de la recherche web: {e}"

    async def _tool_fetch_page(self, url: str) -> str:
        """Récupère et nettoie le contenu texte d'une page web, tronqué à _MAX_PAGE_CHARS."""
        try:
            from bs4 import BeautifulSoup  # noqa: PLC0415 — import tardif optionnel
        except ImportError:
            logger.warning("beautifulsoup4 non installé — fetch_page indisponible")
            return "❌ beautifulsoup4 non installé. Installez-le avec : pip install beautifulsoup4"

        loop = asyncio.get_running_loop()
        try:
            def _fetch() -> str:
                resp = requests.get(
                    url,
                    headers={"User-Agent": self.user_agent},
                    timeout=self._FETCH_TIMEOUT,
                )
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
                text = re.sub(r'\n{3,}', '\n\n', text)
                return text[:self._MAX_PAGE_CHARS]

            text = await loop.run_in_executor(None, _fetch)
            return f"📄 Contenu de {url} :\n\n{text}"
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout fetch_page: {url}")
            return f"❌ Timeout lors de la récupération de la page : {url}"
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connexion impossible: {url}")
            return f"❌ Impossible de se connecter à : {url}"
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            logger.warning(f"HTTP error fetch_page {url}: {status}")
            return f"❌ Erreur HTTP ({status}) pour : {url}"
        except Exception as e:
            logger.error(f"Erreur fetch_page {url}: {e}")
            return f"❌ Impossible de récupérer la page : {e}"

    async def _tool_answer_question(self, question: str) -> str:
        """Synthétise une réponse sourcée à partir du contexte web interne."""
        context = self._web_context
        sources = self._web_sources

        if not context:
            logger.info("Pas de contexte web — fallback Wikipedia")
            return await self._tool_wikipedia_summary(query=question)

        sources_text = "\n".join(f"- {url}" for url in sources) if sources else "Aucune source"
        prompt = (
            f"Tu es un assistant de recherche. Réponds à la question suivante en te basant "
            f"UNIQUEMENT sur le contexte web fourni. Cite les sources si pertinent.\n\n"
            f"Question : {question}\n\n"
            f"Contexte web :\n{context[:3500]}\n\n"
            f"Sources consultées :\n{sources_text}\n\n"
            f"Réponse (en français, concise et sourcée) :"
        )
        try:
            answer = self.ask_llm(prompt, model_role=self.model_role, max_tokens=1024)
            if sources:
                sources_footer = "\n\n📚 Sources :\n" + "\n".join(f"• {s}" for s in sources)
                return answer + sources_footer
            return answer
        except Exception as e:
            logger.error(f"Erreur answer_question LLM: {e}")
            return f"❌ Erreur lors de la synthèse : {e}"

    # ── Outils secondaires ────────────────────────────────────────────────────

    async def _tool_wikipedia_summary(self, query: str) -> str:
        return await self._wikipedia_summary(query)

    async def _tool_wikipedia_search(self, query: str) -> str:
        return await self._wikipedia_search(query)

    async def _tool_arxiv_search(self, query: str) -> str:
        return await self._arxiv_search(query)

    async def _tool_news_headlines(self, query: str) -> str:
        if not self.news_api_key:
            return "Clé API News non configurée."
        return await self._news_headlines(query)

    # ── handle() — 4-step web research flow ──────────────────────────────────

    async def handle(self, query: str) -> str:
        """
        Recherche web en 4 étapes :
          1. Analyse la requête → intention de recherche optimisée
          2. Recherche web DuckDuckGo
          3. Fetch les 2-3 pages les plus pertinentes
          4. Synthèse LLM avec sources
        """
        logger.info(f"KnowledgeAgent.handle() — requête: {query}")

        # Étape 1 — Extraire l'intention de recherche
        search_query = await self._extract_search_intent(query)
        logger.info(f"🔍 Intention de recherche : {search_query}")

        # Étape 2 — Recherche web
        if not self.web_search:
            logger.warning("WebSearch non disponible — fallback Wikipedia")
            return await self._tool_wikipedia_summary(query=search_query)

        try:
            results = await self.web_search.search(search_query, self.max_results)
        except Exception as e:
            logger.error(f"Erreur recherche web: {e}")
            return await self._tool_wikipedia_summary(query=search_query)

        if not results:
            logger.info("Aucun résultat web — fallback Wikipedia")
            return await self._tool_wikipedia_summary(query=search_query)

        # Étape 3 — Fetch les 2-3 pages les plus pertinentes
        pages_content: List[str] = []
        sources: List[str] = []

        for r in results[:min(3, len(results))]:
            url = r.get("url", "")
            if not url:
                snippet = r.get("body", "")[:400]
                title = r.get("title", "")
                if snippet:
                    pages_content.append(f"[{title}]\n{snippet}")
                continue
            sources.append(url)
            page_text = await self._tool_fetch_page(url=url)
            if not page_text.startswith("❌"):
                pages_content.append(page_text[:1200])

        # Fallback sur les snippets si aucun fetch réussi
        if not pages_content:
            for r in results:
                title = r.get("title", "")
                body = r.get("body", "")[:300]
                url = r.get("url", "")
                if body:
                    pages_content.append(f"[{title}] {body}")
                    if url and url not in sources:
                        sources.append(url)

        self._web_context = "\n\n---\n\n".join(pages_content)
        self._web_sources = sources

        # Étape 4 — Synthèse LLM avec sources
        return await self._tool_answer_question(question=query)

    # ── Méthodes privées ──────────────────────────────────────────────────────

    async def _extract_search_intent(self, query: str) -> str:
        """Extrait une requête de recherche web optimisée depuis la requête utilisateur."""
        prompt = (
            f"Extrais la requête de recherche web optimale (en 2-5 mots) pour répondre à :\n"
            f'"{query}"\n\n'
            f"Réponds UNIQUEMENT avec la requête de recherche, sans ponctuation ni guillemets."
        )
        try:
            result = self.ask_llm(prompt, temperature=0.2, max_tokens=32, model_role=self.model_role)
            intent = result.strip().strip('"').strip("'")
            return intent if intent else query
        except Exception as e:
            logger.warning(f"Erreur extraction intention: {e}")
            return query

    async def _wikipedia_summary(self, query: str) -> str:
        try:
            loop = asyncio.get_event_loop()
            url = "https://fr.wikipedia.org/api/rest_v1/page/summary/" + url_quote(query)
            resp = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    url, headers={"User-Agent": self.user_agent}, timeout=self.timeout
                ),
            )
            if resp.status_code == 200:
                data = resp.json()
                return "Wikipédia (fr) : " + data.get("extract", "Pas de résumé disponible.")
            url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + url_quote(query)
            resp = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    url, headers={"User-Agent": self.user_agent}, timeout=self.timeout
                ),
            )
            if resp.status_code == 200:
                data = resp.json()
                return "Wikipedia (en) : " + data.get("extract", "No summary available.")
            return f"Impossible de trouver une page Wikipedia pour '{query}'."
        except Exception as e:
            logger.error(f"Erreur Wikipedia: {e}")
            return f"Erreur lors de l'appel à Wikipedia : {str(e)}"

    async def _wikipedia_search(self, query: str) -> str:
        try:
            loop = asyncio.get_event_loop()
            url = "https://fr.wikipedia.org/w/api.php"
            params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": self.max_results,
            }
            resp = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    url, params=params,
                    headers={"User-Agent": self.user_agent},
                    timeout=self.timeout,
                ),
            )
            data = resp.json()
            results = data.get("query", {}).get("search", [])
            if not results:
                return f"Aucun article trouvé pour '{query}'."
            output = f"Articles Wikipedia correspondant à '{query}':\n"
            for r in results:
                output += f"- {r['title']}\n"
            return output
        except Exception as e:
            logger.error(f"Erreur recherche Wikipedia: {e}")
            return f"Erreur lors de la recherche Wikipedia : {str(e)}"

    async def _arxiv_search(self, query: str) -> str:
        import xml.etree.ElementTree as ET

        try:
            loop = asyncio.get_event_loop()
            url = "http://export.arxiv.org/api/query"
            params = {
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": self.max_results,
            }
            resp = await loop.run_in_executor(
                None, lambda: requests.get(url, params=params, timeout=self.timeout)
            )
            root = ET.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = root.findall("atom:entry", ns)
            if not entries:
                return f"Aucun article arXiv trouvé pour '{query}'."
            output = f"Articles arXiv pour '{query}':\n"
            for entry in entries:
                title_el = entry.find("atom:title", ns)
                summary_el = entry.find("atom:summary", ns)
                title = title_el.text if title_el is not None and title_el.text else ""
                summary = summary_el.text if summary_el is not None and summary_el.text else ""
                output += f"- {title}\n  {summary[:200]}...\n\n"
            return output
        except Exception as e:
            logger.error(f"Erreur arXiv: {e}")
            return f"Erreur lors de la recherche arXiv : {str(e)}"

    async def _news_headlines(self, query: str) -> str:
        if not self.news_api_key:
            return "Clé API News non configurée."
        try:
            loop = asyncio.get_event_loop()
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": query,
                "apiKey": self.news_api_key,
                "pageSize": self.max_results,
                "language": "fr",
            }
            resp = await loop.run_in_executor(
                None, lambda: requests.get(url, params=params, timeout=self.timeout)
            )
            data = resp.json()
            if data.get("status") != "ok":
                return f"Erreur NewsAPI : {data.get('message', 'inconnue')}"
            articles = data.get("articles", [])
            if not articles:
                return f"Aucune actualité trouvée pour '{query}'."
            output = f"Actualités sur '{query}':\n"
            for a in articles:
                title = a.get("title", "Sans titre")
                desc = a.get("description", "")
                output += f"- {title}\n  {desc}\n\n"
            return output
        except Exception as e:
            logger.error(f"Erreur NewsAPI: {e}")
            return f"Erreur lors de la récupération des actualités : {str(e)}"

    async def _run_web_search(self, query: str, max_results: int) -> list[Any]:
        if not self.web_search:
            return []
        results: list[Any] = await self.web_search.search(query, max_results)
        return results

    async def _summarize_results(self, query: str, results: list[Any]) -> str:
        content = "\n".join([f"- {r['title']}: {r['body'][:200]}" for r in results])
        prompt = (
            f'Voici des résultats de recherche pour la requête "{query}" :\n'
            f"{content}\n"
            f"Fais un résumé concis et informatif de ces informations."
        )
        return self.ask_llm(prompt, model_role=self.model_role)
