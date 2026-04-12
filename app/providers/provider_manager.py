"""
Gestionnaire hybride MLX + Ollama.

Sélectionne automatiquement le backend LLM le plus rapide disponible :
- MLX (mlx-lm) en priorité sur Apple Silicon — ~65 tok/s, -50 % RAM
- Ollama en fallback garanti — robuste, multiplateforme

Le CircuitBreaker protège les appels MLX et bascule vers Ollama en cas d'échecs répétés.
"""

import platform
from typing import Any, Dict, List, Optional

from ..utils.circuit_breaker import CircuitBreaker
from ..utils.logger import logger
from .manager import ProviderManager
from .mlx_provider import MLXProvider

# Types de tâches qui préfèrent MLX (latence critique)
_MLX_PREFERRED: frozenset[str] = frozenset({"routing", "fast", "speed", "default", "auto"})
# Types de tâches qui forcent Ollama (qualité maximale ou fallback explicite)
_OLLAMA_FORCED: frozenset[str] = frozenset({"fallback", "quality"})


class HybridProviderManager:
    """
    Gestionnaire hybride MLX + Ollama.

    Interface identique à ProviderManager pour être un drop-in replacement.

    Logique de sélection du backend :
        "routing" / "fast" / "speed" / "default" / "auto"
            → MLX si disponible (Apple Silicon + mlx-lm installé)
            → Ollama sinon
        "quality" / "fallback"
            → Ollama toujours

    En cas d'échecs répétés de MLX, le CircuitBreaker ouvre et redirige
    automatiquement vers Ollama (recovery_timeout = 30 s).
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialise le gestionnaire hybride.

        Args:
            config: Dictionnaire de configuration LLM (même format que ProviderManager).
                    Clé supplémentaire optionnelle :
                    - mlx_model: str, modèle HuggingFace MLX à utiliser.
        """
        self.config = config

        # ── Backend Ollama (toujours initialisé — fallback garanti) ────────────
        self._ollama = ProviderManager(config)

        # ── Backend MLX (optionnel) ────────────────────────────────────────────
        mlx_config: Dict[str, Any] = {
            "mlx_model": config.get(
                "mlx_model", "mlx-community/Qwen2.5-7B-Instruct-4bit"
            )
        }
        mlx_candidate = MLXProvider(mlx_config)

        if mlx_candidate.is_available():
            self._mlx: Optional[MLXProvider] = mlx_candidate
            self._mlx_cb: Optional[CircuitBreaker] = CircuitBreaker(
                name="mlx",
                failure_threshold=3,
                recovery_timeout=30.0,
                half_open_success_threshold=2,
            )
            logger.info(
                "🚀 HybridProviderManager: MLX activé comme backend principal "
                f"(modèle: {mlx_candidate.default_model})"
            )
        else:
            self._mlx = None
            self._mlx_cb = None
            logger.info(
                "HybridProviderManager: MLX indisponible — Ollama seul actif"
            )

        # ── Infos hardware ──────────────────────────────────────────────────────
        self._is_apple_silicon: bool = platform.machine() == "arm64"

        # Exposer le router Ollama pour compatibilité avec les agents existants
        self.router = self._ollama.router

    # ── API publique ────────────────────────────────────────────────────────────

    def get_provider(self, task_type: str = "default") -> Any:
        """
        Retourne le meilleur provider pour le type de tâche donné.

        Args:
            task_type: "routing" | "fast" | "speed" | "default" | "auto"
                       → MLX si disponible
                       "fallback" | "quality"
                       → Ollama toujours

        Returns:
            MLXProvider ou ProviderManager selon disponibilité et task_type.
        """
        if task_type in _OLLAMA_FORCED:
            return self._ollama

        mlx = self._mlx
        if mlx is not None and mlx.is_available():
            return mlx

        return self._ollama

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        priority: str = "auto",
        model: Optional[str] = None,
        model_role: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        timeout: Optional[float] = None,
        top_p: Optional[float] = None,
        repeat_penalty: Optional[float] = None,
    ) -> str:
        """
        Génère une réponse via le meilleur backend disponible.

        Utilise MLX pour les tâches rapides (routing, fast, auto, default).
        Bascule automatiquement vers Ollama si MLX échoue (CircuitBreaker).
        Force Ollama pour "quality", "fallback" et tout model_role spécifié
        (les rôles sont Ollama-specific).

        Args:
            prompt: Le prompt utilisateur.
            system: Le prompt système (optionnel).
            priority: Priorité / type de tâche pour la sélection du provider.
            model: Modèle explicite (optionnel, transmis au provider sélectionné).
            model_role: Rôle fonctionnel ("code", "generation", "router", ...) — force Ollama.
            temperature: Température de génération.
            max_tokens: Tokens maximum à générer.
            timeout: Timeout en secondes (optionnel).

        Returns:
            Texte généré.
        """
        # ── model_role → forcer Ollama (les rôles sont spécifiques à Ollama) ──
        if model_role:
            logger.debug(f"[Hybrid] model_role='{model_role}' → Ollama (forcé)")
            return self._ollama.generate(
                prompt=prompt,
                system=system,
                priority=priority,
                model=model,
                model_role=model_role,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                top_p=top_p,
                repeat_penalty=repeat_penalty,
            )

        # ── Forcer Ollama pour qualité / fallback explicite ────────────────────
        if priority in _OLLAMA_FORCED:
            logger.debug(f"[Hybrid] '{priority}' → Ollama (forcé)")
            return self._ollama.generate(
                prompt=prompt,
                system=system,
                priority=priority,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                top_p=top_p,
                repeat_penalty=repeat_penalty,
            )

        mlx = self._mlx
        mlx_cb = self._mlx_cb

        # ── MLX disponible : appel protégé par CircuitBreaker ─────────────────
        if mlx is not None and mlx_cb is not None and mlx.is_available():

            def _mlx_call() -> str:
                return mlx.generate(
                    prompt=prompt,
                    system=system,
                    priority=priority,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )

            def _ollama_fallback() -> str:
                logger.info("[Hybrid] ⚠️  Fallback MLX → Ollama")
                return self._ollama.generate(
                    prompt=prompt,
                    system=system,
                    priority=priority,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    top_p=top_p,
                    repeat_penalty=repeat_penalty,
                )

            logger.debug(f"[Hybrid] '{priority}' → MLX (fallback Ollama)")
            return str(mlx_cb.call(_mlx_call, _ollama_fallback))

        # ── MLX indisponible : Ollama direct ───────────────────────────────────
        logger.debug(f"[Hybrid] MLX indisponible, '{priority}' → Ollama")
        return self._ollama.generate(
            prompt=prompt,
            system=system,
            priority=priority,
            model=model,
            model_role=model_role,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
        )

    def list_models(self) -> List[str]:
        """Retourne les modèles disponibles sur tous les backends actifs."""
        ollama_models = self._ollama.list_models()
        mlx = self._mlx
        mlx_models = mlx.list_models() if mlx is not None else []
        return ollama_models + mlx_models

    def is_available(self) -> bool:
        """Vérifie si au moins un backend est disponible."""
        mlx = self._mlx
        if mlx is not None and mlx.is_available():
            return True
        return self._ollama.is_available()

    def get_health(self) -> Dict[str, Any]:
        """Retourne un rapport de santé des deux backends."""
        mlx = self._mlx
        mlx_cb = self._mlx_cb

        return {
            "apple_silicon": self._is_apple_silicon,
            "ollama": {"available": self._ollama.is_available()},
            "mlx": {
                "available": mlx is not None and mlx.is_available(),
                "circuit_breaker": (
                    mlx_cb.get_health_status() if mlx_cb is not None else None
                ),
            },
        }
