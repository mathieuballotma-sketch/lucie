"""
LegalRouter — Router déterministe 3 niveaux, 0 appel LLM.

Catégorise chaque requête en :
  - direct   : réponse immédiate sans pipeline (salutations uniquement)
  - search   : recherche dans la base + rédaction (questions juridiques précises ou ambiguës)
  - document : pipeline complet avec Lecteur (document fourni)

Les requêtes hors-scope strict (médical, pénal, fiscal, etc.) sont refusées.
Les requêtes ambiguës (terme juridique général sans contexte précis) passent au
Retriever — il jugera si la base curatée permet une réponse (KI-001 fix).

Temps de routage : < 1ms (pur string matching).
Aucune dépendance au reste du repo.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_REFUSAL_MESSAGE = (
    "Cette requête sort du périmètre de Beaume V1 (licenciement économique). "
    "Je ne traite que les questions relatives au droit social du travail sur ce thème précis. "
    "Merci de reformuler ou de poser une question sur le licenciement économique."
)

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

# ─── Mots-clés précis déclenchant le mode SEARCH ─────────────────────────────
# KI-001 : whitelist élargie — termes métier CSE, PSE, préavis, articles R./L.
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
    # Textes de loi — articles L. et R.
    "l1233", "l.1233",
    "l1234", "l.1234",
    "l1235", "l.1235",
    "l1237", "l.1237",
    "r1234", "r.1234",
    "r1235", "r.1235",
    "l.1237-11", "l.1237-12", "l.1237-13", "l.1237-14", "l.1237-15", "l.1237-16",
    "article l.",
    "article l ",
    "article r.",
    "code du travail",
    "cass. soc.",
    "cass.soc.",
    "chambre sociale",
    "conseil d'état",
    # Institutions et acteurs
    "cse",
    "comité social et économique",
    "représentant du personnel",
    "délégué syndical",
    "salarié protégé",
    "inspection du travail",
    "direccte",
    "dreets",
    # Thèmes précis nécessitant des sources
    "indemnité de licenciement",
    "indemnités de licenciement",
    "indemnité légale",
    "indemnité conventionnelle",
    "préavis de licenciement",
    "délai de préavis",
    "préavis",
    "reclassement obligatoire",
    "reclassement interne",
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
    "consultation du cse",
    "consultation obligatoire",
    "ordre des licenciements",
    "critères d'ordre",
    "critères de licenciement",
    "plan de sauvegarde de l'emploi",
    "pse obligatoire",
    " pse ",
    "pse ",
    " rcc ",
    "rcc ",
    "convention collective",
    "ancienneté",
    "ancienneté du salarié",
    "charges familiales",
    "priorité de réembauche",
]

# ─── Termes ambigus — passthrough au Retriever (KI-001 fix) ──────────────────
# Termes juridiques généraux sans contexte précis : mieux vaut tenter le
# Retriever que refuser a priori (principe : refus propre > refus préventif).
_AMBIGUOUS_TRIGGERS: List[str] = [
    "licenciement",
    "licencié",
    "licenciée",
    "rupture",
    "contrat de travail",
    "employeur",
    "salaire",
    "indemnité",
    "préavis",
    "droits",
    "droit du travail",
    "emploi",
    "chômage",
    "pôle emploi",
    "réorganisation",
    "restructuration",
    "suppression",
    "plan social",
    "poste supprimé",
]


def _is_greeting(text: str) -> bool:
    """Retourne True si la requête est une salutation ou interaction triviale."""
    return bool(_GREETING_RE.match(text.strip()))


def _needs_search(text: str) -> bool:
    """Retourne True si la requête contient des mots-clés précis nécessitant la base curatée."""
    lower = text.lower()
    return any(trigger in lower for trigger in _SEARCH_TRIGGERS)


def _is_ambiguous(text: str) -> bool:
    """
    Retourne True si la requête contient un terme juridique général sans contexte précis.

    KI-001 fix : ces requêtes passent au Retriever plutôt qu'être refusées a priori.
    Le Retriever jugera si la base curatée permet une réponse satisfaisante.
    """
    lower = text.lower()
    return any(trigger in lower for trigger in _AMBIGUOUS_TRIGGERS)


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

    # Niveau 2a : question juridique précise nécessitant la base
    if _needs_search(combined):
        return {
            "level": "search",
            "intent": "recherche_juridique",
            "document": None,
        }

    # Niveau 2b : terme juridique ambigu → passthrough Retriever (KI-001 fix)
    if _is_ambiguous(combined):
        return {
            "level": "search",
            "intent": "recherche_ambiguë",
            "document": None,
        }

    # Hors-scope strict : pas de terme juridique reconnu
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
    Retourne le format historique {valid, intent, document, refusal_reason}.

    - salutation, recherche_juridique, analyse_document, recherche_forcee → valid=True
    - question_generale (hors-scope) → valid=False, intent="out_of_scope"
    """
    r = route(query, document_text, force)
    if r["intent"] == "question_generale":
        return {
            "valid": False,
            "intent": "out_of_scope",
            "document": None,
            "refusal_reason": _REFUSAL_MESSAGE,
        }
    return {
        "valid": True,
        "intent": r["intent"],
        "document": r.get("document"),
        "refusal_reason": None,
        "_level": r["level"],
    }


# ─── Helpers publics ──────────────────────────────────────────────────────────

def is_ambiguous_passthrough(query: str) -> bool:
    """Retourne True si la requête est dans le mode passthrough ambigu (KI-001)."""
    r = route(query)
    return r["intent"] == "recherche_ambiguë"


def is_dossier(path: Optional[str]) -> bool:
    """Vérifie si le chemin pointe vers un dossier (vs un fichier unique)."""
    if not path:
        return False
    return Path(path).is_dir()
