from __future__ import annotations

"""
Cortex central - Orchestrateur des agents et de la planification.

Lois universelles invoquées :
  - Principe d'homéostasie  : gestion d'erreurs robuste, circuit breaker, timeouts,
                               event_bus actif pour les erreurs d'outils.
  - Principe de moindre action : chargement paresseux du modèle, ordre déterministe des chemins,
                                  priorisation selon le type de requête.
  - Principe d'entropie      : suppression de pickle (→ joblib), doublon ActionSelector
                                documenté pour suppression, lock asynchrone lazily créé.
  - Principe d'évolution     : enrichissement du classifieur, validation des prédictions.

Corrections appliquées :
  [P1] asyncio.run() → run_coroutine_threadsafe(coro, loop).result(timeout)
  [P2] NanoPredictor : démarrage lazy depuis think()
  [P3] EmbeddingClassifier : _load_lock créé lazily dans _ensure_loaded
  [P4] ActionSelector inline ; brain/action_selector.py à supprimer
  [P5] event_bus.publish("tool.error", ...) activé dans _execute_step
  [P6] CircuitBreaker branché sur _call_llm
  [P7] pickle → joblib
  [P8] Ordre déterministe des chemins via DEFAULT_PATH_PRIORITY et TYPE_SPECIFIC_PRIORITY
  [P9] Support MPS (Apple Silicon M4) pour les embeddings
  [P10] Enrichissement du classifieur avec exemples conversationnels (confiance > 0.4)
  [P11] Validation stricte des prédictions nano (rejet des agents/tools invalides)
  [P12] Prompt adaptatif pour le nano (moins restrictif)
  [P13] Timeout réduit à 1s pour predicted_action
  [P14] Correction de l'ordre dans TYPE_SPECIFIC_PRIORITY["complex"]
  [P15] Méthode _get_nano_system() pour factoriser le prompt
  [P16] Correction de _get_cached_response pour utiliser les deux systèmes
  [P17] Timeout global réduit à 2s pour les appels synchrones (sauf actions directes)
  [P18] Timeout spécifique de 10s pour direct_action (AppleScript peut être lent)
  [P19] Logs détaillés avec trace pour les exceptions
  [FIX MPS] Remplacement des NaN/inf dans les embeddings avant passage à sklearn
  [FIX DEADLOCK] direct_action et multi_action deviennent asynchrones
  [FIX EVENT_BUS] assignation de event_bus aux agents dans _register_agents
"""

import asyncio
import concurrent.futures
import json
import re
import time
from collections import defaultdict
from concurrent.futures import TimeoutError
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import joblib
import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder
from transformers import AutoModel, AutoTokenizer

from app.agents.base_agent import BaseAgent
from app.agents.computer_control_agent import ComputerControlAgent
from app.agents.document_agent import DocumentAgent
from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.reminder_agent import ReminderAgent
from app.agents.vision.text_extractor import TextExtractorAgent
from app.brain.synapses.event_bus import EventBus

from ..core.elasticity import ElasticityEngine
from ..core.executor import Task, TaskExecutor
from ..memory import MemoryService
from ..providers.manager import ProviderManager
from ..services.prompt_cache import PromptCache
from ..services.web_search import WebSearch
from ..utils.circuit_breaker import CircuitBreaker
from ..utils.errors import ToolError
from ..utils.json_parser import JSONParseError, parse_json_safely
from ..utils.logger import logger
from ..utils.metrics import record_cortex_step

# NOTE [P4] : app/brain/action_selector.py est un doublon — à supprimer.

# Timeout par défaut pour run_coroutine_threadsafe (réduit pour accélérer les échecs)
_THREAD_FUTURE_TIMEOUT: float = 2.0


# =============================================================================
# Classifieur sémantique par embeddings (lazy loading)
# =============================================================================
class EmbeddingClassifier:
    """
    Classifieur sémantique basé sur embeddings utilisant un modèle transformers.

    Le modèle HuggingFace est chargé paresseusement (lazy) à la première prédiction.
    Le classifieur sklearn est persisté via joblib.
    Supporte MPS (Apple Silicon), CUDA, et CPU. [P9]
    """

    QUERY_TYPES: List[str] = [
        "greeting", "action", "multi_action", "simple",
        "complex", "mail", "safari", "arrange",
    ]

    # [P10] Enrichissement avec exemples conversationnels pour éviter les confiances trop faibles
    TRAINING_EXAMPLES: List[Tuple[str, str]] = [
        # --- greeting ---
        ("bonjour", "greeting"), ("salut", "greeting"), ("hello", "greeting"),
        ("coucou", "greeting"), ("merci", "greeting"), ("au revoir", "greeting"),
        ("bye", "greeting"), ("hi", "greeting"), ("bonsoir", "greeting"),
        ("comment ça va", "greeting"), ("comment sa va", "greeting"),
        ("ça va ?", "greeting"), ("sa va ?", "greeting"),
        ("comment tu vas", "greeting"), ("tu vas bien ?", "greeting"),
        ("quoi de neuf", "greeting"), ("bien ou bien", "greeting"),
        # --- simple (conversation quotidienne) ---
        ("quelle est la capitale de la France", "simple"),
        ("météo à Paris", "simple"), ("quel temps fait-il", "simple"),
        ("raconte-moi une blague", "simple"),
        ("combien de temps pour cuire un œuf", "simple"),
        ("je me sens pas bien", "simple"),
        ("je suis fatigué", "simple"),
        ("pourquoi donc", "simple"),
        ("c'est psychologique", "simple"),
        ("j'ai envie d'être riche", "simple"),
        ("tu peux pas m'aider à être riche", "simple"),
        ("aide-moi à me motiver", "simple"),
        ("donne-moi un conseil", "simple"),
        ("qu'est-ce que tu penses de ça", "simple"),
        ("dis-moi quelque chose d'intéressant", "simple"),
        # --- complex ---
        ("écris un poème", "complex"), ("explique la relativité", "complex"),
        ("parle-moi de l'univers", "complex"),
        ("rédige un rapport sur l'IA", "complex"),
        ("comment devenir riche", "complex"),
        ("explique-moi comment investir", "complex"),
        ("comment améliorer ma productivité", "complex"),
        # --- action ---
        ("ouvre notes", "action"), ("lance calculatrice", "action"),
        ("tape bonjour", "action"), ("clique à 500 300", "action"),
        ("capture écran", "action"), ("ouvre safari", "action"),
        ("ouvre mail", "action"), ("prends une capture d'écran", "action"),
        # --- multi_action ---
        ("ouvre safari et tape google", "multi_action"),
        ("lance mail puis écris bonjour", "multi_action"),
        ("ouvre notes et safari", "multi_action"),
        ("ouvre notes et safari et mail", "multi_action"),
        # --- mail ---
        ("envoie un email à john", "mail"), ("compose un message pour marie", "mail"),
        ("écris un email à Paul", "mail"), ("rédige un mail professionnel", "mail"),
        # --- safari ---
        ("ouvre safari sur google", "safari"), ("va sur youtube", "safari"),
        ("recherche chat sur le web", "safari"), ("navigue vers apple.com", "safari"),
        # --- arrange ---
        ("organise les fenêtres côte à côte", "arrange"),
        ("disposition grille", "arrange"), ("mets les fenêtres en mosaïque", "arrange"),
        ("côte à côte", "arrange"), ("split screen", "arrange"),
    ]

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        retrain: bool = False,
    ) -> None:
        self.model_name = model_name

        # [P9] Priorité : MPS (Apple Silicon) > CUDA > CPU
        self.device = torch.device(
            "mps" if torch.backends.mps.is_available()
            else "cuda" if torch.cuda.is_available()
            else "cpu"
        )
        logger.info(f"🖥️  Device utilisé pour les embeddings : {self.device}")

        # Modèle transformers — chargé lazily dans _ensure_loaded
        self._tokenizer: Optional[Any] = None
        self._model: Optional[Any] = None

        # [P3] Lock créé lazily dans _ensure_loaded (pas dans __init__)
        self._load_lock: Optional[asyncio.Lock] = None

        self._classifier: Optional[LogisticRegression] = None
        self._label_encoder: Optional[LabelEncoder] = None
        self.is_trained: bool = False
        self.confidence_threshold: float = 0.7

        # [P7] joblib au lieu de pickle
        self.model_path: Path = Path(__file__).parent / "classifier.joblib"

        if retrain or not self.model_path.exists():
            self._train_sync()
            self._save()
        else:
            self._load_classifier_only()

    # ------------------------------------------------------------------
    # Chargement asynchrone du modèle transformers
    # ------------------------------------------------------------------
    async def _ensure_loaded(self) -> None:
        """Charge le modèle HuggingFace de manière asynchrone si nécessaire."""
        if self._model is not None:
            return

        # [P3] Lock créé lazily ici, dans la boucle asyncio active
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()

        async with self._load_lock:
            if self._model is not None:
                return
            logger.info(f"⏳ Chargement du modèle d'embedding {self.model_name}…")
            loop = asyncio.get_running_loop()

            def _load() -> Tuple[Any, Any]:
                tok = AutoTokenizer.from_pretrained(self.model_name)
                mdl = AutoModel.from_pretrained(self.model_name).to(self.device)
                mdl.eval()
                return tok, mdl

            self._tokenizer, self._model = await loop.run_in_executor(None, _load)
            logger.info(f"✅ Modèle d'embedding chargé sur {self.device}.")

    # ------------------------------------------------------------------
    # Persistance (joblib)
    # ------------------------------------------------------------------
    def _save(self) -> None:
        """Sauvegarde le classifieur sklearn via joblib."""
        joblib.dump(
            {"classifier": self._classifier, "label_encoder": self._label_encoder},
            self.model_path,
        )
        logger.info(f"💾 Classifieur sauvegardé dans {self.model_path}")

    def _load_classifier_only(self) -> None:
        """Charge uniquement le classifieur sklearn (pas le modèle transformers)."""
        try:
            data = joblib.load(self.model_path)
            self._classifier = data["classifier"]
            self._label_encoder = data["label_encoder"]
            self.is_trained = True
            logger.info(f"📂 Classifieur chargé depuis {self.model_path}")
        except Exception as exc:
            logger.error(f"Erreur chargement classifieur: {exc} — réentraînement…")
            self._train_sync()
            self._save()

    # ------------------------------------------------------------------
    # Entraînement synchrone (une seule fois)
    # ------------------------------------------------------------------
    def _train_sync(self) -> None:
        """Entraîne le classifieur (charge le modèle de façon synchrone)."""
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModel.from_pretrained(self.model_name).to(self.device)
        self._model.eval()

        texts, labels = zip(*self.TRAINING_EXAMPLES)
        X = self._vectorize_sync(list(texts))

        self._classifier = LogisticRegression(max_iter=2000, C=1.0, random_state=42)
        self._label_encoder = LabelEncoder()
        y = self._label_encoder.fit_transform(labels)
        self._classifier.fit(X, y)
        self.is_trained = True
        logger.info(f"✅ Classifieur entraîné sur {len(texts)} exemples.")

    # ------------------------------------------------------------------
    # Vectorisation
    # ------------------------------------------------------------------
    def _mean_pooling(
        self, token_embeddings: torch.Tensor, attention_mask: torch.Tensor
    ) -> torch.Tensor:
        """Mean pooling pondéré par le masque d'attention."""
        expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        return torch.sum(token_embeddings * expanded, 1) / torch.clamp(
            expanded.sum(1), min=1e-9
        )

    def _vectorize_sync(self, texts: List[str]) -> np.ndarray:
        """Vectorisation synchrone (utilisée à l'entraînement)."""
        assert self._tokenizer is not None and self._model is not None
        encoded = self._tokenizer(
            texts, padding=True, truncation=True, return_tensors="pt", max_length=128
        ).to(self.device)
        with torch.no_grad():
            outputs = self._model(**encoded)
        emb = self._mean_pooling(outputs.last_hidden_state, encoded["attention_mask"])
        result = torch.nn.functional.normalize(emb, p=2, dim=1).cpu().numpy()
        # [FIX MPS] Remplacer NaN/inf par 0 avant de passer à sklearn
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
        return result

    async def _vectorize(self, texts: List[str]) -> np.ndarray:
        """Vectorisation asynchrone (utilisée à l'inférence)."""
        await self._ensure_loaded()
        assert self._tokenizer is not None and self._model is not None
        encoded = self._tokenizer(
            texts, padding=True, truncation=True, return_tensors="pt", max_length=128
        ).to(self.device)
        with torch.no_grad():
            outputs = self._model(**encoded)
        emb = self._mean_pooling(outputs.last_hidden_state, encoded["attention_mask"])
        result = torch.nn.functional.normalize(emb, p=2, dim=1).cpu().numpy()
        # [FIX MPS] Remplacer NaN/inf par 0 avant de passer à sklearn
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
        return result

    # ------------------------------------------------------------------
    # Prédiction
    # ------------------------------------------------------------------
    async def predict(self, query: str) -> Tuple[str, float]:
        """
        Prédit le type de requête et retourne (type, confiance).

        Returns:
            Tuple (query_type: str, confidence: float)
        """
        if not self.is_trained or self._classifier is None:
            return self._fallback(query), 0.5

        X = await self._vectorize([query])
        probs = self._classifier.predict_proba(X)[0]
        pred_idx = int(np.argmax(probs))
        confidence = float(probs[pred_idx])
        pred_label: str = self._label_encoder.inverse_transform([pred_idx])[0]
        return pred_label, confidence

    def _fallback(self, query: str) -> str:
        """Fallback déterministe basé sur mots-clés (synchrone, utilisé pour les stats)."""
        q = query.lower().strip()
        greetings = ["bonjour", "salut", "hello", "coucou", "merci", "au revoir", "bye", "hi"]
        if q in greetings or any(g in q for g in greetings):
            return "greeting"
        if any(kw in q for kw in ["mail", "email", "courriel", "message"]):
            return "mail"
        if any(kw in q for kw in ["safari", "navigateur", "internet", "page web", "url", "site", "recherche"]):
            return "safari"
        if any(kw in q for kw in ["côte à côte", "side by side", "organise", "grille", "disposition", "mosaïque"]):
            return "arrange"
        if any(kw in q for kw in ["ouvre", "lance", "tape", "clique", "capture", "open", "launch", "type", "click", "écris", "ecris"]):
            return "multi_action" if (" et " in q or " puis " in q) else "action"
        if any(kw in q for kw in ["explique", "décris", "comment", "pourquoi", "raconte", "défini", "c'est quoi", "qu'est-ce que"]):
            return "complex"
        return "simple" if len(q.split()) < 5 else "complex"


# =============================================================================
# Prédicteur asynchrone
# =============================================================================
class NanoPredictor:
    """
    Prédicteur temps réel : analyse le texte partiel toutes les 0.5 s et
    prépare une action candidate via le LLM nano (0.5B).

    Cycle de vie :
      - Instancié dans FrontalCortex.__init__
      - Démarré lazily dans FrontalCortex.think() via start(loop)
      - Arrêté dans FrontalCortex.stop()
    """

    def __init__(
        self,
        manager: ProviderManager,
        agents: Dict[str, BaseAgent],
        model_mapping: Dict[str, str],
    ) -> None:
        self.manager = manager
        self.agents = agents
        self.model_mapping = model_mapping
        self.current_text: str = ""
        self.last_prediction: Optional[Dict[str, Any]] = None
        self.last_update: float = 0.0
        self._lock: Optional[asyncio.Lock] = None  # créé lazily dans start()
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Démarre la tâche de prédiction. Appelé depuis le thread de la boucle."""
        if self._task is not None:
            return
        self._lock = asyncio.Lock()
        self._running = True
        self._task = loop.create_task(self._run())
        logger.info("🧠 NanoPredictor démarré.")

    async def stop(self) -> None:
        """Arrête proprement la tâche de prédiction."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NanoPredictor arrêté.")

    def update_partial_input(self, text: str) -> None:
        """Appelé par le HUD à chaque keystroke."""
        self.current_text = text

    async def _run(self) -> None:
        """Boucle principale : inférence toutes les 0.5 s si le texte a changé."""
        last_text = ""
        while self._running:
            await asyncio.sleep(0.5)
            text = self.current_text
            if text and text != last_text and len(text) > 3:
                last_text = text
                await self._predict(text)

    async def _predict(self, text: str) -> None:
        """
        Génère une action candidate depuis le texte partiel.

        [P11] Validation stricte :
          - Rejette les agents inconnus (ex: "ReminderAgent.create_reminder")
          - Rejette les tools inconnus pour l'agent
          - Rejette les réponses qui répètent le prompt (hallucination nano)
        """
        # Liste blanche des agents valides
        valid_agents = set(self.agents.keys())

        # Construire les outils disponibles par agent
        tools_by_agent: Dict[str, set] = {
            name: {tool.name for tool in agent.get_tools()}
            for name, agent in self.agents.items()
        }
        tools_desc = [
            f"- {name} | {tool.name}: {tool.description}"
            for name, agent in self.agents.items()
            for tool in agent.get_tools()
        ]
        tools_str = "\n".join(tools_desc)

        # Prompt plus strict pour éviter que le nano répète le prompt
        prompt = (
            f"Agents disponibles : {', '.join(valid_agents)}\n"
            f"Outils :\n{tools_str}\n\n"
            f'Demande partielle : "{text}"\n\n'
            f"Réponds UNIQUEMENT avec ce JSON (sans texte autour) :\n"
            f'{{"agent": "NomAgent", "tool": "nom_outil", "parameters": {{}}}}\n'
            f"Si aucune action claire, réponds : {{}}"
        )
        try:
            model_name = self.model_mapping.get("nano", "qwen2.5:0.5b")
            loop = asyncio.get_running_loop()
            response: str = await loop.run_in_executor(
                None,
                lambda: self.manager.generate(
                    prompt=prompt, system="", model=model_name,
                    temperature=0.1, max_tokens=128, timeout=2.0,
                ),
            )
            raw = response.strip()

            # [P11] Rejet si la réponse contient du texte du prompt (hallucination)
            hallucination_markers = [
                "tu es un assistant", "agents disponibles", "outils disponibles",
                "demande partielle", "réponds uniquement",
            ]
            if any(marker in raw.lower() for marker in hallucination_markers):
                logger.debug("Prédiction rejetée : hallucination détectée")
                return

            match = re.search(r"(\{.*\})", raw, re.DOTALL)
            if not match:
                return

            action = parse_json_safely(match.group(1))
            if not action or "agent" not in action or "tool" not in action:
                return

            agent_name = str(action.get("agent", ""))
            tool_name = str(action.get("tool", ""))

            # [P11] Rejet si agent invalide (ex: "ReminderAgent.create_reminder")
            if "." in agent_name or agent_name not in valid_agents:
                logger.debug(f"Prédiction rejetée : agent inconnu '{agent_name}'")
                return

            # [P11] Rejet si tool inconnu pour cet agent
            if tool_name not in tools_by_agent.get(agent_name, set()):
                logger.debug(f"Prédiction rejetée : tool '{tool_name}' inconnu pour '{agent_name}'")
                return

            assert self._lock is not None
            async with self._lock:
                self.last_prediction = action
                self.last_update = time.time()
                logger.debug(f"✅ Prédiction valide: {action}")

        except Exception as exc:
            logger.debug(f"Erreur prédiction: {exc}")

    async def get_prediction(self) -> Optional[Dict[str, Any]]:
        """Retourne la dernière prédiction valide (< 3 s) ou None."""
        if self._lock is None:
            return None
        async with self._lock:
            if self.last_prediction and (time.time() - self.last_update) < 3.0:
                return dict(self.last_prediction)
        return None


# =============================================================================
# Sélecteur de chemin avec classification sémantique
# =============================================================================
class ActionSelector:
    """
    Sélecteur de chemin basé sur le principe de moindre action.

    Ordonne les chemins par temps moyen observé (ascendant).
    Tiebreaker déterministe via DEFAULT_PATH_PRIORITY, avec possibilité de
    surcharge par type via TYPE_SPECIFIC_PRIORITY. [P8]
    """

    DEFAULT_PATH_PRIORITY: Dict[str, int] = {
        "direct_action": 1,
        "multi_action": 2,
        "cache_response": 3,
        "predicted_action": 4,
        "semantic_parsing": 5,
        "llm_nano": 6,
        "llm_speed": 7,
        "llm_balanced": 8,
        "plan_generation": 9,
    }

    # [P8] Priorités spécifiques par type de requête
    # Pour un type donné, on peut définir un ordre différent. Les chemins non listés
    # utiliseront DEFAULT_PATH_PRIORITY.
    TYPE_SPECIFIC_PRIORITY: Dict[str, Dict[str, int]] = {
        "greeting": {
            "llm_nano": 1,          # réponse rapide
            "cache_response": 2,     # si déjà en cache
            "direct_action": 10,     # très faible priorité car inutile
            "multi_action": 11,
            "predicted_action": 12,
            "semantic_parsing": 13,
            "plan_generation": 14,
        },
        "simple": {
            "llm_speed": 1,          # modèle rapide mais pas trop restrictif
            "llm_nano": 2,
            "cache_response": 3,
            "llm_balanced": 4,
            "direct_action": 5,
            "multi_action": 6,
            "predicted_action": 7,
            "semantic_parsing": 8,
            "plan_generation": 9,
        },
        "action": {
            "direct_action": 1,
            "multi_action": 2,
            "llm_speed": 3,
            "llm_nano": 4,
            "llm_balanced": 5,
            "cache_response": 6,
            "predicted_action": 7,
            "semantic_parsing": 8,
            "plan_generation": 9,
        },
        "complex": {
            "llm_balanced": 1,        # meilleur modèle pour les questions complexes
            "plan_generation": 2,
            "llm_speed": 3,
            "cache_response": 4,
            "semantic_parsing": 5,
            "llm_nano": 6,
            "direct_action": 7,
            "multi_action": 8,
            "predicted_action": 9,
        },
        "mail": {
            "llm_balanced": 1,        # modèle performant pour rédiger
            "plan_generation": 2,
            "llm_speed": 3,
            "cache_response": 4,
            "semantic_parsing": 5,
            "direct_action": 6,       # pourrait tomber sur une action mail
            "multi_action": 7,
            "predicted_action": 8,
            "llm_nano": 9,
        },
        "safari": {
            "direct_action": 1,
            "multi_action": 2,
            "llm_speed": 3,
            "llm_balanced": 4,
            "cache_response": 5,
            "semantic_parsing": 6,
            "predicted_action": 7,
            "llm_nano": 8,
            "plan_generation": 9,
        },
        "arrange": {
            "direct_action": 1,
            "multi_action": 2,
            "plan_generation": 3,
            "llm_speed": 4,
            "llm_balanced": 5,
            "cache_response": 6,
            "semantic_parsing": 7,
            "predicted_action": 8,
            "llm_nano": 9,
        },
    }

    def __init__(self, classifier: EmbeddingClassifier) -> None:
        self.stats: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(
            lambda: defaultdict(lambda: {"sum": 0.0, "count": 0, "failures": 0})
        )
        self.paths: Dict[str, Dict[str, Any]] = {}
        self.classifier = classifier

    def register_path(self, path_id: str, func: Callable, description: str = "") -> None:
        """Enregistre un chemin d'exécution."""
        self.paths[path_id] = {"func": func, "description": description}

    async def get_paths_for_query(self, query: str) -> List[Tuple[str, Callable]]:
        """
        Retourne les chemins triés par temps moyen (principe de moindre action),
        en tenant compte des priorités spécifiques au type de requête.

        Returns:
            Liste de (path_id, callable) triée du plus rapide au plus lent.
        """
        query_type, confidence = await self.classifier.predict(query)
        if confidence < self.classifier.confidence_threshold:
            query_type = self.classifier._fallback(query)
            logger.debug(f"Confiance faible ({confidence:.2f}) → fallback: {query_type}")

        type_stats = self.stats[query_type]

        # Récupère les priorités spécifiques pour ce type, ou dictionnaire vide
        specific_prio = self.TYPE_SPECIFIC_PRIORITY.get(query_type, {})

        def _sort_key(pid: str) -> Tuple[float, int]:
            s = type_stats.get(pid, {"sum": 0.0, "count": 0})
            avg = s["sum"] / s["count"] if s["count"] > 0 else float("inf")
            # Priorité : spécifique si définie, sinon globale
            priority = specific_prio.get(pid, self.DEFAULT_PATH_PRIORITY.get(pid, 99))
            return (avg, priority)

        sorted_pids = sorted(self.paths.keys(), key=_sort_key)
        return [(pid, self.paths[pid]["func"]) for pid in sorted_pids]

    def record_success(self, query: str, path_id: str, duration: float) -> None:
        """Enregistre un succès."""
        query_type = self.classifier._fallback(query)
        s = self.stats[query_type][path_id]
        s["sum"] += duration
        s["count"] += 1

    def record_failure(self, query: str, path_id: str) -> None:
        """Enregistre un échec (pénalité de 10 s)."""
        query_type = self.classifier._fallback(query)
        s = self.stats[query_type][path_id]
        s["failures"] += 1
        s["sum"] += 10.0
        s["count"] += 1


# =============================================================================
# Cortex frontal
# =============================================================================
class FrontalCortex:
    """
    Cortex frontal — Orchestrateur des agents et de la planification.

    Interface publique :
      - think(query) → (réponse, durée)
      - stop()       → arrêt propre
    """

    SIMPLE_ACTIONS: Dict[str, Tuple[str, str]] = {
        "ouvre": ("ComputerControlAgent", "open_application"),
        "open": ("ComputerControlAgent", "open_application"),
        "lance": ("ComputerControlAgent", "open_application"),
        "tape": ("ComputerControlAgent", "type_text"),
        "écris": ("ComputerControlAgent", "type_text"),
        "ecris": ("ComputerControlAgent", "type_text"),
        "type": ("ComputerControlAgent", "type_text"),
        "clique": ("ComputerControlAgent", "click"),
        "click": ("ComputerControlAgent", "click"),
        "capture": ("ComputerControlAgent", "get_screenshot"),
        "screenshot": ("ComputerControlAgent", "get_screenshot"),
    }

    APP_ALIASES: Dict[str, str] = {
        "note": "Notes", "notes": "Notes",
        "calculatrice": "Calculator", "calculette": "Calculator",
        "safari": "Safari", "mail": "Mail",
        "calendrier": "Calendar", "rappels": "Reminders",
        "reminders": "Reminders", "calendar": "Calendar",
    }

    def __init__(
        self,
        manager: ProviderManager,
        bus: Any,
        event_bus: EventBus,
        prompt_cache: PromptCache,
        memory_service: MemoryService,
        elasticity_engine: ElasticityEngine,
        config: Dict[str, Any],
    ) -> None:
        self.manager = manager
        self.bus = bus
        self.event_bus = event_bus
        self.prompt_cache = prompt_cache
        self.memory = memory_service
        self.elasticity = elasticity_engine
        self.config = config
        self.web_search = WebSearch() if config.get("web_search", True) else None

        self.executor = TaskExecutor(max_workers=3, persist_path=None)

        self.agents: Dict[str, BaseAgent] = {}
        self._register_agents()

        self.default_system = "Tu es un assistant IA utile, amical et concis."
        self.base_plan_timeout: float = config.get("plan_timeout", 30.0)
        self.max_plan_retries: int = config.get("max_plan_retries", 1)
        self.enable_memory: bool = config.get("enable_memory", True)
        self.enable_elasticity: bool = config.get("enable_elasticity", True)

        self.model_mapping: Dict[str, str] = {
            "speed": config.get("speed_model", "qwen2.5:3b"),
            "balanced": config.get("balanced_model", "qwen2.5:7b"),
            "quality": config.get("quality_model", "qwen2.5:14b"),
            "nano": "qwen2.5:0.5b",
        }

        # [P1] Boucle capturée dans think(), pas ici
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Classifieur sémantique
        retrain: bool = config.get("retrain_classifier", False)
        self.classifier = EmbeddingClassifier(retrain=retrain)

        # Prédicteur — démarré lazily dans think()
        self.predictor = NanoPredictor(manager, self.agents, self.model_mapping)
        self._predictor_started: bool = False

        # [P6] Circuit breaker optionnel
        self._llm_circuit_breaker: Optional[CircuitBreaker] = None
        if config.get("enable_circuit_breaker", True):
            self._llm_circuit_breaker = CircuitBreaker(
                name="llm",
                failure_threshold=config.get("cb_failure_threshold", 5),
                recovery_timeout=config.get("cb_recovery_timeout", 60),
            )

        self.action_selector = ActionSelector(self.classifier)
        self._register_paths()

        logger.info(f"🧠 FrontalCortex initialisé avec {len(self.agents)} agents.")

    # ------------------------------------------------------------------
    # Enregistrement des agents (avec injection de event_bus)
    # ------------------------------------------------------------------
    def _register_agents(self) -> None:
        """Instancie et enregistre tous les agents."""
        agents_list: List[BaseAgent] = [
            ReminderAgent(self.manager, self.bus, {}),
            KnowledgeAgent(
                self.manager, self.bus,
                {
                    "max_results": 3,
                    "web_search": self.web_search,
                    "news_api_key": self.config.get("api_keys", {}).get("news_api_key"),
                },
            ),
            DocumentAgent(self.manager, self.bus, {"web_search": self.web_search}),
            TextExtractorAgent(self.manager, self.bus, self.config.get("vision", {})),
            ComputerControlAgent(self.manager, self.bus, {}),
        ]
        for agent in agents_list:
            # [FIX EVENT_BUS] Injection de l'event bus pour que l'agent puisse publier des erreurs
            agent.event_bus = self.event_bus
            self.agents[agent.name] = agent

    # ------------------------------------------------------------------
    # Enregistrement des chemins
    # ------------------------------------------------------------------
    def _register_paths(self) -> None:
        """Déclare tous les chemins d'exécution."""
        self.action_selector.register_path(
            "direct_action", self._execute_direct_action,  # maintenant coroutine
            "Exécution directe d'une action simple (mots-clés)",
        )
        self.action_selector.register_path(
            "multi_action", self._execute_multi_action,  # maintenant coroutine
            "Exécution séquentielle de plusieurs actions",
        )
        self.action_selector.register_path(
            "predicted_action", self._execute_predicted_action,
            "Action prédite par le nano (temps réel)",
        )
        self.action_selector.register_path(
            "semantic_parsing", self._execute_semantic_parsing,
            "Interprétation sémantique via LLM nano",
        )
        self.action_selector.register_path(
            "cache_response", self._get_cached_response,
            "Réponse depuis le cache exact",
        )
        self.action_selector.register_path(
            "llm_nano", lambda q: self._call_llm(q, "nano"),
            "LLM nano (0.5B) — réponse directe",
        )
        self.action_selector.register_path(
            "llm_speed", lambda q: self._call_llm(q, "speed"),
            "LLM speed (3B) — réponse directe",
        )
        self.action_selector.register_path(
            "llm_balanced", lambda q: self._call_llm(q, "balanced"),
            "LLM balanced (7B) — réponse directe",
        )
        self.action_selector.register_path(
            "plan_generation", self._generate_and_execute_plan,
            "Génération et exécution d'un plan",
        )

    # ------------------------------------------------------------------
    # Utilitaire : coroutine → thread sync (utilisé pour les chemins synchrones)
    # ------------------------------------------------------------------
    def _run_coro_sync(self, coro: Any, timeout: float = _THREAD_FUTURE_TIMEOUT) -> Any:
        """
        Exécute une coroutine depuis un thread synchrone via la boucle principale.

        Raises:
            RuntimeError: boucle non initialisée.
            concurrent.futures.TimeoutError: si timeout atteint.
        """
        if self._loop is None:
            raise RuntimeError(
                "Boucle asyncio non initialisée — think() doit être appelé en premier."
            )
        print(f"RUN_CORO_SYNC: lancement de {coro} avec timeout {timeout}")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            logger.error(f"Timeout dans _run_coro_sync après {timeout}s")
            raise
        except Exception as e:
            # [P19] Logguer l'exception avec la trace pour diagnostic
            logger.error(f"Exception dans _run_coro_sync: {e}", exc_info=True)
            raise

    # [P12, P15] Système prompt pour le nano (factorisé)
    def _get_nano_system(self) -> str:
        """Retourne le system prompt adapté au modèle nano (plus amical)."""
        return (
            "Tu es un assistant personnel local, amical et direct. "
            "Tu réponds en français, de façon concise (1-3 phrases max). "
            "Tu peux aider sur tous les sujets du quotidien : conseils, motivation, "
            "information, conversation. Tu ne refuses jamais une question légitime."
        )

    # ------------------------------------------------------------------
    # Chemins d'exécution
    # ------------------------------------------------------------------
    async def _execute_direct_action(self, query: str) -> str:
        """Chemin 1 : action directe via SIMPLE_ACTIONS (version asynchrone)."""
        route = self._route_simple_action(query)
        if route:
            agent_name, action = route
            agent = self.agents.get(agent_name)
            if agent:
                logger.debug(f"🔧 Exécution directe : {agent_name}.{action['tool']} avec paramètres {action['parameters']}")
                print(f"APPEL A EXECUTE_TOOL: {agent_name}.{action['tool']} avec params {action['parameters']}")
                try:
                    # Appel direct de la coroutine (plus de _run_coro_sync)
                    result: str = await agent.execute_tool(action["tool"], action["parameters"])
                except Exception as e:
                    logger.error(f"Erreur dans direct_action: {e}", exc_info=True)
                    raise
                if result.startswith("❌"):
                    raise Exception(f"L'outil a retourné une erreur: {result}")
                return result
        raise Exception("Aucune action directe trouvée")

    async def _execute_multi_action(self, query: str) -> str:
        """Chemin 2 : exécution séquentielle (et/puis) - version asynchrone."""
        parts = re.split(r"\s+(et|puis)\s+", query, flags=re.IGNORECASE)
        results: List[str] = []
        for part in parts:
            part = part.strip()
            if not part or part.lower() in ("et", "puis"):
                continue
            route = self._route_simple_action(part)
            if not route:
                raise Exception(f"Impossible de traiter la sous-action: {part}")
            agent_name, action = route
            agent = self.agents.get(agent_name)
            if not agent:
                raise Exception(f"Agent {agent_name} introuvable")
            try:
                # Appel direct de la coroutine avec asyncio.wait_for pour timeout
                result = await asyncio.wait_for(
                    agent.execute_tool(action["tool"], action["parameters"]),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                raise Exception(f"Timeout sur l'étape '{part}'")
            if result.startswith("❌"):
                raise Exception(f"Échec de la sous-action: {result}")
            results.append(result)
        if results:
            return "\n".join(results)
        raise Exception("Aucune action multiple trouvée")

    def _execute_predicted_action(self, query: str) -> str:
        """Chemin 3 : action prédite par le NanoPredictor."""
        # [P13] Timeout réduit à 1s
        prediction = self._run_coro_sync(self.predictor.get_prediction(), timeout=1.0)
        if not prediction:
            raise Exception("Aucune prédiction disponible")
        agent_name = prediction.get("agent")
        tool_name = prediction.get("tool")
        params = prediction.get("parameters", {})
        if not agent_name or not tool_name:
            raise Exception("Prédiction incomplète")
        agent = self.agents.get(agent_name)
        if not agent:
            raise Exception(f"Agent {agent_name} inconnu")
        result = self._run_coro_sync(agent.execute_tool(tool_name, params))
        if result.startswith("❌"):
            raise Exception(f"Échec de l'action prédite: {result}")
        return result

    def _execute_semantic_parsing(self, query: str) -> str:
        """Chemin 4 : parse via LLM nano pour extraire des actions JSON."""
        tools_desc = [
            f"- {name}.{tool.name}: {tool.description}"
            for name, agent in self.agents.items()
            for tool in agent.get_tools()
        ]
        tools_str = "\n".join(tools_desc)
        prompt = (
            f"Tu es un assistant qui traduit des demandes en actions JSON.\n"
            f"Outils disponibles :\n{tools_str}\n\n"
            f'Demande : "{query}"\n\n'
            f"Génère une liste JSON d'actions (agent, tool, parameters, description).\n"
            f"Si aucune action, retourne [].\nRéponds uniquement avec le JSON."
        )
        try:
            model_name = self.model_mapping.get("nano", "qwen2.5:0.5b")
            response = self.manager.generate(
                prompt=prompt, system="", model=model_name,
                temperature=0.1, max_tokens=512, timeout=3.0,
            )
            cleaned = response.strip()
            try:
                actions = parse_json_safely(cleaned, expected_type=list)
            except JSONParseError:
                match = re.search(r"(\[.*\])", cleaned, re.DOTALL)
                if not match:
                    raise Exception("Impossible de parser la réponse du LLM")
                actions = parse_json_safely(match.group(1), expected_type=list)

            if not actions:
                raise Exception("Aucune action générée")

            results: List[str] = []
            for act in actions:
                agent_name = act.get("agent")
                tool_name = act.get("tool")
                params = act.get("parameters", {})
                agent = self.agents.get(agent_name)
                if not agent:
                    raise Exception(f"Agent {agent_name} inconnu")
                result = self._run_coro_sync(agent.execute_tool(tool_name, params))
                if result.startswith("❌"):
                    raise Exception(f"Échec de l'action {tool_name}: {result}")
                results.append(result)
            return "\n".join(results)
        except Exception as exc:
            raise Exception(f"Échec parsing sémantique: {exc}") from exc

    def _get_cached_response(self, query: str) -> str:
        """Chemin 5 : réponse depuis le cache."""
        # [P16] Tenter les deux systèmes (nano et défaut)
        systems = [self._get_nano_system(), self.default_system]
        for system in systems:
            cached = self.prompt_cache.get(query, system=system, model="balanced")
            if cached:
                return cached
        raise Exception("Cache miss")

    def _call_llm(self, query: str, model_profile: str) -> str:
        """
        Chemin 6-8 : appel direct au LLM.
        [P6] Protégé par circuit breaker si activé.
        [P12] Prompt adaptatif pour le nano (moins restrictif).
        """
        model_name = self.model_mapping.get(model_profile)
        if not model_name:
            raise Exception(f"Profil de modèle inconnu: {model_profile}")

        enriched = self._enrich_query(query)
        word_count = len(query.split())
        timeout = min(5.0 * (1 + word_count / 50), 30.0)

        # [P12] System prompt adaptatif selon le profil
        if model_profile == "nano":
            system = self._get_nano_system()
        else:
            system = self.default_system

        def _generate() -> str:
            return self.manager.generate(
                prompt=enriched, system=system,
                model=model_name, temperature=0.5, max_tokens=256, timeout=timeout,
            )

        response: str = (
            self._llm_circuit_breaker.call(_generate)
            if self._llm_circuit_breaker is not None
            else _generate()
        )

        self.prompt_cache.put(query, system, "balanced", response)
        if self.enable_memory:
            self.memory.add_to_working(query, response)
            self.memory.add_episode(query, response, metadata={"latency": time.time()})
        return response

    def _generate_and_execute_plan(self, query: str) -> str:
        """Chemin 9 : génère et exécute un plan multi-étapes."""
        plan = self._generate_plan_with_retry(query)
        if not plan:
            raise Exception("Plan invalide")
        self._cache_plan(query, plan)
        timeout = self._get_dynamic_timeout(query, plan_needed=True)
        final_response = self._execute_plan(plan, query, timeout=timeout)
        self.prompt_cache.put(query, self.default_system, "balanced", final_response)
        if self.enable_memory:
            self.memory.add_to_working(query, final_response)
            self.memory.add_episode(
                query, final_response, metadata={"latency": time.time()}
            )
        return final_response

    def _safe_fallback(self, query: str) -> str:
        """Dernier recours."""
        logger.warning("Utilisation du fallback sécurisé.")
        return "Désolé, je n'ai pas pu traiter votre demande. Veuillez réessayer."

    # ------------------------------------------------------------------
    # Méthodes de support
    # ------------------------------------------------------------------
    def _route_simple_action(self, query: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Parse une action simple via SIMPLE_ACTIONS."""
        q = query.lower()
        for keyword, (agent_name, tool_name) in self.SIMPLE_ACTIONS.items():
            if keyword not in q:
                continue
            if tool_name == "open_application":
                rest = q.replace(keyword, "").strip()
                if rest.startswith(("et", "puis")):
                    continue
                rest = re.sub(r'^["\'](.*)["\']$', r"\1", rest)
                normalized = self.APP_ALIASES.get(rest.lower())
                if normalized:
                    rest = normalized
                return agent_name, {"tool": tool_name, "parameters": {"app_name": rest}}
            elif tool_name == "type_text":
                pattern = r"\b" + re.escape(keyword) + r'\s*"([^"]+)"'
                m = re.search(pattern, query, re.IGNORECASE)
                text = m.group(1) if m else query.replace(keyword, "", 1).strip()
                if text.lower().startswith(("et", "puis")):
                    return None
                app_m = re.search(r"(?:dans|sur)\s+([a-zA-Z]+)", q, re.IGNORECASE)
                params: Dict[str, Any] = {"text": text}
                if app_m:
                    params["app_name"] = app_m.group(1)
                return agent_name, {"tool": tool_name, "parameters": params}
            elif tool_name == "click":
                m = re.search(r"(\d+)[,\s]+(\d+)", query)
                if m:
                    return agent_name, {
                        "tool": tool_name,
                        "parameters": {"x": int(m.group(1)), "y": int(m.group(2))},
                    }
            elif tool_name == "get_screenshot":
                return agent_name, {"tool": tool_name, "parameters": {}}
        return None

    def _get_dynamic_timeout(self, query: str, plan_needed: bool) -> float:
        """Timeout dynamique basé sur la longueur de la requête."""
        base = self.base_plan_timeout if plan_needed else 5.0
        estimated = base * (1 + len(query.split()) / 100)
        return min(estimated, self.base_plan_timeout * 2)

    def _enrich_query(self, query: str) -> str:
        """Enrichit la requête avec le contexte mémoire récent."""
        if self.enable_memory:
            ctx = self.memory.get_working_context(n=3)
            if ctx:
                return f"Contexte récent:\n{ctx}\n\n{query}"
        return query

    def _build_agents_description(self) -> str:
        """Description textuelle des agents et leurs outils."""
        return "\n".join(
            f"- {name}: {', '.join(t.name for t in agent.get_tools())}"
            for name, agent in self.agents.items()
        )

    def _get_cached_plan(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """Récupère un plan depuis le cache sémantique."""
        try:
            return self.prompt_cache.get_plan(query, similarity_threshold=0.75)
        except Exception as exc:
            logger.error(f"Erreur récupération plan cache: {exc}")
            return None

    def _cache_plan(self, query: str, plan: List[Dict[str, Any]]) -> None:
        """Persiste un plan dans le cache."""
        try:
            self.prompt_cache.put_plan(query, plan)
        except Exception as exc:
            logger.error(f"Erreur stockage plan cache: {exc}")

    def _generate_plan_with_retry(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """Génère un plan avec retry exponentiel."""
        for attempt in range(self.max_plan_retries + 1):
            try:
                plan = self._generate_plan(query)
                if plan and self._validate_plan(plan):
                    return plan
                logger.warning(f"Plan invalide, tentative {attempt + 1}")
            except Exception as exc:
                logger.error(f"Exception génération plan: {exc}")
            if attempt < self.max_plan_retries:
                time.sleep(0.5 * (attempt + 1))
        return None

    def _generate_plan(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """Appelle le LLM pour générer un plan JSON."""
        agents_desc = self._build_agents_description()
        prompt = (
            f'Planifie: "{query}"\n'
            f"Agents: {agents_desc}\n"
            f'Format JSON: [{{"id":"1","agent":"X","tool":"Y","parameters":{{}},"description":"…"}}]\n'
            f"Réponds uniquement avec le JSON, sinon []."
        )
        try:
            response = self.manager.generate(
                prompt=prompt, system="", model="speed",
                temperature=0.3, max_tokens=512,
            )
            cleaned = response.strip()
            try:
                plan = parse_json_safely(cleaned, expected_type=list)
                if plan:
                    return plan
            except JSONParseError:
                m = re.search(r"(\[.*\])", cleaned, re.DOTALL)
                if m:
                    plan = parse_json_safely(m.group(1), expected_type=list)
                    if plan:
                        return plan
            return None
        except Exception as exc:
            logger.error(f"Erreur génération plan: {exc}")
            return None

    def _validate_plan(self, plan: List[Dict[str, Any]]) -> bool:
        """Valide la structure d'un plan."""
        if not isinstance(plan, list):
            return False
        for step in plan:
            if "id" not in step or "agent" not in step:
                return False
            if step["agent"] not in self.agents:
                return False
        return True

    def _execute_plan(
        self, plan: List[Dict[str, Any]], query: str, timeout: float = 30.0
    ) -> str:
        """Exécute un plan via le TaskExecutor."""
        if not plan:
            return "Aucune action."

        from concurrent.futures import FIRST_EXCEPTION, wait

        task_futures: Dict[str, Dict[str, Any]] = {}
        step_tasks: Dict[str, str] = {}

        for step in plan:
            task = Task(
                id=step.get("id", str(time.time())),
                name=step.get("description", step["agent"]),
                func=self._execute_step,
                args=(step, {}),
                kwargs={},
            )
            if "depends_on" in step:
                task.dependencies = step["depends_on"]
            task_id = self.executor.submit(task)
            task_futures[task_id] = step
            step_tasks[step["id"]] = task_id

        futures = [self.executor.get_future(tid) for tid in task_futures]
        try:
            done, not_done = wait(futures, timeout=timeout, return_when=FIRST_EXCEPTION)
            if not_done:
                for f in not_done:
                    f.cancel()
                raise TimeoutError(f"Plan non terminé après {timeout}s")
            for f in done:
                if f.exception():
                    raise f.exception()

            results: List[str] = []
            for step in plan:
                tid = step_tasks[step["id"]]
                try:
                    results.append(self.executor.get_task_result(tid, timeout=0))
                except Exception as exc:
                    return f"Échec de l'étape '{step.get('description')}': {exc}"
        except (TimeoutError, Exception):
            for tid in task_futures:
                self.executor.cancel_task(tid)
            raise

        return results[0] if len(results) == 1 else self._synthesize(query, results)

    def _execute_step(self, *args: Any) -> str:
        """
        Exécute une étape du plan depuis un thread du TaskExecutor.

        [P1] run_coroutine_threadsafe avec timeout.
        [P5] Publie les erreurs sur event_bus.
        """
        if len(args) < 2:
            raise Exception(f"Arguments insuffisants: {len(args)}")

        step: Dict[str, Any] = args[-2]
        agent_name: str = step.get("agent", "")
        tool_name: Optional[str] = step.get("tool")
        params: Any = step.get("parameters", {})

        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {"content": params}
        if not isinstance(params, dict):
            params = {}

        agent = self.agents.get(agent_name)
        if not agent:
            raise Exception(f"Agent {agent_name} inconnu")

        step_timeout = self._get_dynamic_timeout(
            step.get("description", ""), plan_needed=False
        )

        try:
            coro = (
                agent.execute_tool(tool_name, params) if tool_name
                else agent.handle(params.get("query", ""))
            )
            result: str = self._run_coro_sync(coro, timeout=step_timeout)
            logger.info(f"✅ Étape '{step.get('description', '')}' OK")
            return result

        except ToolError as exc:
            error_payload = {
                "tool": tool_name, "agent": agent_name,
                "code": exc.code, "message": exc.message, "suggestion": exc.suggestion,
            }
            logger.error(f"❌ Erreur outil [{exc.code}]: {exc.message}")
            # [P5] Publication sur event_bus
            try:
                self._run_coro_sync(
                    self.event_bus.publish("tool.error", error_payload), timeout=2.0
                )
            except Exception as pub_exc:
                logger.warning(f"Impossible de publier sur event_bus: {pub_exc}")
            raise Exception(f"Erreur outil: {json.dumps(error_payload)}") from exc

        except Exception as exc:
            logger.error(f"❌ Erreur étape '{step.get('description', '')}': {exc}")
            try:
                self._run_coro_sync(
                    self.event_bus.publish("tool.error", {
                        "tool": tool_name, "agent": agent_name,
                        "code": "UNKNOWN", "message": str(exc), "suggestion": "",
                    }), timeout=2.0,
                )
            except Exception:
                pass
            raise

    def _synthesize(self, query: str, results: List[str]) -> str:
        """Synthétise plusieurs résultats via LLM speed."""
        if not results:
            return "Aucun résultat."
        if len(results) == 1:
            return results[0]
        if sum(len(r) for r in results) < 500 and len(results) <= 3:
            return "\n\n".join(results)
        prompt = (
            f'Résultats pour "{query}":\n'
            + "\n---\n".join(results)
            + "\nSynthèse concise:"
        )
        try:
            return self.manager.generate(
                prompt, self.default_system, model="speed", max_tokens=256
            )
        except Exception as exc:
            logger.error(f"Erreur synthèse: {exc}")
            return "\n\n".join(results)

    # ------------------------------------------------------------------
    # Interface publique
    # ------------------------------------------------------------------
    async def think(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        """
        Point d'entrée principal du Cortex.

        [P1] Capture la boucle asyncio courante.
        [P2] Démarre le NanoPredictor lazily.

        Returns:
            Tuple (réponse: str, durée: float)
        """
        # [P1] Capturer la boucle ici — garanti valide
        self._loop = asyncio.get_running_loop()

        # [P2] Démarrage lazy du prédicteur
        if not self._predictor_started:
            self.predictor.start(self._loop)
            self._predictor_started = True

        start = time.time()
        logger.info(f"🧠 think() — Requête: {query[:60]}…")

        paths = await self.action_selector.get_paths_for_query(query)
        logger.info(f"⚡ Ordre des chemins: {[p[0] for p in paths]}")

        last_error: Optional[Exception] = None
        for path_id, path_func in paths:
            try:
                # Vérifier si le chemin est une coroutine ou une fonction synchrone
                if asyncio.iscoroutinefunction(path_func):
                    response = await path_func(query)
                else:
                    response = path_func(query)
                duration = time.time() - start
                self.action_selector.record_success(query, path_id, duration)
                record_cortex_step(path_id, duration)
                logger.info(f"✅ Chemin '{path_id}' réussi en {duration:.3f}s")
                return response, duration
            except Exception as exc:
                logger.warning(f"⚠️  Chemin '{path_id}' échoué: {exc}")
                self.action_selector.record_failure(query, path_id)
                last_error = exc

        logger.error(f"Tous les chemins ont échoué. Dernière erreur: {last_error}")
        response = self._safe_fallback(query)
        duration = time.time() - start
        record_cortex_step("safe_fallback", duration)
        return response, duration

    async def stop(self) -> None:
        """Arrête proprement le Cortex."""
        await self.predictor.stop()
        self.executor.shutdown()
        logger.info("🛑 Cortex arrêté.")