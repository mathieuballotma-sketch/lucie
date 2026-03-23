"""
Provider MLX-LM pour Apple Silicon.

Utilise mlx-lm pour une génération locale ultra-rapide sur M1/M2/M3/M4.
Gestion gracieuse si mlx-lm n'est pas installé (import optionnel).
"""

import platform
import time
from typing import Any, Dict, List, Optional, Tuple

from ..utils.logger import logger

# Import optionnel — mlx-lm peut ne pas être installé
# On détecte une seule fois à l'import pour éviter les vérifications répétées.
_MLX_IMPORT_OK: bool = False
try:
    if platform.machine() == "arm64":
        import mlx_lm  # noqa: F401

        _MLX_IMPORT_OK = True
    else:
        logger.debug("MLXProvider: machine non arm64, import mlx-lm ignoré")
except ImportError:
    logger.debug("mlx-lm non installé — pip install mlx-lm pour activer MLX")

# Cache process-level des modèles chargés : model_name → (model, tokenizer)
# mlx_lm.load() est coûteux (téléchargement + désérialisation GPU), on met en cache.
_model_cache: Dict[str, Tuple[Any, ...]] = {}


class MLXProvider:
    """
    Provider LLM via mlx-lm (Apple Silicon uniquement).

    Interface identique à ProviderManager (Ollama) pour être un drop-in replacement.
    Si mlx-lm n'est pas installé ou si la machine n'est pas Apple Silicon,
    is_available() retourne False et generate() lève RuntimeError.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialise le provider MLX.

        Args:
            config: Dictionnaire optionnel. Clé utile :
                - mlx_model: str, modèle HuggingFace à utiliser
                  (défaut: "mlx-community/Qwen2.5-7B-Instruct-4bit")
        """
        self.config: Dict[str, Any] = config or {}
        self.default_model: str = self.config.get(
            "mlx_model", "mlx-community/Qwen2.5-7B-Instruct-4bit"
        )
        self._available: bool = _MLX_IMPORT_OK and platform.machine() == "arm64"

        if self._available:
            logger.info(
                f"✅ MLXProvider initialisé — modèle par défaut: {self.default_model}"
            )
        elif platform.machine() != "arm64":
            logger.info("MLXProvider désactivé: machine non Apple Silicon")
        else:
            logger.info(
                "MLXProvider désactivé: mlx-lm non installé "
                "(pip install mlx-lm pour activer)"
            )

    # ------------------------------------------------------------------
    # Interface publique
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        priority: str = "auto",
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Génère une réponse via mlx-lm.

        Args:
            prompt: Le prompt utilisateur.
            system: Le prompt système (optionnel).
            priority: Ignoré — présent pour compatibilité d'interface.
            model: Nom du modèle mlx-lm (HuggingFace Hub ou chemin local).
            temperature: Température pour la génération.
            max_tokens: Nombre maximum de tokens à générer.
            timeout: Non utilisé par mlx-lm — présent pour compatibilité.

        Returns:
            Texte généré, strippé des espaces.

        Raises:
            RuntimeError: Si MLX n'est pas disponible sur cette machine.
        """
        # Supprimer les avertissements ruff sur les paramètres non utilisés
        # (ils font partie de l'interface commune avec ProviderManager)
        _ = priority, timeout

        if not self._available:
            raise RuntimeError(
                "MLXProvider non disponible: "
                "mlx-lm requis sur Apple Silicon (pip install mlx-lm)"
            )

        model_name = model or self.default_model
        start_time = time.time()

        try:
            from mlx_lm import generate, load

            # Construire le prompt (format chat simplifié si system fourni)
            if system:
                full_prompt = (
                    f"<|system|>\n{system}\n<|user|>\n{prompt}\n<|assistant|>\n"
                )
            else:
                full_prompt = prompt

            # Charger le modèle depuis le cache ou le télécharger
            if model_name not in _model_cache:
                logger.info(f"⬇️  Chargement MLX {model_name} en mémoire...")
                _model_cache[model_name] = load(model_name)

            cached = _model_cache[model_name]
            lm_model = cached[0]
            tokenizer = cached[1]

            result: str = generate(
                lm_model,
                tokenizer,
                prompt=full_prompt,
                max_tokens=max_tokens,
                temp=temperature,
                verbose=False,
            )

            elapsed = time.time() - start_time
            logger.info(
                f"⚡ MLX {model_name} → {elapsed:.2f}s, {len(result)} chars"
            )
            return result.strip() if result else "[RÉPONSE VIDE]"

        except Exception as e:
            logger.error(f"Erreur MLXProvider.generate ({model_name}): {e}")
            raise

    def is_available(self) -> bool:
        """Vérifie si MLX est disponible sur cette machine."""
        return self._available

    def list_models(self) -> List[str]:
        """
        Retourne les modèles MLX disponibles dans le cache HuggingFace local.

        Si aucun modèle n'est trouvé en cache, retourne le modèle par défaut.
        """
        if not self._available:
            return []

        models: List[str] = []
        try:
            import os
            from pathlib import Path

            hf_home = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
            hub_dir = Path(hf_home) / "hub"

            if hub_dir.exists():
                for d in hub_dir.iterdir():
                    if d.is_dir() and d.name.startswith("models--mlx-community--"):
                        # "models--mlx-community--Qwen2.5-7B-Instruct-4bit"
                        # → "mlx-community/Qwen2.5-7B-Instruct-4bit"
                        model_name = d.name[len("models--"):].replace("--", "/", 1)
                        models.append(model_name)
        except Exception as e:
            logger.debug(f"Impossible de lister les modèles MLX en cache: {e}")

        return models if models else [self.default_model]
