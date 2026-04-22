"""Mapping des étapes pipeline internes → libellés utilisateur.

Centralisation obligatoire : le nom interne d'un agent ("Lecteur", "Retriever",
"Rédacteur", "Vérificateur") ne doit JAMAIS apparaître dans l'UI. Double raison :

1. UX — l'avocat ne connaît pas le jargon agentique. « Lecteur » ne veut rien
   dire pour lui.
2. Protection IP — si un concurrent voit une capture pendant que Lucie
   travaille, il ne doit pas pouvoir reverse-engineer le pipeline interne.

Les logs, l'AuditTrail HMAC et les métriques perf continuent d'utiliser les
noms techniques. Seule la couche d'affichage traverse ce mapping.
"""

from __future__ import annotations

from typing import Literal, Optional

Stage = Literal[
    "router",
    "lecteur",
    "retriever",
    "redacteur",
    "verificateur",
    "cache",
    "finalizing",
]

Mode = Literal["analysis", "action", "document", "search", "direct"]


_DEFAULT: dict[Stage, str] = {
    "router": "J'identifie le type de demande",
    "lecteur": "Je comprends votre question",
    "retriever": "Je consulte les articles pertinents",
    "redacteur": "Je prépare la réponse",
    "verificateur": "Je vérifie chaque citation",
    "cache": "Je retrouve une réponse déjà étudiée",
    "finalizing": "Je finalise",
}


def user_label(
    stage: Stage,
    *,
    has_document: bool = False,
    produces_document: bool = False,
    mode: Optional[Mode] = None,
) -> str:
    """Retourne le libellé utilisateur pour une étape donnée.

    Variantes contextuelles :
    - Pièces chargées (`has_document=True`) : Retriever devient
      « Je lis votre dossier » au lieu de « Je consulte les articles ».
    - Création de document (`produces_document=True` ou mode='action') :
      Rédacteur devient « Je rédige le projet de courrier ».
    """
    if stage == "retriever" and has_document:
        return "Je lis votre dossier"
    if stage == "redacteur" and (produces_document or mode == "action"):
        return "Je rédige le projet de courrier"
    return _DEFAULT[stage]


__all__ = ["Stage", "Mode", "user_label"]
