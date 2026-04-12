"""
Client Ollama direct — aucune dépendance au reste du repo.
POST /api/generate, retourne le texte de la réponse.

Gère le retry sur réponse vide (bug gemma4:e4b first-call).
"""

import json
from typing import Optional

import httpx

from .config import OLLAMA_BASE_URL, OLLAMA_TIMEOUT


async def generate(
    model: str,
    prompt: str,
    system: str = "",
    options: Optional[dict] = None,
) -> str:
    """
    Appelle POST /api/generate sur Ollama et retourne le texte généré.

    Args:
        model: Nom du modèle Ollama (ex: "gemma4:e4b").
        prompt: Prompt utilisateur.
        system: System prompt (optionnel).
        options: Paramètres de sampling (temperature, top_p, etc.).

    Returns:
        Texte de la réponse. Chaîne vide si échec.

    Note:
        Retry automatique une fois si la réponse est vide (bug gemma4:e4b first-call).
    """
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options

    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        response_text = await _post(client, payload)

        # Retry une fois si réponse vide (bug first-call gemma4:e4b)
        if not response_text.strip():
            response_text = await _post(client, payload)

    return response_text


async def _post(client: httpx.AsyncClient, payload: dict) -> str:
    """Effectue la requête POST et extrait le champ 'response'."""
    try:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Ollama timeout après {OLLAMA_TIMEOUT}s "
            f"(modèle: {payload.get('model')})"
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"Ollama HTTP {e.response.status_code}: {e.response.text[:200]}"
        )
    except Exception as e:
        raise RuntimeError(f"Ollama erreur: {e}")


def extract_json_from_response(text: str) -> Optional[dict]:
    """
    Extrait le premier bloc JSON valide d'une réponse LLM.
    Gère les blocs ```json ... ``` et le JSON brut.
    """
    import re

    # Essai 1 : bloc ```json ... ```
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Essai 2 : premier { ... } ou [ ... ] dans le texte
    m = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Essai 3 : texte brut
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None
