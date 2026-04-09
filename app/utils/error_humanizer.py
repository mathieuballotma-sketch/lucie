"""
Traducteur d'erreurs techniques en messages humains.
L'utilisateur ne doit JAMAIS voir un message technique.
"""

_ERROR_MAP = {
    "Aucun agent Thalamus disponible": "Je ne suis pas sûre de comprendre ta demande. Tu peux reformuler ?",
    "Aucune action directe trouvee": "Je ne sais pas encore faire ça, mais je travaille dessus !",
    "Aucune action multi trouvee": "Je n'ai pas réussi à exécuter toutes les étapes. Tu veux réessayer ?",
    "Aucune creation trouvee": "Je n'ai pas pu créer ce que tu demandes pour le moment.",
    "Résonance non disponible": "Laisse-moi réfléchir... Tu peux reformuler ta question ?",
    "Pas d'engine disponible": "Je suis en train de démarrer, réessaie dans quelques secondes.",
    "Pas d'engine": "Je suis en train de démarrer, réessaie dans quelques secondes.",
    "Pas de signal Thalamus": "Je n'ai pas bien compris. Tu peux préciser ?",
    "Recherche visuelle échouée": "La recherche visuelle n'a pas abouti. Tu veux essayer autrement ?",
}

_PATTERN_MAP = [
    ("timeout", "La requête a pris trop de temps. Réessaie, ça ira plus vite."),
    ("connection refused", "Je n'arrive pas à me connecter au modèle IA. Vérifie qu'Ollama est lancé."),
    ("broken pipe", "La connexion au modèle a été interrompue. Je réessaie..."),
    ("model not found", "Le modèle IA n'est pas installé. Lance 'ollama pull gemma4:e4b' dans le terminal."),
    ("not found", "Le modèle IA demandé n'est pas installé. Lance 'ollama pull gemma4:e4b' dans le terminal."),
    ("out of memory", "Pas assez de mémoire pour cette requête. Ferme quelques applications et réessaie."),
    ("connection reset", "La connexion au modèle a été réinitialisée. Je réessaie..."),
]


def humanize_error(error_msg: str) -> str:
    """Convertit un message d'erreur technique en message humain."""
    # Match exact
    if error_msg in _ERROR_MAP:
        return _ERROR_MAP[error_msg]

    # Match par pattern
    lower = error_msg.lower()
    for pattern, human_msg in _PATTERN_MAP:
        if pattern in lower:
            return human_msg

    # Fallback générique
    if error_msg.startswith("Erreur:") or error_msg.startswith("Error:"):
        return "Quelque chose n'a pas fonctionné. Tu peux réessayer ou reformuler ta demande."

    return error_msg  # Si ce n'est pas une erreur, retourner tel quel
