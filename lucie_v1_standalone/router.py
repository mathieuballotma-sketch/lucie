"""
LegalRouter — Router déterministe 3 niveaux, 0 appel LLM.

Catégorise chaque requête en :
  - direct   : réponse immédiate sans pipeline (salutations, définitions, questions générales)
  - search   : recherche dans la base + rédaction (questions juridiques précises)
  - document : pipeline complet avec Lecteur (document fourni)

Temps de routage : < 1ms (pur string matching).
Aucune dépendance au reste du repo.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Patterns de salutation / interaction simple ──────────────────────────────
# Matche en début ou en totalité de la requête
_GREETING_RE = re.compile(
    r'^(bonjour|bonsoir|salut|hello|hi|hey|coucou'
    r'|bonne journée|bonne soirée|bonne nuit'
    r'|merci|thanks|thank you|au revoir|bye|à bientôt|à plus'
    r'|ok|okay|d\'accord|parfait|super|très bien|nickel'
    r'|oui|non|peut-être|peut etre'
    r'|aide|help)[\s!.,?;:]*$',
    re.IGNORECASE | re.UNICODE,
)

# ─── Mots-clés déclenchant le mode SEARCH ────────────────────────────────────
# Ces termes indiquent une question juridique précise nécessitant la base curatée.
_SEARCH_TRIGGERS: List[str] = [
    # Procédure / actes
    "licenciement économique",
    "licenciement éco",
    "licenciement eco",
    "motif économique",
    "plan social",
    "rupture conventionnelle collective",
    "lettre de licenciement",
    "procédure de licenciement",
    "entretien préalable",
    "notification de licenciement",
    "plan de reclassement",
    "congé de reclassement",
    "contrat de sécurisation professionnelle",
    # Textes de loi
    "l1233",
    "l.1233",
    "l1237",
    "l.1237",
    "article l.",
    "article l ",
    "code du travail",
    # Thèmes précis nécessitant des sources
    "indemnité de licenciement",
    "indemnités de licenciement",
    "préavis de licenciement",
    "délai de préavis",
    "reclassement obligatoire",
    "salarié protégé",
    "représentant du personnel",
    "délégué syndical",
    "comité social et économique",
    "faute grave",
    "faute lourde",
    "prud'hommes",
    "prudhommes",
    "conseil de prud",
    "suppression de poste",
    "difficultés économiques",
    "sauvegarde de la compétitivité",
    "mutations technologiques",
    "réorganisation de l'entreprise",
    "cessation d'activité",
    "licencier",
    "licencié économiquement",
    "licenciée économiquement",
    "délai pour contester",
    "délai de recours",
    "délai de prescription",
    "pse obligatoire",
    " pse ",
    " rcc ",
]


def _is_greeting(text: str) -> bool:
    """Retourne True si la requête est une salutation ou interaction triviale."""
    return bool(_GREETING_RE.match(text.strip()))


def _needs_search(text: str) -> bool:
    """Retourne True si la requête contient des mots-clés nécessitant la base curatée."""
    lower = text.lower()
    return any(trigger in lower for trigger in _SEARCH_TRIGGERS)


def route(
    query: str,
    document_text: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Catégorise la requête en 3 niveaux de traitement.

    Args:
        query: Texte de la requête utilisateur.
        document_text: Texte du document joint (optionnel).
        force: Si True, force le mode search (bypass routing, pour les démos).

    Returns:
        {
            "level": "direct" | "search" | "document",
            "intent": str,
            "document": str | None,
        }
    """
    # Niveau 3 : document fourni → pipeline complet
    if document_text:
        return {
            "level": "document",
            "intent": "analyse_document",
            "document": document_text,
        }

    # force sans document → search direct (pour les démos)
    if force:
        return {
            "level": "search",
            "intent": "recherche_forcee",
            "document": None,
        }

    combined = query.strip()

    # Niveau 1 : salutation / interaction triviale
    if _is_greeting(combined):
        return {
            "level": "direct",
            "intent": "salutation",
            "document": None,
        }

    # Niveau 2 : question juridique précise nécessitant la base
    if _needs_search(combined):
        return {
            "level": "search",
            "intent": "recherche_juridique",
            "document": None,
        }

    # Niveau 1 par défaut : question générale, définition, hors-scope
    return {
        "level": "direct",
        "intent": "question_generale",
        "document": None,
    }


# ─── Rétrocompatibilité : validate() redirige vers route() ───────────────────
def validate(
    query: str,
    document_text: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Compatibilité ascendante — préférer route() pour le nouveau code.

    Retourne le format historique {valid, intent, document, refusal_reason}
    en mappant les niveaux 2 et 3 sur valid=True, le niveau 1 sur valid=True
    (les questions simples sont désormais traitées en mode direct, pas refusées).
    """
    r = route(query, document_text, force)
    return {
        "valid": True,  # plus de refus : tout est traité (direct, search ou document)
        "intent": r["intent"],
        "document": r.get("document"),
        "refusal_reason": None,
        "_level": r["level"],  # champ interne pour le pipeline
    }


def is_dossier(path: Optional[str]) -> bool:
    """Vérifie si le chemin pointe vers un dossier (vs un fichier unique)."""
    if not path:
        return False
    return Path(path).is_dir()
