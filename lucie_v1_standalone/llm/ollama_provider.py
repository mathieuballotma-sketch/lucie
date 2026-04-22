"""
OllamaProvider — Implémentation LLMProvider via l'API Ollama locale.

Caractéristiques :
- Options Python directes (pas d'env vars) : num_ctx, num_predict, temperature, keep_alive
- Streaming via stream=True
- Retry automatique sur réponse vide (bug first-call gemma4:e4b)
- Aucune dépendance au reste du repo
"""

from __future__ import annotations

import json
import logging
from typing import Iterator

import httpx

from .provider import LLMProvider  # noqa: F401 — vérifie la conformité Protocol

logger = logging.getLogger(__name__)

# Timeouts composites alignés sur `config.OLLAMA_*_TIMEOUT` (Phase 1ter) :
# connect court (détection service down), read long (5 min) pour permettre
# aux génerations longues d'aboutir. Voir ollama_client.py pour le rationale.
_DEFAULT_CONNECT = 10.0
_DEFAULT_READ = 300.0
_DEFAULT_WRITE = 10.0
_DEFAULT_POOL = 10.0


def _build_timeout(read_timeout: float) -> httpx.Timeout:
    return httpx.Timeout(
        connect=_DEFAULT_CONNECT,
        read=read_timeout,
        write=_DEFAULT_WRITE,
        pool=_DEFAULT_POOL,
    )


class OllamaProvider:
    """Fournisseur LLM via Ollama (localhost:11434)."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: float = _DEFAULT_READ,
        model: str = "gemma4:e4b",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout  # interprété comme read-timeout
        self._model = model

    # ------------------------------------------------------------------
    # LLMProvider Protocol
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        options: dict | None = None,
        stream: bool = False,
        keep_alive: str = "10m",
    ) -> str | Iterator[str]:
        """
        Appelle POST /api/generate sur Ollama.

        Args:
            prompt: Prompt utilisateur.
            system: System prompt (optionnel).
            options: Paramètres Ollama (num_ctx, num_predict, temperature, …).
            stream: Si True, retourne un générateur de chunks texte.
            keep_alive: Durée de maintien du modèle en mémoire GPU.

        Returns:
            str complet si stream=False, Iterator[str] sinon.
        """
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": stream,
            "keep_alive": keep_alive,
        }
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options

        if stream:
            return self._stream(payload)
        return self._generate_sync(payload)

    def available_models(self) -> list[str]:
        """Retourne les modèles disponibles via /api/tags."""
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def load_model(self, name: str) -> None:
        """Pré-warm : charge le modèle sans générer de texte."""
        try:
            with httpx.Client(timeout=self._timeout) as client:
                client.post(
                    f"{self._base_url}/api/generate",
                    json={"model": name, "prompt": "", "stream": False, "keep_alive": "10m"},
                )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _generate_sync(self, payload: dict) -> str:
        with httpx.Client(timeout=_build_timeout(self._timeout)) as client:
            text = self._post(client, payload)
            # Retry une fois si réponse vide (bug first-call gemma4:e4b)
            if not text.strip():
                text = self._post(client, payload)
        return text

    def _post(self, client: httpx.Client, payload: dict) -> str:
        try:
            resp = client.post(f"{self._base_url}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")
        except httpx.TimeoutException:
            logger.warning(
                "[OllamaProvider] Timeout après %.0fs (read) sur modèle %s — "
                "requête abandonnée, veuillez réessayer",
                self._timeout,
                payload.get("model"),
            )
            raise RuntimeError(
                f"Ollama timeout après {self._timeout}s (modèle: {payload.get('model')})"
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Ollama HTTP {e.response.status_code}: {e.response.text[:200]}"
            )
        except Exception as e:
            raise RuntimeError(f"Ollama erreur: {e}")

    def _stream(self, payload: dict) -> Iterator[str]:
        with httpx.Client(timeout=_build_timeout(self._timeout)) as client:
            with client.stream("POST", f"{self._base_url}/api/generate", json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        text = chunk.get("response", "")
                        if text:
                            yield text
                        if chunk.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: dict) -> "OllamaProvider":
        """Construit depuis un dict de config (base_url, timeout, model)."""
        return cls(
            base_url=config.get("base_url", "http://localhost:11434"),
            timeout=float(config.get("timeout", _DEFAULT_READ)),
            model=config.get("model", "gemma4:e4b"),
        )
