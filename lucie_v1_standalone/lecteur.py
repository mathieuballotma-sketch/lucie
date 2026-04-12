"""
LecteurAgent — lit les documents clients, extrait les faits clés.
Modèle : gemma4:e4b (speed).

Extrait les faits bruts uniquement — aucune analyse juridique.
Retourne un JSON strict selon le schéma défini dans le prompt système.

Aucune dépendance au reste du repo.
"""

import json
from pathlib import Path
from typing import Any, Optional

from . import ollama_client
from .config import LECTEUR_PARAMS

_SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "lecteur_system.txt"


async def handle(document_text: str) -> str:
    """
    Extrait les faits clés du document.

    Args:
        document_text: Texte brut de la lettre / document de licenciement.

    Returns:
        JSON string avec les faits structurés.
    """
    system = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    prompt = (
        "Extrais les faits en JSON selon le schéma défini dans tes instructions système. "
        "Réponds UNIQUEMENT avec le JSON valide, sans texte autour.\n\n"
        "Voici le document à analyser :\n\n"
        f"---\n{document_text}\n---"
    )

    options = {k: v for k, v in LECTEUR_PARAMS.items() if k != "model"}

    response = await ollama_client.generate(
        model=LECTEUR_PARAMS["model"],
        prompt=prompt,
        system=system,
        options=options,
    )

    parsed = ollama_client.extract_json_from_response(response)

    # Retry une fois si le JSON est invalide
    if parsed is None:
        response = await ollama_client.generate(
            model=LECTEUR_PARAMS["model"],
            prompt=prompt + "\n\nIMPORTANT : réponds UNIQUEMENT avec du JSON valide, sans markdown.",
            system=system,
            options=options,
        )
        parsed = ollama_client.extract_json_from_response(response)

    if parsed is None:
        result: Any = {
            "erreur": "Extraction JSON impossible après retry",
            "raw": response[:500],
        }
    else:
        result = parsed

    return json.dumps(result, ensure_ascii=False, indent=2)
