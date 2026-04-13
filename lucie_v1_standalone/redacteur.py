"""
RedacteurAgent — rédige la note ou la réponse juridique structurée.
Modèle : gemma4:e4b (speed).

Deux modes :
  - "document" : note d'analyse formelle complète (pipeline niveau 3)
  - "search"   : réponse directe à une question juridique (pipeline niveau 2)

Contrainte absolue : refuse de rédiger sans sources.
Ne cite que les sources fournies par le Retriever.

Aucune dépendance au reste du repo.
"""

import json
from pathlib import Path
from typing import Literal

from . import ollama_client
from .config import REDACTEUR_PARAMS

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_SYSTEM_DOCUMENT = _PROMPTS_DIR / "redacteur_system.txt"
_SYSTEM_SEARCH = _PROMPTS_DIR / "redacteur_search_system.txt"


async def handle(
    faits_json: str,
    sources_json: str,
    mode: Literal["document", "search"] = "document",
) -> str:
    """
    Rédige la note ou la réponse juridique.

    Args:
        faits_json: JSON des faits extraits par lecteur.handle() ou la requête brute.
        sources_json: JSON des sources trouvées par retriever.handle().
        mode: "document" pour une note formelle, "search" pour une réponse directe.

    Returns:
        Note ou réponse en Markdown, ou message de blocage si aucune source.
    """
    # ── Vérification préalable : sources disponibles ──────────────────────────
    try:
        sources_data = json.loads(sources_json)
        nb_sources = (
            len(sources_data.get("sources", []))
            + len(sources_data.get("jurisprudences", []))
        )
    except (json.JSONDecodeError, AttributeError):
        nb_sources = 0

    if nb_sources == 0:
        return (
            "**RÉDACTION IMPOSSIBLE**\n\n"
            "Aucune source disponible dans la base curatée pour rédiger cette réponse. "
            "Le Rédacteur refuse de produire une analyse sans sources vérifiées.\n\n"
            "> Enrichir la base dans "
            "`knowledge/droit_social/licenciement_economique/` avant de relancer."
        )

    # ── Choix du prompt selon le mode ─────────────────────────────────────────
    system_path = _SYSTEM_SEARCH if mode == "search" else _SYSTEM_DOCUMENT
    system = system_path.read_text(encoding="utf-8")

    if mode == "search":
        # En mode search, on extrait la question originale du faits_json
        try:
            faits_data = json.loads(faits_json)
            question = faits_data.get("query", faits_json)
        except (json.JSONDecodeError, AttributeError):
            question = faits_json

        prompt = (
            f"## Question\n\n{question}\n\n"
            "## Sources disponibles\n\n"
            f"```json\n{sources_json}\n```\n\n"
            "Réponds directement à la question en utilisant UNIQUEMENT les sources fournies. "
            "Cite chaque source utilisée entre crochets [ID]."
        )
    else:
        prompt = (
            "## Faits extraits du document\n\n"
            f"```json\n{faits_json}\n```\n\n"
            "## Sources disponibles\n\n"
            f"```json\n{sources_json}\n```\n\n"
            "Rédige maintenant la note d'analyse complète selon la structure demandée. "
            "Chaque affirmation juridique doit être suivie de sa source entre crochets [ID]."
        )

    options = {k: v for k, v in REDACTEUR_PARAMS.items() if k != "model"}

    return await ollama_client.generate(
        model=REDACTEUR_PARAMS["model"],
        prompt=prompt,
        system=system,
        options=options,
    )
