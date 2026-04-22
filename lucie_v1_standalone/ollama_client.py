"""
Client Ollama direct — aucune dépendance au reste du repo.
POST /api/generate, retourne le texte de la réponse.

Gère le retry sur réponse vide (bug gemma4:e4b first-call).

Timeouts httpx composites (Phase 1ter, 2026-04-22) :
  - connect=10 s  → détecte un service Ollama down rapidement
  - read=300 s    → supporte une génération longue (5 min) sans couper
  - write=10 s    → envoi du prompt, jamais lourd
  - pool=10 s     → acquisition connexion dans le pool
Un ReadTimeout (90 s précédemment) faisait échouer silencieusement les
questions à réponse longue. Désormais on laisse 5 min au LLM avant
d'abandonner, et le message d'erreur utilisateur est explicite.
"""

import json
import logging
import os
from typing import AsyncIterator, Optional

import httpx

from .config import (
    OLLAMA_BASE_URL,
    OLLAMA_CONNECT_TIMEOUT,
    OLLAMA_POOL_TIMEOUT,
    OLLAMA_READ_TIMEOUT,
    OLLAMA_WRITE_TIMEOUT,
)
from .perf import current_bucket

logger = logging.getLogger(__name__)


def _httpx_timeout() -> httpx.Timeout:
    """Timeout composite recommandé pour un LLM local lent mais fiable."""
    return httpx.Timeout(
        connect=OLLAMA_CONNECT_TIMEOUT,
        read=OLLAMA_READ_TIMEOUT,
        write=OLLAMA_WRITE_TIMEOUT,
        pool=OLLAMA_POOL_TIMEOUT,
    )


# Message de refus utilisateur — piloté par le HUD en cas de RuntimeError
# contenant « Ollama timeout ». Texte court, pas de jargon technique.
OLLAMA_TIMEOUT_USER_MESSAGE = (
    "Lucie prend plus de temps que prévu sur cette question. "
    "Réessayez dans un instant — si le problème persiste, relancez Ollama."
)


def _keep_alive_value() -> str:
    """Durée keep-alive Ollama. P2 : défaut 24h pour éviter reload (-2-3s/call).

    Override via `LUCIE_OLLAMA_KEEP_ALIVE` (ex: "10m", "2h", "86400").
    """
    return os.environ.get("LUCIE_OLLAMA_KEEP_ALIVE", "24h")


def _record_ollama_stats(model: str, data: dict) -> None:
    """Enregistre les métriques internes Ollama (eval_duration…) dans le bucket courant."""
    bucket = current_bucket()
    if bucket is None:
        return
    # Ollama renvoie des ns — on convertit en ms.
    prompt_eval_ms = (data.get("prompt_eval_duration") or 0) / 1e6
    eval_ms = (data.get("eval_duration") or 0) / 1e6
    total_ms = (data.get("total_duration") or 0) / 1e6
    bucket.add(
        f"ollama.{model}",
        total_ms,
        prompt_eval_ms=int(prompt_eval_ms),
        eval_ms=int(eval_ms),
        prompt_tokens=data.get("prompt_eval_count"),
        out_tokens=data.get("eval_count"),
    )


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
        "keep_alive": _keep_alive_value(),
    }
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options

    async with httpx.AsyncClient(timeout=_httpx_timeout()) as client:
        response_text = await _post(client, payload)

        # Retry une fois si réponse vide (bug first-call gemma4:e4b)
        if not response_text.strip():
            response_text = await _post(client, payload)

    return response_text


def _streaming_enabled() -> bool:
    """P1 : streaming activé par défaut, désactivable via `LUCIE_STREAM=0`."""
    return os.environ.get("LUCIE_STREAM", "1") == "1"


async def generate_stream(
    model: str,
    prompt: str,
    system: str = "",
    options: Optional[dict] = None,
) -> AsyncIterator[str]:
    """Version streaming de `generate` — yield chaque chunk de tokens.

    Utilise `stream=True` côté Ollama. Le dernier chunk contient les stats
    (`total_duration`, `eval_count`…) qu'on enregistre dans le bucket de profilage
    s'il existe.
    """
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": _keep_alive_value(),
    }
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options

    async with httpx.AsyncClient(timeout=_httpx_timeout()) as client:
        try:
            async with client.stream(
                "POST", f"{OLLAMA_BASE_URL}/api/generate", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("response"):
                        yield chunk["response"]
                    if chunk.get("done"):
                        _record_ollama_stats(model, chunk)
                        break
        except httpx.TimeoutException:
            logger.warning(
                "[OllamaClient] Timeout après %.0fs (read) sur modèle %s — "
                "requête abandonnée, veuillez réessayer",
                OLLAMA_READ_TIMEOUT,
                model,
            )
            raise RuntimeError(
                f"Ollama timeout après {OLLAMA_READ_TIMEOUT}s (modèle: {model})"
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Ollama HTTP {e.response.status_code}: {e.response.text[:200]}"
            )


async def _post(client: httpx.AsyncClient, payload: dict) -> str:
    """Effectue la requête POST et extrait le champ 'response'."""
    try:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        _record_ollama_stats(payload.get("model", "?"), data)
        return data.get("response", "")
    except httpx.TimeoutException:
        logger.warning(
            "[OllamaClient] Timeout après %.0fs (read) sur modèle %s — "
            "requête abandonnée, veuillez réessayer",
            OLLAMA_READ_TIMEOUT,
            payload.get("model"),
        )
        raise RuntimeError(
            f"Ollama timeout après {OLLAMA_READ_TIMEOUT}s "
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
