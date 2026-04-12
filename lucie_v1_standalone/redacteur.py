"""
RedacteurAgent — rédige la note juridique structurée.
Modèle : gemma4:e4b (speed).

Contrainte absolue : refuse de rédiger sans sources.
Ne cite que les sources fournies par le Retriever.

Aucune dépendance au reste du repo.
"""

import json
from pathlib import Path

from . import ollama_client
from .config import REDACTEUR_PARAMS

_SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "redacteur_system.txt"


async def handle(faits_json: str, sources_json: str) -> str:
    """
    Rédige la note structurée.

    Args:
        faits_json: JSON des faits extraits par lecteur.handle().
        sources_json: JSON des sources trouvées par retriever.handle().

    Returns:
        Note juridique en Markdown, ou message de blocage si aucune source.
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
            "Aucune source disponible dans la base curatée pour rédiger cette note. "
            "Le Rédacteur refuse de produire une analyse sans sources vérifiées.\n\n"
            "> Enrichir la base dans "
            "`knowledge/droit_social/licenciement_economique/` avant de relancer."
        )

    # ── Rédaction ─────────────────────────────────────────────────────────────
    system = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

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
