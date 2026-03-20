"""
CodeDebugAgent — Agent spécialisé dans l'explication, le debug et le refactoring de code.

Utilise deepseek-coder:6.7b comme modèle principal.
Outils : explain_code, find_bug, refactor_code, review_code.

Principes :
- Moindre action : prompt ciblé par tâche
- Résonance : deepseek-coder est optimisé pour le code
- Évolution : chaque interaction améliore via FeedbackAgent
"""

from __future__ import annotations

import asyncio
from typing import Any, List

from pydantic.v1 import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger


# ── Contrats Pydantic ─────────────────────────────────────────────────────────

class ExplainCodeContract(BaseModel):
    """Contrat pour l'explication de code."""
    code: str = Field(..., description="Code à expliquer", min_length=5)


class FindBugContract(BaseModel):
    """Contrat pour la recherche de bugs."""
    code: str = Field(..., description="Code à analyser", min_length=5)
    error: str = Field("", description="Message d'erreur (optionnel)")


class RefactorCodeContract(BaseModel):
    """Contrat pour le refactoring."""
    code: str = Field(..., description="Code à refactorer", min_length=5)
    instructions: str = Field("", description="Instructions de refactoring (optionnel)")


class ReviewCodeContract(BaseModel):
    """Contrat pour la revue de code."""
    code: str = Field(..., description="Code à revoir", min_length=5)


# ── Agent ─────────────────────────────────────────────────────────────────────

class CodeDebugAgent(BaseAgent):
    """
    Agent spécialisé dans l'analyse, le debug et le refactoring de code.
    Utilise deepseek-coder:6.7b pour des réponses techniques précises.
    """

    MODEL = "deepseek-coder:6.7b"
    FALLBACK_MODEL = "qwen2.5:7b"

    def __init__(self, llm_service: Any, bus: Any, config: dict) -> None:
        super().__init__("CodeDebugAgent", llm_service, bus)
        self.generation_timeout = config.get("code_timeout", 30.0)
        logger.info("🐛 CodeDebugAgent initialisé (deepseek-coder:6.7b)")

    def get_tools(self) -> List[Tool]:
        return [
            Tool(
                name="explain_code",
                description="Explique ce que fait un code en langage simple",
                contract=ExplainCodeContract,
            ),
            Tool(
                name="find_bug",
                description="Identifie le bug dans un code (avec erreur optionnelle)",
                contract=FindBugContract,
            ),
            Tool(
                name="refactor_code",
                description="Refactore un code selon des instructions",
                contract=RefactorCodeContract,
            ),
            Tool(
                name="review_code",
                description="Revue complète : bugs, améliorations, sécurité, performance",
                contract=ReviewCodeContract,
            ),
        ]

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        keywords = [
            "explique ce code", "explain", "debug", "bug",
            "refactor", "refactore", "review", "revue",
            "optimise", "améliore", "qu'est-ce que fait",
        ]
        return any(kw in q for kw in keywords)

    # ── Appel LLM centralisé ──────────────────────────────────────────────

    async def _call_code_llm(self, prompt: str, system: str) -> str:
        """Appel deepseek-coder avec fallback sur qwen2.5:7b."""
        loop = asyncio.get_running_loop()
        for model in (self.MODEL, self.FALLBACK_MODEL):
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda m=model: self.llm.generate(
                            prompt=prompt,
                            system=system,
                            model=m,
                            temperature=0.15,
                            max_tokens=1024,
                            timeout=self.generation_timeout,
                        ),
                    ),
                    timeout=self.generation_timeout + 2.0,
                )
                if result and result.strip():
                    return result
            except Exception as e:
                logger.warning(f"🐛 {model} échoué : {e}")
        return "Impossible d'analyser le code — aucun modèle disponible."

    # ── Outils ────────────────────────────────────────────────────────────

    async def _tool_explain_code(self, code: str) -> str:
        """Explique ce que fait ce code en langage simple."""
        logger.info("🐛 Explication de code demandée")
        prompt = (
            "Explique ce code de manière claire et concise en français.\n"
            "Structure ta réponse :\n"
            "1. Ce que fait le code (résumé en 1-2 phrases)\n"
            "2. Comment il fonctionne (étape par étape)\n"
            "3. Points importants à noter\n\n"
            f"Code :\n```\n{code}\n```"
        )
        return await self._call_code_llm(
            prompt,
            "Tu es un expert en programmation. Explique simplement en français.",
        )

    async def _tool_find_bug(self, code: str, error: str = "") -> str:
        """Identifie le bug dans ce code."""
        logger.info("🐛 Recherche de bug demandée")
        error_ctx = f"\nMessage d'erreur : {error}" if error else ""
        prompt = (
            f"Trouve le(s) bug(s) dans ce code.{error_ctx}\n"
            "Structure ta réponse :\n"
            "1. Bug identifié (description claire)\n"
            "2. Ligne(s) concernée(s)\n"
            "3. Pourquoi c'est un bug\n"
            "4. Code corrigé\n\n"
            f"Code :\n```\n{code}\n```"
        )
        return await self._call_code_llm(
            prompt,
            "Tu es un debugger expert. Trouve les bugs et propose des corrections.",
        )

    async def _tool_refactor_code(self, code: str, instructions: str = "") -> str:
        """Refactore ce code selon les instructions."""
        logger.info("🐛 Refactoring demandé")
        instr = instructions or "Améliore la lisibilité, les types, et la structure."
        prompt = (
            f"Refactore ce code selon ces instructions : {instr}\n"
            "Structure ta réponse :\n"
            "1. Changements effectués (liste)\n"
            "2. Code refactoré complet\n"
            "3. Pourquoi ces changements\n\n"
            f"Code original :\n```\n{code}\n```"
        )
        return await self._call_code_llm(
            prompt,
            "Tu es un senior dev. Refactore proprement : PEP8, types, async/await.",
        )

    async def _tool_review_code(self, code: str) -> str:
        """Revue complète : bugs, améliorations, sécurité, performance."""
        logger.info("🐛 Revue de code demandée")
        prompt = (
            "Fais une revue complète de ce code.\n"
            "Structure ta réponse :\n"
            "## Bugs potentiels\n"
            "## Sécurité\n"
            "## Performance\n"
            "## Lisibilité\n"
            "## Recommandations\n\n"
            f"Code :\n```\n{code}\n```"
        )
        return await self._call_code_llm(
            prompt,
            "Tu es un reviewer senior. Analyse bugs, sécurité, performance, lisibilité.",
        )
