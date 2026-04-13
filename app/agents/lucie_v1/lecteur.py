"""
LecteurAgent — lit les documents clients, extrait les faits clés.
Modèle : E2B (speed / gemma4:e4b).

Extrait les faits bruts uniquement — aucune analyse juridique.
Retourne un JSON strict selon le schéma défini dans le prompt système.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any, List, Optional

from ..base_agent import BaseAgent
from .terrain import TerrainMixin

_SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "lecteur_system.txt"
_MODEL = "speed"   # gemma4:e4b — léger et rapide


class LecteurAgent(TerrainMixin, BaseAgent):
    """
    Extrait les faits structurés d'un document de licenciement économique.
    Refuse les documents hors périmètre avec {"erreur": "Document hors périmètre"}.
    Réessaie une fois si le JSON est invalide.
    """

    GENERATIVE_THRESHOLD = 20  # 20 docs → synthèse des anomalies récurrentes

    def __init__(
        self,
        llm_service: Any,
        bus: Any,
        event_bus: Any = None,
        token: Optional[str] = None,
    ):
        super().__init__(
            name="lecteur",
            llm_service=llm_service,
            bus=bus,
            event_bus=event_bus,
            token=token,
        )
        self.stability = "core"
        self._system_prompt = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    def can_handle(self, query: str) -> bool:
        return False  # Utilisé uniquement via LegalPipeline

    async def handle(self, document_text: str) -> str:
        """
        Extrait les faits clés du document.

        Args:
            document_text: Texte brut de la lettre / document de licenciement.

        Returns:
            JSON string avec les faits structurés.
        """
        prompt = (
            "TÂCHE : Extraire les faits structurés du document en JSON strict.\n"
            "FORMAT : Réponds UNIQUEMENT avec le JSON valide selon le schéma du prompt système — aucun texte avant ou après.\n"
            "RÈGLE : Si un champ est absent du document, laisse-le vide. N'invente rien.\n\n"
            "## Document à analyser\n\n"
            f"---\n{document_text}\n---"
        )

        response = await self.ask_llm_async(
            prompt=prompt,
            system_prompt=self._system_prompt,
            model=_MODEL,
            temperature=0.0,
            max_tokens=1024,
            top_p=1.0,
        )

        parsed = self.extract_json_from_response(response)

        # Retry une fois si le JSON est invalide
        if parsed is None:
            response = await self.ask_llm_async(
                prompt=prompt + "\n\nIMPORTANT : réponds UNIQUEMENT avec du JSON valide, sans markdown.",
                system_prompt=self._system_prompt,
                model=_MODEL,
                temperature=0,
                top_p=1,
                max_tokens=1024,
                top_p=1.0,
            )
            parsed = self.extract_json_from_response(response)

        if parsed is None:
            result: Any = {
                "erreur": "Extraction JSON impossible après retry",
                "raw": response[:500],
            }
        else:
            result = parsed

        # ── Couche capitalisante ───────────────────────────────────────────────
        if isinstance(result, dict) and "erreur" not in result:
            self._log_to_journal({
                "anomalies_detectees": result.get("anomalies_detectees", []),
                "mentions_absentes": result.get("mentions_legales_absentes", []),
                "type_doc": result.get("type_document", "inconnu"),
            })
        else:
            self._log_to_journal({
                "anomalies_detectees": [],
                "mentions_absentes": [],
                "type_doc": "erreur",
            })

        return json.dumps(result, ensure_ascii=False, indent=2)

    def _build_generative_proposal(self, lines: List[str]) -> str:
        """Synthèse des anomalies les plus fréquentes après N documents lus."""
        try:
            entries = [json.loads(l) for l in lines if l.strip()]
            anomalies: Counter = Counter()
            for e in entries:
                for a in e.get("anomalies_detectees", []):
                    anomalies[a] += 1
            top = [f"{a} ({c}x)" for a, c in anomalies.most_common(5) if c >= 2]
            if not top:
                return ""
            return (
                f"Après {len(entries)} documents analysés, anomalies récurrentes : "
                + ", ".join(top)
                + ". Veux-tu que j'ajoute ces points à la checklist de vérification ?"
            )
        except Exception:
            return ""
