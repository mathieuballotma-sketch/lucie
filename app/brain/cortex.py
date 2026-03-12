from __future__ import annotations

"""
Cortex central - Orchestrateur des agents et de la planification.
Version avec learning routing, memory manager et planner.
Conserve tous les chemins originaux et ajoute les améliorations.
"""

import asyncio
import concurrent.futures
import json
import random
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
from app.agents.planner_agent import PlannerAgent
from app.agents.reminder_agent import ReminderAgent
from app.agents.vision.text_extractor import TextExtractorAgent
from app.brain.synapses.event_bus import EventBus
from app.memory.memory_manager import MemoryManager

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

_THREAD_FUTURE_TIMEOUT: float = 2.0


# =============================================================================
# Classifieur sémantique (inchangé sauf correction MPS)
# =============================================================================
class EmbeddingClassifier:
    """
    Classifieur sémantique basé sur embeddings utilisant un modèle transformers.
    Supporte MPS avec nettoyage NaN.
    """

    QUERY_TYPES: List[str] = [
        "greeting", "action", "multi_action", "simple",
        "complex", "mail", "safari", "arrange",
    ]

    TRAINING_EXAMPLES: List[Tuple[str, str]] = [
        # ... (liste complète, identique à celle d'origine, avec les nouveaux exemples pour actions composées)
        ("bonjour", "greeting"), ("salut", "greeting"), ("hello", "greeting"),
        ("coucou", "greeting"), ("merci", "greeting"), ("au revoir", "greeting"),
        ("bye", "greeting"), ("hi", "greeting"), ("bonsoir", "greeting"),
        ("comment ça va", "greeting"), ("comment sa va", "greeting"),
        ("ça va ?", "greeting"), ("sa va ?", "greeting"),
        ("comment tu vas", "greeting"), ("tu vas bien ?", "greeting"),
        ("quoi de neuf", "greeting"), ("bien ou bien", "greeting"),
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
        ("écris un poème", "complex"), ("explique la relativité", "complex"),
        ("parle-moi de l'univers", "complex"),
        ("rédige un rapport sur l'IA", "complex"),
        ("comment devenir riche", "complex"),
        ("explique-moi comment investir", "complex"),
        ("comment améliorer ma productivité", "complex"),
        ("ouvre notes", "action"), ("lance calculatrice", "action"),
        ("tape bonjour", "action"), ("clique à 500 300", "action"),
        ("capture écran", "action"), ("ouvre safari", "action"),
        ("ouvre mail", "action"), ("prends une capture d'écran", "action"),
        ("ouvre safari et tape google", "multi_action"),
        ("lance mail puis écris bonjour", "multi_action"),
        ("ouvre notes et safari", "multi_action"),
        ("ouvre notes et safari et mail", "multi_action"),
        ("envoie un email à john", "mail"), ("compose un message pour marie", "mail"),
        ("écris un email à Paul", "mail"), ("rédige un mail professionnel", "mail"),
        ("ouvre safari sur google", "safari"), ("va sur youtube", "safari"),
        ("recherche chat sur le web", "safari"), ("navigue vers apple.com", "safari"),
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
        self.device = torch.device(
            "mps" if torch.backends.mps.is_available()
            else "cuda" if torch.cuda.is_available()
            else "cpu"
        )
        logger.info(f"🖥️  Device utilisé pour les embeddings : {self.device}")

        self._tokenizer: Optional[Any] = None
        self._model: Optional[Any] = None
        self._load_lock: Optional[asyncio.Lock] = None

        self._classifier: Optional[LogisticRegression] = None
        self._label_encoder: Optional[LabelEncoder] = None
        self.is_trained: bool = False
        self.confidence_threshold: float = 0.7

        self.model_path: Path = Path(__file__).parent / "classifier.joblib"

        if retrain or not self.model_path.exists():
            self._train_sync()
            self._save()
        else:
            self._load_classifier_only()

    async def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
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

    def _save(self) -> None:
        joblib.dump(
            {"classifier": self._classifier, "label_encoder": self._label_encoder},
            self.model_path,
        )
        logger.info(f"💾 Classifieur sauvegardé dans {self.model_path}")

    def _load_classifier_only(self) -> None:
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

    def _train_sync(self) -> None:
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

    def _mean_pooling(
        self, token_embeddings: torch.Tensor, attention_mask: torch.Tensor
    ) -> torch.Tensor:
        expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        return torch.sum(token_embeddings * expanded, 1) / torch.clamp(
            expanded.sum(1), min=1e-9
        )

    def _vectorize_sync(self, texts: List[str]) -> np.ndarray:
        assert self._tokenizer is not None and self._model is not None
        encoded = self._tokenizer(
            texts, padding=True, truncation=True, return_tensors="pt", max_length=128
        ).to(self.device)
        with torch.no_grad():
            outputs = self._model(**encoded)
        emb = self._mean_pooling(outputs.last_hidden_state, encoded["attention_mask"])
        result = torch.nn.functional.normalize(emb, p=2, dim=1).cpu().numpy()
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
        return result

    async def _vectorize(self, texts: List[str]) -> np.ndarray:
        await self._ensure_loaded()
        assert self._tokenizer is not None and self._model is not None
        encoded = self._tokenizer(
            texts, padding=True, truncation=True, return_tensors="pt", max_length=128
        ).to(self.device)
        with torch.no_grad():
            outputs = self._model(**encoded)
        emb = self._mean_pooling(outputs.last_hidden_state, encoded["attention_mask"])
        result = torch.nn.functional.normalize(emb, p=2, dim=1).cpu().numpy()
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
        return result

    async def predict(self, query: str) -> Tuple[str, float]:
        if not self.is_trained or self._classifier is None:
            return self._fallback(query), 0.5
        X = await self._vectorize([query])
        probs = self._classifier.predict_proba(X)[0]
        pred_idx = int(np.argmax(probs))
        confidence = float(probs[pred_idx])
        pred_label: str = self._label_encoder.inverse_transform([pred_idx])[0]
        return pred_label, confidence

    def _fallback(self, query: str) -> str:
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
# Prédicteur temps réel (NanoPredictor) – inchangé
# =============================================================================
class NanoPredictor:
    """
    Prédicteur temps réel : analyse le texte partiel toutes les 0.5 s et
    prépare une action candidate via le LLM nano (0.5B).
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
        self._lock: Optional[asyncio.Lock] = None
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._task is not None:
            return
        self._lock = asyncio.Lock()
        self._running = True
        self._task = loop.create_task(self._run())
        logger.info("🧠 NanoPredictor démarré.")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NanoPredictor arrêté.")

    def update_partial_input(self, text: str) -> None:
        self.current_text = text

    async def _run(self) -> None:
        last_text = ""
        while self._running:
            await asyncio.sleep(0.5)
            text = self.current_text
            if text and text != last_text and len(text) > 3:
                last_text = text
                await self._predict(text)

    async def _predict(self, text: str) -> None:
        valid_agents = set(self.agents.keys())
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

            if "." in agent_name or agent_name not in valid_agents:
                logger.debug(f"Prédiction rejetée : agent inconnu '{agent_name}'")
                return

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
        if self._lock is None:
            return None
        async with self._lock:
            if self.last_prediction and (time.time() - self.last_update) < 3.0:
                return dict(self.last_prediction)
        return None


# =============================================================================
# Learning Router (ActionSelector amélioré)
# =============================================================================
class PathStats:
    """Statistiques d'un chemin d'exécution."""
    def __init__(self):
        self.success = 0
        self.fail = 0
        self.total_time = 0.0
        self.count = 0

    @property
    def success_rate(self) -> float:
        total = self.success + self.fail
        return self.success / total if total > 0 else 0.0

    @property
    def avg_time(self) -> float:
        return self.total_time / self.count if self.count > 0 else float('inf')

    def record_success(self, duration: float):
        self.success += 1
        self.count += 1
        self.total_time += duration

    def record_failure(self):
        self.fail += 1


class ActionSelector:
    """
    Sélecteur de chemin avec apprentissage par renforcement.
    Combine statistiques de performance et priorités statiques.
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

    TYPE_SPECIFIC_PRIORITY: Dict[str, Dict[str, int]] = {
        "greeting": {
            "llm_nano": 1,
            "cache_response": 2,
            "direct_action": 10,
            "multi_action": 11,
            "predicted_action": 12,
            "semantic_parsing": 13,
            "plan_generation": 14,
        },
        "simple": {
            "llm_speed": 1,
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
            "llm_balanced": 1,
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
            "llm_balanced": 1,
            "plan_generation": 2,
            "llm_speed": 3,
            "cache_response": 4,
            "semantic_parsing": 5,
            "direct_action": 6,
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
        self.stats: Dict[str, Dict[str, PathStats]] = defaultdict(lambda: defaultdict(PathStats))
        self.paths: Dict[str, Dict[str, Any]] = {}
        self.classifier = classifier
        self.epsilon = 0.05  # 5% d'exploration

    def register_path(self, path_id: str, func: Callable, description: str = "") -> None:
        self.paths[path_id] = {"func": func, "description": description}

    async def get_paths_for_query(self, query: str) -> List[Tuple[str, Callable]]:
        query_type, confidence = await self.classifier.predict(query)
        if confidence < self.classifier.confidence_threshold:
            query_type = self.classifier._fallback(query)
            logger.debug(f"Confiance faible ({confidence:.2f}) → fallback: {query_type}")

        type_stats = self.stats[query_type]

        # Exploration epsilon-greedy
        if random.random() < self.epsilon:
            candidates = list(self.paths.keys())
            if len(candidates) > 3:
                candidates = candidates[:3]
            path_id = random.choice(candidates)
            logger.debug(f"Exploration: choix aléatoire de {path_id}")
            return [(path_id, self.paths[path_id]["func"])]

        # Sinon, tri par score décroissant
        def _score(pid: str) -> float:
            s = type_stats.get(pid)
            if s is None or s.count == 0:
                # Pas de stats : utiliser la priorité statique
                priority = self.TYPE_SPECIFIC_PRIORITY.get(query_type, {}).get(pid,
                            self.DEFAULT_PATH_PRIORITY.get(pid, 99))
                # Convertir priorité en score (plus petit = meilleur)
                return 1000 - priority
            # Score = taux de succès / (temps moyen + epsilon)
            eps = 0.001
            return s.success_rate / (s.avg_time + eps)

        sorted_pids = sorted(self.paths.keys(), key=_score, reverse=True)
        return [(pid, self.paths[pid]["func"]) for pid in sorted_pids]

    def record_success(self, query: str, path_id: str, duration: float) -> None:
        query_type = self.classifier._fallback(query)
        self.stats[query_type][path_id].record_success(duration)

    def record_failure(self, query: str, path_id: str) -> None:
        query_type = self.classifier._fallback(query)
        self.stats[query_type][path_id].record_failure()


# =============================================================================
# Cortex frontal (début)
# =============================================================================
class FrontalCortex:
    """
    Cortex frontal — Orchestrateur des agents et de la planification.
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

        # Memory Manager (nouveau)
        self.memory_manager = MemoryManager(memory_service, config)

        # Planner Agent (nouveau)
        self.planner = PlannerAgent(manager, bus, config)
        # Les agents seront injectés après enregistrement

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

        self._loop: Optional[asyncio.AbstractEventLoop] = None

        retrain: bool = config.get("retrain_classifier", False)
        self.classifier = EmbeddingClassifier(retrain=retrain)

        self.predictor = NanoPredictor(manager, self.agents, self.model_mapping)
        self._predictor_started: bool = False

        self._llm_circuit_breaker: Optional[CircuitBreaker] = None
        if config.get("enable_circuit_breaker", True):
            self._llm_circuit_breaker = CircuitBreaker(
                name="llm",
                failure_threshold=config.get("cb_failure_threshold", 5),
                recovery_timeout=config.get("cb_recovery_timeout", 60),
            )

        self.action_selector = ActionSelector(self.classifier)
        self._register_paths()

        # Injecter les agents dans le planner
        self.planner.set_agents(self.agents)

        logger.info(f"🧠 FrontalCortex initialisé avec {len(self.agents)} agents, memory manager et planner.")

    def _register_agents(self) -> None:
        """Instancie et enregistre tous les agents (avec injection de event_bus)."""
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
            agent.event_bus = self.event_bus
            self.agents[agent.name] = agent

    def _register_paths(self) -> None:
        """Déclare tous les chemins d'exécution."""
        self.action_selector.register_path(
            "direct_action", self._execute_direct_action,
            "Exécution directe d'une action simple (mots-clés)",
        )
        self.action_selector.register_path(
            "multi_action", self._execute_multi_action,
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
            "Génération et exécution d'un plan via PlannerAgent",
        )
        """
Memory Manager - Gère le contexte utilisateur en combinant mémoire court terme et long terme.
"""

from typing import Optional
from app.memory import MemoryService
from app.utils.logger import logger


class MemoryManager:
    def __init__(self, memory_service: MemoryService, config: dict):
        self.memory = memory_service
        self.max_short_term = config.get("max_short_term", 5)
        self.max_long_term = config.get("max_long_term", 3)

    async def get_context(self, user_id: str, query: str) -> str:
        """
        Récupère le contexte pertinent pour la requête.
        Args:
            user_id: identifiant de l'utilisateur (pour future extension multi-utilisateur)
            query: requête actuelle
        Returns:
            Chaîne de contexte formatée
        """
        context_parts = []

        # Mémoire à court terme (dernières interactions)
        short_term = self.memory.get_working_context(n=self.max_short_term)
        if short_term:
            context_parts.append(f"Conversation récente:\n{short_term}")

        # Mémoire à long terme (souvenirs similaires)
        long_term_results = self.memory.remember(query, n_results=self.max_long_term)
        if long_term_results:
            memories = []
            for res in long_term_results:
                # On suppose que chaque résultat a une clé 'response' ou 'content'
                response = res.get('response') or res.get('content') or str(res)
                memories.append(response)
            context_parts.append(f"Souvenirs pertinents:\n" + "\n".join(memories))

        return "\n\n".join(context_parts) if context_parts else ""