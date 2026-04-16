"""
LegalRouter — Router déterministe, 0 LLM.
Valide que la requête porte sur le licenciement économique (scope V1).
Refuse immédiatement toute requête hors scope avec un message explicite.
"""

import json
from collections import Counter
from typing import Any, Dict, List, Optional

from .terrain import TerrainMixin

# ─── Mots-clés définissant le scope V1 ───────────────────────────────────────
SCOPE_KEYWORDS: List[str] = [
    "licenciement économique",
    "licenciement éco",
    "licenciement eco",
    "motif économique",
    "plan social",
    "PSE",
    "rupture conventionnelle collective",
    "RCC",
    "lettre de licenciement",
    "procédure de licenciement",
    "L1233",
    "L1237",
    "Code du travail",
    "indemnités",
    "préavis",
    "reclassement",
    "droit social",
    "droit du travail",
    "licencié",
    "licenciée",
    "suppression de poste",
    "difficultés économiques",
    "sauvegarde de la compétitivité",
    "mutations technologiques",
    "réorganisation",
]

REFUSAL_MESSAGE = (
    "Cette requête sort du périmètre de la démo V1 (licenciement économique). "
    "Je ne peux traiter que les questions relatives au droit social du travail "
    "sur ce thème précis. Merci de reformuler ou de contacter un agent général."
)


class LegalRouter(TerrainMixin):
    """
    Router déterministe pour le pipeline V1.

    N'hérite pas de BaseAgent — pas de LLM, pas d'EventBus requis.
    Le TerrainMixin est utilisé pour la journalisation et les propositions.
    """

    name = "router"
    GENERATIVE_THRESHOLD = 50  # 50 refus hors scope avant proposition d'extension

    def validate(
        self,
        query: str,
        document_text: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Valide une requête contre le scope V1.

        Args:
            query: Texte de la requête utilisateur.
            document_text: Texte du document joint (optionnel).
            force: Si True, bypass le filtrage (utile pour les démos).

        Returns:
            {
                "valid": bool,
                "intent": str,
                "document": str | None,
                "refusal_reason": str | None,
            }
        """
        if force:
            result: Dict[str, Any] = {
                "valid": True,
                "intent": "analyse_licenciement",
                "document": document_text,
                "refusal_reason": None,
            }
            self._log_to_journal({"query": query[:200], "valid": True, "forced": True})
            return result

        # Concaténer query + document pour le matching
        combined = (query + " " + (document_text or "")).lower()
        hit = any(kw.lower() in combined for kw in SCOPE_KEYWORDS)

        if hit:
            result = {
                "valid": True,
                "intent": "analyse_licenciement",
                "document": document_text,
                "refusal_reason": None,
            }
        else:
            result = {
                "valid": False,
                "intent": "out_of_scope",
                "document": None,
                "refusal_reason": REFUSAL_MESSAGE,
            }

        self._log_to_journal({
            "query": query[:200],
            "valid": result["valid"],
            "intent": result["intent"],
        })
        return result

    def _build_generative_proposal(self, lines: List[str]) -> str:
        """
        Analyse les refus hors scope et propose d'étendre le scope
        si un thème revient souvent dans les requêtes refusées.
        """
        try:
            entries = [json.loads(l) for l in lines if l.strip()]
            refusals = [e.get("query", "") for e in entries if not e.get("valid")]
            if len(refusals) < self.GENERATIVE_THRESHOLD:
                return ""
            words: Counter = Counter()
            for q in refusals:
                words.update(w for w in q.lower().split() if len(w) > 4)
            top = [w for w, _ in words.most_common(10)]
            if not top:
                return ""
            themes = ", ".join(top[:5])
            return (
                f"J'ai refusé {len(refusals)} requêtes hors scope. "
                f"Thèmes récurrents détectés : {themes}. "
                "Veux-tu étendre le scope V1 à ces thèmes ?"
            )
        except Exception:
            return ""
