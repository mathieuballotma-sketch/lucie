"""
Gestionnaire des fournisseurs LLM (Ollama).
Permet d'interagir avec les modèles locaux, avec gestion des erreurs, retries,
reconnexion automatique sur Broken pipe, et option keep_alive.
"""

import time
from typing import Any, Dict, List, Optional

import httpx
import ollama
from ollama import Message, Options

# Constante interne pour les appels vision (API /api/generate)
_OLLAMA_GENERATE_ENDPOINT = "/api/generate"

from ..utils.exceptions import (
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMTimeoutError,
)
from ..utils.logger import logger
from .model_router import ModelRouter


class ProviderManager:
    """
    Gère les appels aux modèles LLM via Ollama.
    Utilise ollama.Client avec timeout explicite pour éviter les Broken pipe.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialise le gestionnaire avec la configuration.

        Args:
            config: Dictionnaire contenant les clés :
                - host: str, URL d'Ollama (ex: "http://localhost:11434")
                - models: dict, mapping des noms de profil vers des objets ModelConfig
                - timeout: int, timeout en secondes
                - retry_attempts: int, nombre de tentatives en cas d'échec
                - retry_delay: float, délai entre les tentatives
                - keep_alive: int, durée de maintien en mémoire (secondes, -1 pour indéfini)
        """
        self.config = config
        self.host = config.get("host", "http://localhost:11434")
        self.models = config.get("models", {})
        self.model_roles: Dict[str, str] = config.get("model_roles", {})
        self.timeout = config.get("timeout", 60)
        self.retry_attempts = config.get("retry_attempts", 3)
        self.retry_delay = config.get("retry_delay", 1.0)
        self.keep_alive = config.get("keep_alive", -1)

        # Configuration energetique (injectee par EnergyOrchestrator)
        self._energy_config: Optional[Dict[str, Any]] = None

        # Créer un client Ollama avec timeout explicite
        self._client = self._create_client()

        logger.info(
            f"ProviderManager initialisé avec host {self.host}, "
            f"timeout={self.timeout}s, keep_alive={self.keep_alive}"
        )

        # Vérifier la connexion au démarrage et initialiser le router
        self._test_connection()
        self.router = ModelRouter(self.list_models())

        # Pour le suivi des changements de modèle
        self._last_model: Optional[str] = None

    def _create_client(self) -> ollama.Client:
        """Crée un client Ollama avec timeout HTTP explicite."""
        return ollama.Client(
            host=self.host,
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )

    def _reconnect(self) -> None:
        """Recrée le client HTTP (corrige les Broken pipe sur connexion stale)."""
        logger.warning("Reconnexion au serveur Ollama...")
        self._client = self._create_client()

    def _test_connection(self) -> None:
        """Vérifie que le serveur Ollama est accessible et que les modèles sont disponibles."""
        try:
            models_resp = self._client.list()
            models_list = models_resp.get("models", [])  # noqa: E501
            models_available = [m["name"] for m in models_list]
            logger.info(f"✅ Ollama accessible. Modèles disponibles: {models_available}")

            default_model = self._select_model("auto")
            if default_model and default_model not in models_available:
                logger.error(
                    f"❌ Modèle par défaut '{default_model}' non trouvé. "
                    f"Téléchargez-le avec: ollama pull {default_model}"
                )
            else:
                logger.info(f"✅ Modèle par défaut '{default_model}' disponible.")
        except Exception as e:
            logger.error(f"❌ Impossible de se connecter à Ollama: {e}")

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
        images: Optional[List[str]] = None,
        top_p: Optional[float] = None,
        repeat_penalty: Optional[float] = None,
    ) -> str:
        """
        Génère une réponse à partir d'un prompt.

        Args:
            prompt: Le prompt utilisateur.
            system: Le prompt système (optionnel).
            priority: Priorité ("auto", "speed", "balanced", "quality") pour choisir le modèle.
            model: Nom explicite du modèle (si fourni, écrase priority).
            model_role: Rôle fonctionnel ("code", "generation", "router", ...) résolu via model_roles.
            temperature: Température pour la génération.
            max_tokens: Nombre maximum de tokens à générer.
            timeout: Timeout spécifique pour cette requête (en secondes).
            images: Liste de chaînes base64 (images) pour les requêtes multimodales.
            top_p: Nucleus sampling — 1.0 = désactivé.
            repeat_penalty: Pénalité de répétition — 1.0 = désactivé.
        """
        start_time = time.time()
        routed = False

        # Résoudre model_role → model si model_role fourni et model absent
        if model_role and model is None:
            resolved = self.model_roles.get(model_role)
            if resolved:
                model = resolved
                logger.debug(f"[Role] '{model_role}' → {model}")

        # Déterminer le modèle à utiliser
        if model:
            if model in self.models:
                model_obj = self.models[model]
                model_name = self._get_model_name(model_obj)
            else:
                model_name = model
        elif priority != "auto" and priority in self.models:
            model_name = self._get_model_name(self.models[priority])
        else:
            # Routage intelligent basé sur le contenu de la requête
            decision = self.router.route(prompt)
            model_name = decision.model.name
            # Utiliser les paramètres optimisés du profil (sauf si override)
            profile_opts = decision.model.to_options(
                override_temp=temperature,
                override_max_tokens=max_tokens,
            )
            temperature = profile_opts["temperature"]
            max_tokens = profile_opts["num_predict"]
            routed = True

        if not model_name:
            model_name = self._select_model("auto") or "qwen2.5:7b"

        # Construire les messages — toujours injecter le français si pas de system
        _DEFAULT_SYSTEM = (
            "LANGUE : français uniquement. "
            "Tu es Lucie, un assistant IA local. "
            "Réponds TOUJOURS en français."
        )
        effective_system = system if system else _DEFAULT_SYSTEM
        messages: List[Message] = [
            Message(role="system", content=effective_system),
        ]
        messages.append(Message(role="user", content=prompt))

        # Options pour Ollama — inclure num_ctx du profil si routé
        profile = self.router.get_model_profile(model_name)
        num_ctx = profile.num_ctx if profile else 4096
        options_kwargs: Dict[str, Any] = {
            "num_predict": max_tokens,
            "temperature": temperature,
            "num_ctx": num_ctx,
        }
        if top_p is not None:
            options_kwargs["top_p"] = top_p
        if repeat_penalty is not None:
            options_kwargs["repeat_penalty"] = repeat_penalty
        options = Options(**options_kwargs)

        logger.debug(f"Appel LLM - model: {model_name}, max_tokens: {max_tokens}")

        # Si un timeout spécifique est demandé, recréer un client temporaire
        request_timeout = timeout if timeout is not None else self.timeout
        client = self._client
        if timeout is not None and timeout != self.timeout:
            client = ollama.Client(
                host=self.host,
                timeout=httpx.Timeout(request_timeout, connect=10.0),
            )

        # Tentatives avec retry et reconnexion automatique
        last_error: Optional[Exception] = None
        for attempt in range(self.retry_attempts + 1):
            try:
                if images:
                    # Appel multimodal via /api/generate (images non supportées par /api/chat)
                    response = client.generate(
                        model=model_name,
                        prompt=prompt,
                        system=effective_system,
                        images=images,
                        options=options,
                        keep_alive=self.keep_alive,
                    )
                    elapsed = time.time() - start_time
                    result = str(response.get("response", "")).strip()
                else:
                    response = client.chat(
                        model=model_name,
                        messages=messages,
                        options=options,
                        keep_alive=self.keep_alive,
                    )
                    elapsed = time.time() - start_time
                    msg = response.get("message", {})  # noqa: E501
                    result = str(msg.get("content", "")).strip()  # noqa: E501

                # Enregistrer la latence pour les stats
                self.router.record_latency(model_name, elapsed)

                log_prefix = "🧭 " if routed else ""
                logger.info(
                    f"{log_prefix}LLM {model_name} → {elapsed:.2f}s, "
                    f"{len(result)} chars"
                )
                if self._last_model != model_name:
                    logger.info(f"Changement de modèle: {self._last_model} → {model_name}")
                    self._last_model = model_name
                return result if result else "[RÉPONSE VIDE]"

            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                is_pipe_error = "broken pipe" in error_str or "errno 32" in error_str
                is_connection_error = (
                    is_pipe_error
                    or "connection" in error_str
                    or "reset" in error_str
                )

                logger.warning(
                    f"Tentative {attempt + 1}/{self.retry_attempts + 1} échouée: {e}"
                )

                if attempt < self.retry_attempts:
                    # Reconnexion sur erreur de connexion / broken pipe
                    if is_connection_error:
                        self._reconnect()
                        client = self._client

                    wait = self.retry_delay * (2 ** attempt)
                    logger.info(f"Nouvelle tentative dans {wait:.1f}s...")
                    time.sleep(wait)

        # Toutes les tentatives ont échoué
        error_str = str(last_error).lower() if last_error else ""
        if "not found" in error_str:
            raise LLMModelNotFoundError(f"Modèle '{model_name}' introuvable.")
        elif "timeout" in error_str:
            raise LLMTimeoutError(
                f"Timeout après {self.retry_attempts + 1} tentatives."
            )
        else:
            raise LLMConnectionError(f"Échec de communication après retries: {last_error}")

    def _get_model_name(self, model: Any) -> str:
        """Extrait le nom du modèle à partir d'un objet ModelConfig ou d'une chaîne."""
        if hasattr(model, "name"):
            return str(model.name)
        elif isinstance(model, dict):
            return str(model.get("name", ""))
        else:
            return str(model)

    def _select_model(self, priority: str) -> Optional[str]:
        """Sélectionne un nom de modèle en fonction de la priorité."""
        if not self.models:
            return None

        if priority in self.models:
            model_obj = self.models[priority]
            return self._get_model_name(model_obj)

        # Sinon, on prend le premier modèle disponible
        for model in self.models.values():
            return self._get_model_name(model)

        return None

    def list_models(self) -> List[str]:
        """Retourne la liste des modèles disponibles sur le serveur Ollama."""
        try:
            response = self._client.list()
            models_list = response.get("models", [])  # noqa: E501
            return [m["name"] for m in models_list]
        except Exception as e:
            logger.error(f"Impossible de lister les modèles: {e}")
            return []

    def set_energy_config(self, energy_config: Dict[str, Any]) -> None:
        """Injecte la configuration energetique depuis EnergyOrchestrator."""
        self._energy_config = energy_config
        keep_alive = energy_config.get("keep_alive")
        if keep_alive is not None:
            self.keep_alive = keep_alive
        logger.info(f"Configuration energetique appliquee: {energy_config}")

    def unload_model(self, model: str) -> None:
        """Decharge un modele de la memoire Ollama (keep_alive: 0)."""
        try:
            self._client.chat(
                model=model,
                messages=[],
                keep_alive=0,
            )
            logger.info(f"Modele {model} decharge de la memoire")
        except Exception as e:
            logger.warning(f"Impossible de decharger {model}: {e}")

    def unload_all_models(self) -> None:
        """Decharge tous les modeles actuellement en memoire."""
        try:
            response = self._client.ps()
            running = response.get("models", [])
            for model_info in running:
                name = model_info.get("name", "")
                if name:
                    self.unload_model(name)
            if not running:
                logger.debug("Aucun modele en memoire a decharger")
        except Exception as e:
            logger.warning(f"Impossible de lister les modeles en memoire: {e}")

    def is_available(self) -> bool:
        """Vérifie rapidement si Ollama est joignable."""
        try:
            self._client.list()
            return True
        except BaseException:
            return False
