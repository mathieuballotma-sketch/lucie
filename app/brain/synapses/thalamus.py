"""
Thalamus — Filtre de signal entre les requêtes et les agents.

Chaque agent écoute uniquement sa fréquence.
Loi de Résonance : le signal est routé vers l'agent
qui vibre à la bonne fréquence.

Complète le PathRouter existant, ne le remplace pas.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

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
        # Fallback sémantique — aucun mot-clé ne matche
        semantic = detect_frequency_semantic(query)
        if semantic != "general_query":
            logger.debug(f"🔮 Thalamus sémantique → {semantic}")
        return semantic

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
    if not active:
        # Fallback sémantique pour detect_all aussi
        semantic = detect_frequency_semantic(query)
        if semantic != "general_query":
            logger.debug(f"🔮 Thalamus sémantique (all) → {semantic}")
        return [semantic]
    return [s for s, _ in active]


# ─────────────────────────────────────────────────────────────
# Fallback sémantique — prototypes par fréquence
# Phrases choisies SANS mots-clés FREQUENCY_MAP pour tester
# la similarité sémantique pure.
# ─────────────────────────────────────────────────────────────

_PROTOTYPE_EXAMPLES: Dict[str, List[str]] = {
    "finance_query": [
        "placer mon argent intelligemment",
        "quel rendement pour mon épargne",
        "stratégie patrimoniale à long terme",
        "comment diversifier mes actifs",
        "rentabilité de mes placements",
        "gérer mon budget mensuel efficacement",
    ],
    "code_query": [
        "corriger cette logique de boucle",
        "restructurer l'architecture du projet",
        "ajouter une validation d'entrée",
        "pourquoi cette variable est nulle",
        "écrire un test unitaire pour la classe",
        "transformer cette procédure en asynchrone",
    ],
    "file_query": [
        "trier mes photos par date",
        "organiser le contenu du disque dur",
        "nettoyer les éléments en double",
        "archiver les anciens projets",
        "libérer de l'espace de stockage",
        "classer les captures d'écran",
    ],
    "research_query": [
        "donne-moi un état de l'art sur le sujet",
        "quelles sont les dernières avancées",
        "fais un point complet sur ce thème",
        "résumer les grandes tendances actuelles",
        "collecter des sources fiables",
        "approfondir ce domaine de connaissance",
    ],
    "mac_query": [
        "montre-moi les préférences système",
        "basculer vers l'autre fenêtre active",
        "activer le mode sombre sur l'interface",
        "afficher les connexions réseau",
        "redémarrer ce processus en arrière-plan",
        "accéder aux réglages de notifications",
    ],
    "memory_query": [
        "qu'est-ce qu'on s'était dit à propos de ça",
        "tu avais mentionné quelque chose là-dessus",
        "retrouve notre échange sur ce sujet",
        "quelle était ma décision à ce moment",
        "on en a déjà discuté il y a quelque temps",
        "reviens sur ce qu'on avait convenu ensemble",
    ],
}

# Cache global pour les centroïdes de prototypes
_frequency_prototypes: Optional[Dict[str, "np.ndarray[Any, Any]"]] = None
_prototype_model = None


def _init_prototypes() -> Optional[Dict[str, "np.ndarray[Any, Any]"]]:
    """
    Initialise les centroïdes sémantiques pour chaque fréquence.
    Charge le modèle MiniLM via le classifier du cortex.
    Retourne None si le modèle est indisponible.
    """
    global _frequency_prototypes, _prototype_model

    # Déjà initialisé — retourner le cache
    if _frequency_prototypes is not None:
        return _frequency_prototypes

    try:
        from app.brain.cortex.classifier import _load_mini_model

        model = _load_mini_model()
        if model is None:
            logger.warning("⚠️ Thalamus sémantique désactivé — modèle absent")
            return None

        _prototype_model = model
        prototypes: Dict[str, "np.ndarray[Any, Any]"] = {}

        for freq, examples in _PROTOTYPE_EXAMPLES.items():
            # Encode tous les exemples en batch
            vecs = model.encode(examples, normalize_embeddings=True)
            # Centroïde = moyenne des vecteurs
            centroid = np.mean(vecs, axis=0).astype(np.float32)
            # Normalisation L2 du centroïde
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid = centroid / norm
            prototypes[freq] = centroid

        _frequency_prototypes = prototypes
        logger.info(
            f"✅ Thalamus sémantique initialisé — {len(prototypes)} prototypes"
        )
        return _frequency_prototypes

    except Exception as e:
        logger.warning(f"⚠️ Thalamus sémantique indisponible : {e}")
        return None


def detect_frequency_semantic(query: str) -> str:
    """
    Fallback sémantique — similarité cosinus avec les prototypes.
    Retourne la fréquence la plus proche si score >= 0.55.
    Sinon retourne 'general_query'.
    Gracieux : retourne 'general_query' si le modèle est absent.
    """
    prototypes = _init_prototypes()
    if prototypes is None or _prototype_model is None:
        return "general_query"

    try:
        # Encode la requête
        query_vec = _prototype_model.encode(
            query, normalize_embeddings=True
        ).astype(np.float32)

        best_freq = "general_query"
        best_score = 0.0

        for freq, centroid in prototypes.items():
            score = float(np.dot(query_vec, centroid))
            if score > best_score:
                best_score = score
                best_freq = freq

        # Seuil minimal de confiance
        if best_score >= 0.55:
            return best_freq

        return "general_query"

    except Exception as e:
        logger.warning(f"⚠️ Erreur sémantique Thalamus : {e}")
        return "general_query"
