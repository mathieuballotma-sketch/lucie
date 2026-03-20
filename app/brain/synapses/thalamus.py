"""
Thalamus — Filtre de signal entre les requêtes et les agents.

Chaque agent écoute uniquement sa fréquence.
Loi de Résonance : le signal est routé vers l'agent
qui vibre à la bonne fréquence.

Complète le PathRouter existant, ne le remplace pas.
"""

from __future__ import annotations

from typing import Dict, List

from ...utils.logger import logger


FREQUENCY_MAP: Dict[str, List[str]] = {
    "finance_query": [
        "or", "bitcoin", "bourse", "action", "crypto",
        "cours", "prix", "marché", "euro", "dollar",
        "investissement", "trading", "dividende", "portefeuille",
    ],
    "code_query": [
        "python", "code", "fonction", "bug", "erreur",
        "script", "programme", "classe", "module", "import",
        "debug", "refacto", "algorithme", "review", "revue",
        "optimise", "améliore", "refactore",
    ],
    "file_query": [
        "fichier", "dossier", "document", "ranger",
        "déplacer", "supprimer", "créer", "copier", "renommer",
        "téléchargements", "bureau",
    ],
    "research_query": [
        "cherche", "trouve", "recherche", "synthèse",
        "résumé", "analyse", "compare", "explique", "définition",
        "information", "article", "wikipedia",
    ],
    "mac_query": [
        "ouvre", "ferme", "lance", "safari", "mail",
        "calendrier", "notes", "finder", "spotify",
        "chrome", "slack", "zoom", "appli",
    ],
    "memory_query": [
        "souviens", "rappelle", "dernière fois", "hier",
        "avant", "historique", "on avait dit", "tu te souviens",
        "précédemment", "déjà vu",
    ],
    "document_query": [
        "pdf", "word", "excel", "présentation", "rapport",
        "contrat", "lettre", "facture", "devis", "tableau",
    ],
    "calendar_query": [
        "rendez-vous", "réunion", "agenda", "planning",
        "semaine", "événement",
        "réserve", "disponible", "horaire",
    ],
    "reminder_query": [
        "rappel", "rappelle", "rappelle-moi", "rappelle moi",
        "n'oublie pas", "pense à", "deadline", "échéance",
    ],
    "watch_query": [
        "surveille", "préviens-moi si", "alerte quand",
        "watch", "monitore", "alerte-moi",
    ],
    "mail_query": [
        "mail", "mails", "email", "emails", "inbox",
        "boîte mail", "boite mail", "courrier",
        "traite mes mails", "lis mes mails",
        "classe mes mails", "nouveau mail",
    ],
}


def detect_frequency(query: str) -> str:
    """
    Thalamus — détecte la fréquence naturelle de la requête utilisateur.
    Loi de Résonance : chaque agent écoute uniquement sa fréquence de signal.
    Retourne le signal le plus fort. En cas d'égalité, retourne le premier.
    """
    query_lower = query.lower()
    scores: Dict[str, int] = {}

    for signal, keywords in FREQUENCY_MAP.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            scores[signal] = score

    if not scores:
        return "general_query"

    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    logger.debug(f"🔮 Thalamus → {best} (scores : {scores})")
    return best


def detect_all_frequencies(query: str) -> List[str]:
    """
    Détecte toutes les fréquences actives.
    Pour les requêtes multi-domaines.
    Exemple : 'cherche le cours de l or et ouvre un fichier excel'
    → ['research_query', 'finance_query', 'file_query']
    """
    query_lower = query.lower()
    active: List[tuple[str, int]] = []

    for signal, keywords in FREQUENCY_MAP.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            active.append((signal, score))

    active.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in active] or ["general_query"]
