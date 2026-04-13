"""
LegalRouter — Router déterministe, 0 appel LLM.
Valide que la requête porte sur le licenciement économique (scope V1).
Refuse immédiatement toute requête hors scope avec un message explicite.

Aucune dépendance au reste du repo.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

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

GENERATIVE_THRESHOLD = 50  # 50 refus hors scope avant proposition d'extension


def validate(
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
        return {
            "valid": True,
            "intent": "analyse_licenciement",
            "document": document_text,
            "refusal_reason": None,
        }

    combined = (query + " " + (document_text or "")).lower()
    hit = any(kw.lower() in combined for kw in SCOPE_KEYWORDS)

    if hit:
        return {
            "valid": True,
            "intent": "analyse_licenciement",
            "document": document_text,
            "refusal_reason": None,
        }
    else:
        return {
            "valid": False,
            "intent": "hors_scope",
            "document": None,
            "refusal_reason": REFUSAL_MESSAGE,
        }


def is_dossier(path: Optional[str]) -> bool:
    """Vérifie si le chemin pointe vers un dossier (vs un fichier unique)."""
    if not path:
        return False
    return Path(path).is_dir()
