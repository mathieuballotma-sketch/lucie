"""
VerificateurAgent — vérifie que les citations de la note correspondent aux sources.
Modèle : E2B (speed / gemma4:e4b).

Pour chaque [REFERENCE] dans la note :
  1. Vérifie qu'elle existe dans les sources fournies.
  2. Supprime les citations invalides.
  3. Calcule un score de fiabilité et rend un verdict.
"""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base_agent import BaseAgent
from .terrain import TerrainMixin

_SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "verificateur_system.txt"
_MODEL = "speed"   # gemma4:e4b — rapide, tâche de comparaison


class VerificateurAgent(TerrainMixin, BaseAgent):
    """
    Contrôle la validité des citations dans la note du Rédacteur.
    Ne produit aucun nouveau contenu juridique.
    Retourne le rapport de vérification + la note corrigée.
    """

    GENERATIVE_THRESHOLD = 5  # 5 notes avec score < 0.7 → alerte rédacteur

    def __init__(
        self,
        llm_service: Any,
        bus: Any,
        event_bus: Any = None,
        token: Optional[str] = None,
    ):
        super().__init__(
            name="verificateur",
            llm_service=llm_service,
            bus=bus,
            event_bus=event_bus,
            token=token,
        )
        self.stability = "core"
        self._system_prompt = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    def can_handle(self, query: str) -> bool:
        return False  # Utilisé uniquement via LegalPipeline

    # ─── Utilitaires ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_citations(note: str) -> List[str]:
        """Extrait toutes les références [XXX] présentes dans la note."""
        return re.findall(r'\[([A-Za-z0-9_\-]+)\]', note)

    @staticmethod
    def _build_source_ids(sources_json: str) -> Dict[str, str]:
        """Construit un dict {ID_UPPER: extrait} depuis le JSON des sources."""
        try:
            data = json.loads(sources_json)
            result: Dict[str, str] = {}
            for s in data.get("sources", []) + data.get("jurisprudences", []):
                sid = s.get("id", "")
                if sid:
                    result[sid.upper()] = s.get("extrait", "")
            return result
        except Exception:
            return {}

    # ─── Handle ───────────────────────────────────────────────────────────────

    async def handle(self, note_markdown: str, sources_json: str) -> str:
        """
        Vérifie la note contre les sources.

        Args:
            note_markdown: Note rédigée par RedacteurAgent.
            sources_json: JSON des sources (RetrieverAgent).

        Returns:
            JSON string avec rapport de vérification + note corrigée.
        """
        source_ids = self._build_source_ids(sources_json)
        citations = self._extract_citations(note_markdown)

        # ── Cas : aucune citation dans la note ────────────────────────────────
        if not citations:
            result: Dict[str, Any] = {
                "citations_verifiees": [],
                "citations_invalides": [],
                "note_corrigee": note_markdown,
                "score_fiabilite": 1.0,
                "verdict": "VALIDÉ",
                "avertissement": "Aucune citation [REF] détectée dans la note.",
            }
            self._log_and_record(result)
            return json.dumps(result, ensure_ascii=False, indent=2)

        # ── Vérification locale (matching exact sur IDs) ───────────────────────
        verifiees: List[Dict[str, Any]] = []
        invalides: List[Dict[str, Any]] = []
        for cit in citations:
            if cit.upper() in source_ids:
                verifiees.append({
                    "reference": cit,
                    "statut": "OK",
                    "correspondance": 1.0,
                })
            else:
                invalides.append({
                    "reference": cit,
                    "statut": "INTROUVABLE",
                    "action": "supprimé",
                })

        # ── Si des citations sont invalides → affiner avec le LLM ─────────────
        if invalides:
            prompt = (
                "## Note à vérifier\n\n"
                f"{note_markdown}\n\n"
                "## Sources disponibles (IDs valides)\n\n"
                f"```json\n{sources_json}\n```\n\n"
                "Vérifie chaque citation [XXX] dans la note. "
                "Pour les citations invalides, supprime-les du texte et retourne le JSON demandé "
                "avec la note corrigée dans le champ `note_corrigee`."
            )
            response = await self.ask_llm_async(
                prompt=prompt,
                system_prompt=self._system_prompt,
                model=_MODEL,
                temperature=0.0,
                max_tokens=2048,
            )
            llm_parsed = self.extract_json_from_response(response)
            if llm_parsed and "note_corrigee" in llm_parsed:
                self._log_and_record(llm_parsed)
                return json.dumps(llm_parsed, ensure_ascii=False, indent=2)
            # Fallback si LLM ne produit pas le JSON attendu

        # ── Construction locale de la note corrigée ───────────────────────────
        note_corrigee = note_markdown
        for inv in invalides:
            ref = re.escape(inv["reference"])
            note_corrigee = re.sub(rf'\[{ref}\]', '', note_corrigee)

        nb_total = len(citations)
        nb_ok = len(verifiees)
        score = nb_ok / nb_total if nb_total > 0 else 1.0

        if invalides:
            verdict = "CORRIGÉ" if score >= 0.5 else "INSUFFISANT"
        else:
            verdict = "VALIDÉ"

        result = {
            "citations_verifiees": verifiees,
            "citations_invalides": invalides,
            "note_corrigee": note_corrigee,
            "score_fiabilite": round(score, 2),
            "verdict": verdict,
        }
        self._log_and_record(result)
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _log_and_record(self, result: Dict[str, Any]) -> None:
        """Journalise le résultat de la vérification."""
        score = result.get("score_fiabilite", 1.0)
        self._log_to_journal({
            "citations_ok": len(result.get("citations_verifiees", [])),
            "citations_invalides": len(result.get("citations_invalides", [])),
            "score_fiabilite": score,
            "verdict": result.get("verdict", "INCONNU"),
        })

    # ─── Générative ───────────────────────────────────────────────────────────

    def _build_generative_proposal(self, lines: List[str]) -> str:
        """Alerte si le score de fiabilité est systématiquement < 0.7."""
        try:
            entries = [json.loads(l) for l in lines if l.strip()]
            # Regarder les N dernières entrées (N = GENERATIVE_THRESHOLD)
            recent = entries[-self.GENERATIVE_THRESHOLD:]
            low = [e for e in recent if e.get("score_fiabilite", 1.0) < 0.7]
            if len(low) < len(recent):
                return ""
            avg_score = sum(e.get("score_fiabilite", 0.0) for e in low) / len(low)
            return (
                f"Le Rédacteur produit des citations invalides de façon répétée "
                f"(score moyen : {avg_score:.2f} sur {len(low)} notes). "
                "Je suggère de renforcer le prompt du Rédacteur. "
                "Veux-tu que je génère un diagnostic ?"
            )
        except Exception:
            return ""
