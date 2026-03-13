"""
Agent spécialisé dans la création de documents Word.

Corrections v2 :
  - _tool_create_word_document : retour explicitement async (wrappé dans run_in_executor)
  - handle() : tous les appels à _tool_create_word_document avec await
"""

import asyncio
import os

from pydantic.v1 import BaseModel, Field

from app.actions.writer import WriterAgent
from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger


class DocumentAgentCreateWordDocumentContract(BaseModel):
    title:   str = Field(..., description="Le titre du document")
    content: str = Field(..., description="Le contenu du document")


class DocumentAgent(BaseAgent):
    """Agent de création de documents Word."""

    def __init__(self, llm_service, bus, config):
        super().__init__("DocumentAgent", llm_service, bus)
        base_dir   = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        output_dir = os.path.join(base_dir, "Lucid_Docs")
        self.writer     = WriterAgent(output_dir)
        self.web_search = config.get("web_search")
        logger.info(f"📁 Documents sauvegardés dans : {output_dir}")

    def get_tools(self) -> list:
        return [
            Tool(
                name="create_word_document",
                description="Crée un document Word avec le titre et le contenu spécifiés",
                contract=DocumentAgentCreateWordDocumentContract,
            )
        ]

    async def _tool_create_word_document(self, title: str, content: str) -> str:
        """
        FIX v2 : writer.create_word_document() est synchrone.
        On le wrapp dans run_in_executor pour garder la méthode async
        sans bloquer la boucle et sans erreur de type Pylance.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.writer.create_word_document, title, content
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        creation_words = ["crée", "fais", "fait", "génère", "écris", "rédige", "créer", "faire", "écrire"]
        doc_words      = ["word", "document", "docx", "résumé", "resume", "résumer", "resumer"]
        return any(w in q for w in creation_words) and any(w in q for w in doc_words)

    async def handle(self, query: str) -> str:
        logger.info(f"DocumentAgent.handle() - requête: {query}")
        search_keywords = ["recherche", "trouve", "cours", "prix", "actualité", "infos sur", "information"]
        needs_search = (
            any(kw in query.lower() for kw in search_keywords)
            and self.web_search is not None
        )

        content = ""

        if needs_search:
            logger.info("🔍 Recherche web préalable...")
            try:
                loop    = asyncio.get_running_loop()
                results = await loop.run_in_executor(None, self.web_search.search, query, 3)
                if results:
                    search_summary = "\n".join(
                        [f"- {r['title']}: {r['body'][:200]}" for r in results]
                    )
                    prompt = f"""
Tu dois créer un document Word sur : "{query}".
Résultats de recherche :
{search_summary}
Rédige un contenu structuré. Ne fournis que le contenu, sans titre.
"""
                    content = self.ask_llm(prompt)
                else:
                    logger.warning("Aucun résultat, utilisation LLM seul.")
            except Exception as e:
                logger.error(f"Erreur recherche web: {e}")

        if not content:
            prompt = f"""
Tu es un assistant qui crée des documents Word. Demande : "{query}"
Extrais le titre et le contenu au format JSON :
{{"title": "...", "content": "..."}}
Le contenu doit être détaillé et bien structuré.
Réponds uniquement avec le JSON.
"""
            try:
                response = self.ask_llm(prompt, temperature=0.5)
                data     = self.extract_json_from_response(response)
                if data and "title" in data and "content" in data:
                    title   = data["title"]
                    content = data["content"]
                else:
                    title   = query
                    content = "Contenu généré automatiquement."
                # FIX v2 : await obligatoire
                return await self._tool_create_word_document(title=title, content=content)
            except Exception as e:
                logger.error(f"Erreur handle: {e}")
                return f"Erreur: {e}"

        prompt_titre = f"Donne un titre court (sans guillemets) pour un document sur : {query}"
        title = self.ask_llm(prompt_titre).strip()
        # FIX v2 : await obligatoire
        return await self._tool_create_word_document(title=title, content=content)