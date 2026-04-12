"""
RedacteurAgent — rédige la note juridique structurée.
Modèle : E4B (quality / gemma4:26b) — seul agent à mériter le gros modèle.

Contrainte absolue : refuse de rédiger sans sources.
Ne cite que les sources fournies par le Retriever.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any, List, Optional

from ..base_agent import BaseAgent
from .terrain import TerrainMixin

_SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "redacteur_system.txt"
_MODEL = "speed"     # gemma4:e4b — gemma4:26b timeouts on current hardware (31% CPU / 69% GPU)


class RedacteurAgent(TerrainMixin, BaseAgent):
    """
    Rédige une note d'analyse juridique structurée en Markdown.
    Bloqué si aucune source n'est disponible.
    """

    GENERATIVE_THRESHOLD = 30  # 30 notes → proposition de template réutilisable

    def __init__(
        self,
        llm_service: Any,
        bus: Any,
        event_bus: Any = None,
        token: Optional[str] = None,
    ):
        super().__init__(
            name="redacteur",
            llm_service=llm_service,
            bus=bus,
            event_bus=event_bus,
            token=token,
        )
        self.stability = "core"
        self._system_prompt = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    def can_handle(self, query: str) -> bool:
        return False  # Utilisé uniquement via LegalPipeline

    async def handle(self, faits_json: str, sources_json: str) -> str:
        """
        Rédige la note structurée.

        Args:
            faits_json: JSON des faits extraits par LecteurAgent.
            sources_json: JSON des sources trouvées par RetrieverAgent.

        Returns:
            Note juridique en Markdown, ou message de blocage si aucune source.
        """
        # ── Vérification préalable : sources disponibles ──────────────────────
        try:
            sources_data = json.loads(sources_json)
            nb_sources = (
                len(sources_data.get("sources", []))
                + len(sources_data.get("jurisprudences", []))
            )
        except (json.JSONDecodeError, AttributeError):
            nb_sources = 0

        if nb_sources == 0:
            return (
                "**RÉDACTION IMPOSSIBLE**\n\n"
                "Aucune source disponible dans la base curatée pour rédiger cette note. "
                "Le Rédacteur refuse de produire une analyse sans sources vérifiées.\n\n"
                "> Enrichir la base dans "
                "`knowledge/droit_social/licenciement_economique/` avant de relancer."
            )

        # ── Rédaction ─────────────────────────────────────────────────────────
        prompt = (
            "## Faits extraits du document\n\n"
            f"```json\n{faits_json}\n```\n\n"
            "## Sources disponibles\n\n"
            f"```json\n{sources_json}\n```\n\n"
            "Rédige maintenant la note d'analyse complète selon la structure demandée. "
            "Chaque affirmation juridique doit être suivie de sa source entre crochets [ID]."
        )

        response = await self.ask_llm_async(
            prompt=prompt,
            system_prompt=self._system_prompt,
            model=_MODEL,
            temperature=0.2,
            max_tokens=2048,
        )

        # ── Couche capitalisante ───────────────────────────────────────────────
        nb_citations = response.count("[")
        nb_sections = response.count("## ")
        self._log_to_journal({
            "nb_sources_utilisees": nb_sources,
            "sections_produites": nb_sections,
            "score_longueur": len(response.split()),
            "nb_citations": nb_citations,
        })

        return response

    def _build_generative_proposal(self, lines: List[str]) -> str:
        """Propose de créer un template Markdown réutilisable après N notes."""
        try:
            entries = [json.loads(l) for l in lines if l.strip()]
            if not entries:
                return ""
            avg_cit = sum(e.get("nb_citations", 0) for e in entries) / len(entries)
            avg_sec = sum(e.get("sections_produites", 0) for e in entries) / len(entries)
            return (
                f"Après {len(entries)} notes rédigées : "
                f"{avg_cit:.1f} citations/note, {avg_sec:.1f} sections/note en moyenne. "
                "Veux-tu que je crée un template Markdown réutilisable ?"
            )
        except Exception:
            return ""
