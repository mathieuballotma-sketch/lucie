"""
Agent spécialisé dans la création et la lecture de documents Word et PDF.

Pilier #2 BMAD — Lecture de documents :
  - read_pdf    : extraction texte PDF multi-pages via PyMuPDF (fitz)
  - read_docx   : extraction texte DOCX via python-docx
  - summarize_document : lecture auto-détectée + résumé LLM

Corrections v2 :
  - _tool_create_word_document : retour explicitement async (wrappé dans run_in_executor)
  - handle() : tous les appels à _tool_create_word_document avec await
"""

import asyncio
import os
import re
from typing import Any

from pydantic.v1 import BaseModel, Field

from app.actions.writer import WriterAgent
from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger


class DocumentAgentCreateWordDocumentContract(BaseModel):
    title:   str = Field(..., description="Le titre du document")
    content: str = Field(..., description="Le contenu du document")


class DocumentAgentReadPdfContract(BaseModel):
    path: str = Field(..., description="Chemin vers le fichier PDF à lire")


class DocumentAgentReadDocxContract(BaseModel):
    path: str = Field(..., description="Chemin vers le fichier DOCX à lire")


class DocumentAgentSummarizeDocumentContract(BaseModel):
    path: str = Field(..., description="Chemin vers le document (PDF ou DOCX) à résumer")


class DocumentAgent(BaseAgent):
    """Agent de création et lecture de documents Word et PDF."""

    model_role = "code"

    def __init__(self, llm_service: Any, bus: Any, config: dict[str, Any]) -> None:
        super().__init__("DocumentAgent", llm_service, bus)
        self.stability = "core"  # Agent prioritaire — lecture PDF/Word/Excel
        base_dir   = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        output_dir = os.path.join(base_dir, "Lucid_Docs")
        self.writer     = WriterAgent(output_dir)
        self.web_search: Any = config.get("web_search")
        logger.info(f"📁 Documents sauvegardés dans : {output_dir}")

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="create_word_document",
                description="Crée un document Word avec le titre et le contenu spécifiés",
                contract=DocumentAgentCreateWordDocumentContract,
            ),
            Tool(
                name="read_pdf",
                description="Extrait le texte d'un fichier PDF (multi-pages) via PyMuPDF",
                contract=DocumentAgentReadPdfContract,
            ),
            Tool(
                name="read_docx",
                description="Extrait le texte d'un fichier Word (.docx) via python-docx",
                contract=DocumentAgentReadDocxContract,
            ),
            Tool(
                name="summarize_document",
                description="Lit un document (PDF ou DOCX auto-détecté) et le résume avec le LLM",
                contract=DocumentAgentSummarizeDocumentContract,
            ),
        ]

    # ── Helpers de lecture synchrones (run_in_executor) ─────────────────────────

    @staticmethod
    def _sync_read_pdf(path: str) -> str:
        import fitz  # noqa: PLC0415 — import tardif pour éviter dépendance optionnelle
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Fichier introuvable : {path}")
        doc = fitz.open(path)
        pages_text = []
        for page in doc:
            text = page.get_text()
            if text.strip():
                pages_text.append(text)
        doc.close()
        if not pages_text:
            return "(Aucun texte extractible dans ce PDF)"
        return "\n\n".join(pages_text)

    @staticmethod
    def _sync_read_docx(path: str) -> str:
        from docx import Document as DocxDocument  # noqa: PLC0415
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Fichier introuvable : {path}")
        doc = DocxDocument(path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        if not paragraphs:
            return "(Aucun texte trouvé dans ce fichier DOCX)"
        return "\n\n".join(paragraphs)

    # ── Outils async ─────────────────────────────────────────────────────────────

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

    async def _tool_read_pdf(self, path: str) -> str:
        """Extrait le texte de toutes les pages d'un PDF."""
        loop = asyncio.get_running_loop()
        try:
            text = await loop.run_in_executor(None, self._sync_read_pdf, path)
            return f"📄 Contenu du PDF ({os.path.basename(path)}) :\n\n{text}"
        except FileNotFoundError as e:
            return f"❌ {e}"
        except Exception as e:
            logger.error(f"Erreur lecture PDF {path}: {e}")
            return f"❌ Impossible de lire le PDF : {e}"

    async def _tool_read_docx(self, path: str) -> str:
        """Extrait le texte de tous les paragraphes d'un fichier DOCX."""
        loop = asyncio.get_running_loop()
        try:
            text = await loop.run_in_executor(None, self._sync_read_docx, path)
            return f"📄 Contenu du DOCX ({os.path.basename(path)}) :\n\n{text}"
        except FileNotFoundError as e:
            return f"❌ {e}"
        except Exception as e:
            logger.error(f"Erreur lecture DOCX {path}: {e}")
            return f"❌ Impossible de lire le DOCX : {e}"

    async def _tool_summarize_document(self, path: str) -> str:
        """Lit un document (PDF ou DOCX) et demande au LLM d'en faire un résumé."""
        ext = os.path.splitext(path)[1].lower()
        loop = asyncio.get_running_loop()
        try:
            if ext == ".pdf":
                raw_text = await loop.run_in_executor(None, self._sync_read_pdf, path)
            elif ext in (".docx", ".doc"):
                raw_text = await loop.run_in_executor(None, self._sync_read_docx, path)
            else:
                return f"❌ Format non supporté : {ext}. Utilisez .pdf ou .docx"
        except FileNotFoundError as e:
            return f"❌ {e}"
        except Exception as e:
            logger.error(f"Erreur lecture document {path}: {e}")
            return f"❌ Impossible de lire le document : {e}"

        prompt = (
            f'Résume ce document de façon claire et concise en français.\n'
            f'Identifie les points clés, les thèmes principaux, et les informations importantes.\n\n'
            f'Document :\n{raw_text[:4000]}\n\nRésumé :'
        )
        try:
            summary = self.ask_llm(prompt, model_role=self.model_role)
            return f"📋 Résumé de {os.path.basename(path)} :\n\n{summary}"
        except Exception as e:
            logger.error(f"Erreur résumé LLM: {e}")
            return f"❌ Erreur lors du résumé : {e}"

    # ── Routage ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_path_from_query(query: str) -> str | None:
        """Extrait un chemin de fichier (PDF/DOCX) depuis la requête utilisateur."""
        # Chemin absolu ou relatif avec extension
        pattern = r'[~/.]?(?:/[\w\-. ]+)+\.(?:pdf|docx|doc)\b'
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return match.group(0).strip()
        # Nom de fichier simple avec extension
        simple = re.search(r'\b[\w\-. ]+\.(?:pdf|docx|doc)\b', query, re.IGNORECASE)
        if simple:
            return simple.group(0).strip()
        return None

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        creation_words = ["crée", "fais", "fait", "génère", "écris", "rédige", "créer", "faire", "écrire"]
        reading_words  = ["lis", "lire", "ouvre", "ouvrir", "extrais", "extraire",
                          "résume", "résumer", "analyse", "analyser", "contenu", "texte"]
        doc_words      = ["pdf", "document", "docx", "word", "fichier", "résumé", "resume"]
        return (
            (any(w in q for w in creation_words) or any(w in q for w in reading_words))
            and any(w in q for w in doc_words)
        )

    async def handle(self, query: str) -> str:
        logger.info(f"DocumentAgent.handle() - requête: {query}")
        q = query.lower()

        # ── Routage : lecture de document ────────────────────────────────────────
        reading_words  = ["lis", "lire", "ouvre", "ouvrir", "extrais", "extraire",
                          "résume", "résumer", "analyse", "analyser"]
        summarize_words = ["résume", "résumer", "analyse", "analyser"]

        if any(w in q for w in reading_words):
            path = self._extract_path_from_query(query)
            if path:
                if any(w in q for w in summarize_words):
                    return await self._tool_summarize_document(path=path)
                ext = os.path.splitext(path)[1].lower()
                if ext == ".pdf":
                    return await self._tool_read_pdf(path=path)
                elif ext in (".docx", ".doc"):
                    return await self._tool_read_docx(path=path)
                else:
                    return await self._tool_summarize_document(path=path)

        # ── Routage : création de document ───────────────────────────────────────
        search_keywords = ["recherche", "trouve", "cours", "prix", "actualité", "infos sur", "information"]
        needs_search = (
            any(kw in q for kw in search_keywords)
            and self.web_search is not None
        )

        content = ""

        if needs_search:
            logger.info("🔍 Recherche web préalable...")
            try:
                # web_search.search est async — appel direct avec await
                results = await self.web_search.search(query, 3)
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
                    content = self.ask_llm(prompt, model_role=self.model_role)
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
                response = self.ask_llm(prompt, temperature=0.5, model_role=self.model_role)
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
        title = self.ask_llm(prompt_titre, model_role=self.model_role).strip()
        # FIX v2 : await obligatoire
        return await self._tool_create_word_document(title=title, content=content)
