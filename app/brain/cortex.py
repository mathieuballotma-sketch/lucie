"""
Cortex central - Orchestrateur des agents et de la planification.
Version refactorisée avec séparation des responsabilités et robustesse accrue.
Incarne les lois universelles :
- Moindre action : optimisation des chemins, cache, timeouts adaptatifs.
- Homéostasie : gestion d'erreurs robuste, circuit breakers, publication sur event bus.
- Évolution : apprentissage des performances, création de nouveaux agents.
- Entropie : code modulaire, suppression des doublons, documentation.
- Symbiose : communication via event_bus, intégration harmonieuse des composants.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import random
import re
import time
import importlib.util
import sys
from collections import defaultdict
from concurrent.futures import TimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

import joblib
import numpy as np
import torch
from pydantic import BaseModel, ValidationError
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder
from transformers import AutoModel, AutoTokenizer
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from app.agents.base_agent import BaseAgent
from app.agents.computer_control_agent import ComputerControlAgent
from app.agents.creator_agent import CreatorAgent
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
from ..utils.errors import ToolError, PathExecutionError, AgentNotFoundError
from ..utils.json_parser import JSONParseError, parse_json_safely
from ..utils.logger import logger
from ..utils.metrics import record_cortex_step, MetricsCollector

_THREAD_FUTURE_TIMEOUT: float = 2.0


# -----------------------------------------------------------------------------
# Modèles de validation Pydantic
# -----------------------------------------------------------------------------
class UserQuery(BaseModel):
    """Requête utilisateur validée."""
    text: str
    allow_web_search: bool = True
    system_prompt: Optional[str] = None

    @classmethod
    def from_raw(cls, query: str, **kwargs) -> UserQuery:
        try:
            return cls(text=query, **kwargs)
        except ValidationError as e:
            raise ValueError(f"Requête invalide: {e}")


# -----------------------------------------------------------------------------
# Gestionnaire d'événements pour le dossier des agents personnalisés
# -----------------------------------------------------------------------------
class AgentFileHandler(FileSystemEventHandler):
    """Handler pour les événements de création/modification de fichiers dans le dossier des agents."""
    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.py'):
            self.registry.load_agent_from_file(Path(event.src_path))

    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.py'):
            self.registry.load_agent_from_file(Path(event.src_path))


# -----------------------------------------------------------------------------
# Registre des agents
# -----------------------------------------------------------------------------
class AgentRegistry:
    """Gère l'enregistrement et le chargement des agents standards et personnalisés."""

    def __init__(
        self,
        manager: ProviderManager,
        bus: Any,
        event_bus: EventBus,
        config: Dict[str, Any],
        custom_agents_dir: Path,
        cortex_token: str,  # Token du cortex pour que le registre publie au nom du cortex
    ):
        self.manager = manager
        self.bus = bus
        self.event_bus = event_bus
        self.config = config
        self.custom_agents_dir = custom_agents_dir
        self.cortex_token = cortex_token
        self.agents: Dict[str, BaseAgent] = {}
        self.observer: Optional[Observer] = None
        self._register_standard_agents()

    def _register_standard_agents(self) -> None:
        """Instancie et enregistre tous les agents standards."""
        web_search = WebSearch() if self.config.get("web_search", True) else None
        agents_list: List[BaseAgent] = [
            ReminderAgent(self.manager, self.bus, {}),
            KnowledgeAgent(
                self.manager, self.bus,
                {
                    "max_results": 3,
                    "web_search": web_search,
                    "news_api_key": self.config.get("api_keys", {}).get("news_api_key"),
                },
            ),
            DocumentAgent(self.manager, self.bus, {"web_search": web_search}),
            TextExtractorAgent(self.manager, self.bus, self.config.get("vision", {})),
            ComputerControlAgent(self.manager, self.bus, {}),
        ]
        # Création du CreatorAgent avec la liste dynamique des outils
        available_tools = self._get_all_tool_names()
        creator = CreatorAgent(
            self.manager, self.bus, self.event_bus, self.config,
            agents_dir=self.custom_agents_dir,
            available_tools=available_tools
        )
        agents_list.append(creator)

        for agent in agents_list:
            # Déterminer les droits de publication/souscription pour cet agent
            publish_channels = []
            subscribe_channels = []

            if isinstance(agent, CreatorAgent):
                publish_channels.append("agent.created")
            # Ajouter d'autres droits selon le type d'agent
            # Exemple: HealerAgent aura besoin de canaux, mais il n'est pas dans ce registre car il est créé dans engine.
            # Ici on gère uniquement les agents du cortex, donc on peut les lister.

            # Enregistrer la source sur l'event bus
            token = self.event_bus.register_source(
                source=agent.name,
                publish_channels=publish_channels,
                subscribe_channels=subscribe_channels
            )
            agent.set_token(token)  # On suppose que BaseAgent a une méthode set_token
            agent.event_bus = self.event_bus
            self.agents[agent.name] = agent
            logger.debug(f"Agent {agent.name} enregistré avec token {token[:8]}...")

    def _get_all_tool_names(self) -> List[str]:
        """Retourne la liste de tous les noms d'outils disponibles dans les agents standards."""
        tool_names = set()
        for agent in self.agents.values():
            for tool in agent.get_tools():
                tool_names.add(tool.name)
        return list(tool_names)

    def start_watcher(self) -> None:
        """Démarre la surveillance du dossier des agents personnalisés."""
        self.observer = Observer()
        handler = AgentFileHandler(self)
        self.observer.schedule(handler, str(self.custom_agents_dir), recursive=False)
        self.observer.start()
        logger.info(f"👀 Surveillance du dossier {self.custom_agents_dir} activée")

    def stop_watcher(self) -> None:
        if self.observer:
            self.observer.stop()
            self.observer.join()

    def load_agent_from_file(self, filepath: Path) -> None:
        """Charge dynamiquement un agent depuis un fichier Python et l'ajoute au registre."""
        try:
            module_name = filepath.stem
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                logger.error(f"Impossible de charger le module {filepath}")
                return
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseAgent) and attr != BaseAgent:
                    agent_instance = attr(self.manager, self.bus, self.config)
                    # Enregistrer l'agent sur l'event bus
                    # On ne connaît pas ses besoins en canaux, on lui donne des droits par défaut
                    token = self.event_bus.register_source(
                        source=agent_instance.name,
                        publish_channels=[],  # À définir si on veut lui donner des droits
                        subscribe_channels=[]
                    )
                    agent_instance.set_token(token)
                    agent_instance.event_bus = self.event_bus
                    self.agents[agent_instance.name] = agent_instance
                    logger.info(f"✅ Agent {agent_instance.name} chargé dynamiquement depuis {filepath}")
                    # Publier un événement avec le token du cortex
                    asyncio.create_task(self.event_bus.publish(
                        channel="agent.loaded",
                        data={"name": agent_instance.name},
                        source="AgentRegistry",
                        token=self.cortex_token
                    ))
                    return
            logger.warning(f"Aucune classe d'agent trouvée dans {filepath}")
        except Exception as e:
            logger.error(f"Erreur lors du chargement de {filepath}: {e}")
            asyncio.create_task(self.event_bus.publish(
                channel="tool.error",
                data={
                    "agent": "AgentRegistry",
                    "error": str(e),
                    "suggestion": "Vérifiez la syntaxe du fichier agent."
                },
                source="AgentRegistry",
                token=self.cortex_token
            ))

    def get_agent(self, name: str) -> BaseAgent:
        """Retourne un agent par son nom, lève AgentNotFoundError si absent."""
        agent = self.agents.get(name)
        if not agent:
            raise AgentNotFoundError(f"Agent '{name}' introuvable")
        return agent

    def list_agents(self) -> List[str]:
        return list(self.agents.keys())

    def get_all_tool_names(self) -> List[str]:
        """Retourne la liste de tous les noms d'outils disponibles (utile pour CreatorAgent)."""
        tool_names = set()
        for agent in self.agents.values():
            for tool in agent.get_tools():
                tool_names.add(tool.name)
        return list(tool_names)


# -----------------------------------------------------------------------------
# Classifieur sémantique (EmbeddingClassifier)
# -----------------------------------------------------------------------------
class EmbeddingClassifier:
    """
    Classifieur sémantique basé sur embeddings utilisant un modèle transformers.
    Supporte MPS avec nettoyage NaN.
    Incarne le principe d'évolution : le classifieur est réentraînable et s'améliore avec les données.
    """

    QUERY_TYPES: List[str] = [
        "greeting", "action", "multi_action", "simple",
        "complex", "mail", "safari", "arrange", "creation",
    ]

    TRAINING_EXAMPLES: List[Tuple[str, str]] = [
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
        # Nouveaux exemples pour la création d'agents
        ("crée un agent météo", "creation"),
        ("génère un agent qui surveille les prix", "creation"),
        ("je veux créer un nouvel assistant", "creation"),
        ("fabrique un agent pour mes rappels", "creation"),
        ("développe un agent de recherche", "creation"),
        ("crée un agent qui ouvre notes et écrit bonjour", "creation"),
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

        # Détection de création d'agent
        if any(kw in q for kw in ["crée un agent", "créer un agent", "génère un agent", "fabrique un agent"]):
            return "creation"

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


# -----------------------------------------------------------------------------
# Prédicteur temps réel (NanoPredictor)
# -----------------------------------------------------------------------------
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


# -----------------------------------------------------------------------------
# Learning Router (ActionSelector amélioré)
# -----------------------------------------------------------------------------
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
        "creation_agent": 10,
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
            "creation_agent": 15,
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
            "creation_agent": 10,
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
            "creation_agent": 10,
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
            "creation_agent": 10,
        },
        "mail": {
            "direct_action": 1,
            "llm_balanced": 2,
            "plan_generation": 3,
            "llm_speed": 4,
            "cache_response": 5,
            "semantic_parsing": 6,
            "multi_action": 7,
            "predicted_action": 8,
            "llm_nano": 9,
            "creation_agent": 10,
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
            "creation_agent": 10,
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
            "creation_agent": 10,
        },
        "creation": {
            "creation_agent": 1,
            "llm_balanced": 2,
            "plan_generation": 3,
            "llm_speed": 4,
            "cache_response": 5,
            "semantic_parsing": 6,
            "llm_nano": 7,
            "direct_action": 8,
            "multi_action": 9,
            "predicted_action": 10,
        },
    }

    def __init__(self, classifier: EmbeddingClassifier) -> None:
        self.stats: Dict[str, Dict[str, PathStats]] = defaultdict(lambda: defaultdict(PathStats))
        self.paths: Dict[str, Dict[str, Any]] = {}
        self.classifier = classifier
        self.epsilon = 0.05

    def register_path(self, path_id: str, func: Callable, description: str = "") -> None:
        self.paths[path_id] = {"func": func, "description": description}

    async def get_paths_for_query(self, query: str) -> List[Tuple[str, Callable]]:
        query_type, confidence = await self.classifier.predict(query)
        if confidence < self.classifier.confidence_threshold:
            query_type = self.classifier._fallback(query)
            logger.debug(f"Confiance faible ({confidence:.2f}) → fallback: {query_type}")

        type_stats = self.stats[query_type]

        if random.random() < self.epsilon:
            candidates = list(self.paths.keys())
            if len(candidates) > 3:
                candidates = candidates[:3]
            path_id = random.choice(candidates)
            logger.debug(f"Exploration: choix aléatoire de {path_id}")
            return [(path_id, self.paths[path_id]["func"])]

        def _score(pid: str) -> float:
            s = type_stats.get(pid)
            if s is None or s.count == 0:
                priority = self.TYPE_SPECIFIC_PRIORITY.get(query_type, {}).get(pid,
                            self.DEFAULT_PATH_PRIORITY.get(pid, 99))
                return 1000 - priority
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


class PathManager:
    """Gère l'enregistrement et la sélection des chemins d'exécution."""

    def __init__(self, classifier: EmbeddingClassifier, action_selector: ActionSelector):
        self.classifier = classifier
        self.selector = action_selector

    def register_all_paths(self, executor: ExecutionEngine) -> None:
        """Enregistre tous les chemins auprès du sélecteur."""
        self.selector.register_path(
            "direct_action", executor.execute_direct_action,
            "Exécution directe d'une action simple (mots-clés)",
        )
        self.selector.register_path(
            "multi_action", executor.execute_multi_action,
            "Exécution séquentielle de plusieurs actions",
        )
        self.selector.register_path(
            "predicted_action", executor.execute_predicted_action,
            "Action prédite par le nano (temps réel)",
        )
        self.selector.register_path(
            "semantic_parsing", executor.execute_semantic_parsing,
            "Interprétation sémantique via LLM nano",
        )
        self.selector.register_path(
            "cache_response", executor.get_cached_response,
            "Réponse depuis le cache exact",
        )
        self.selector.register_path(
            "llm_nano", lambda q: executor.call_llm(q, "nano"),
            "LLM nano (0.5B) — réponse directe",
        )
        self.selector.register_path(
            "llm_speed", lambda q: executor.call_llm(q, "speed"),
            "LLM speed (3B) — réponse directe",
        )
        self.selector.register_path(
            "llm_balanced", lambda q: executor.call_llm(q, "balanced"),
            "LLM balanced (7B) — réponse directe",
        )
        self.selector.register_path(
            "plan_generation", executor.generate_and_execute_plan,
            "Génération et exécution d'un plan via PlannerAgent",
        )
        self.selector.register_path(
            "creation_agent", executor.execute_creation_agent,
            "Création d'un nouvel agent via CreatorAgent",
        )

    async def select_paths(self, query: str) -> List[Tuple[str, Callable]]:
        return await self.selector.get_paths_for_query(query)

    def record_success(self, query: str, path_id: str, duration: float) -> None:
        self.selector.record_success(query, path_id, duration)

    def record_failure(self, query: str, path_id: str) -> None:
        self.selector.record_failure(query, path_id)


# -----------------------------------------------------------------------------
# Moteur d'exécution (ExecutionEngine)
# -----------------------------------------------------------------------------
class ExecutionEngine:
    """
    Exécute les différents chemins d'action.
    Utilise les agents, le cache, le LLM, etc.
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
        "rappel": "Reminders",
    }

    def __init__(
        self,
        registry: AgentRegistry,
        planner: PlannerAgent,
        manager: ProviderManager,
        prompt_cache: PromptCache,
        memory: MemoryService,
        event_bus: EventBus,
        config: Dict[str, Any],
        loop: asyncio.AbstractEventLoop,
        model_mapping: Dict[str, str],
        llm_circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.registry = registry
        self.planner = planner
        self.manager = manager
        self.prompt_cache = prompt_cache
        self.memory = memory
        self.event_bus = event_bus
        self.config = config
        self.loop = loop
        self.model_mapping = model_mapping
        self.llm_circuit_breaker = llm_circuit_breaker
        self.default_system = "Tu es un assistant IA utile, amical et concis."
        self.enable_memory = config.get("enable_memory", True)
        self.base_plan_timeout = config.get("plan_timeout", 30.0)

    def _run_coro_sync(self, coro: Any, timeout: float = _THREAD_FUTURE_TIMEOUT) -> Any:
        """Exécute une coroutine de manière synchrone dans le thread asyncio."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            logger.error(f"Timeout dans _run_coro_sync après {timeout}s")
            raise
        except Exception as e:
            logger.error(f"Exception dans _run_coro_sync: {e}", exc_info=True)
            raise

    async def execute_direct_action(self, query: str) -> str:
        route = self._route_simple_action(query)
        if route:
            agent_name, action = route
            try:
                agent = self.registry.get_agent(agent_name)
                logger.debug(f"🔧 Exécution directe : {agent_name}.{action['tool']}")
                result = await agent.execute_tool(action["tool"], action["parameters"])
                if result.startswith("❌"):
                    raise PathExecutionError(f"L'outil a retourné une erreur: {result}")
                return result
            except AgentNotFoundError as e:
                raise PathExecutionError(str(e)) from e
        raise PathExecutionError("Aucune action directe trouvée")

    async def execute_multi_action(self, query: str) -> str:
        parts = re.split(r"\s+(et|puis)\s+", query, flags=re.IGNORECASE)
        results = []
        for part in parts:
            part = part.strip()
            if not part or part.lower() in ("et", "puis"):
                continue
            route = self._route_simple_action(part)
            if not route:
                raise PathExecutionError(f"Impossible de traiter la sous-action: {part}")
            agent_name, action = route
            agent = self.registry.get_agent(agent_name)
            try:
                result = await asyncio.wait_for(
                    agent.execute_tool(action["tool"], action["parameters"]),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                raise PathExecutionError(f"Timeout sur l'étape '{part}'")
            if result.startswith("❌"):
                raise PathExecutionError(f"Échec de la sous-action: {result}")
            results.append(result)
        if results:
            return "\n".join(results)
        raise PathExecutionError("Aucune action multiple trouvée")

    def execute_predicted_action(self, query: str) -> str:
        prediction = self._run_coro_sync(self._get_prediction(), timeout=1.0)
        if not prediction:
            raise PathExecutionError("Aucune prédiction disponible")
        agent_name = prediction.get("agent")
        tool_name = prediction.get("tool")
        params = prediction.get("parameters", {})
        if not agent_name or not tool_name:
            raise PathExecutionError("Prédiction incomplète")
        agent = self.registry.get_agent(agent_name)
        result = self._run_coro_sync(agent.execute_tool(tool_name, params))
        if result.startswith("❌"):
            raise PathExecutionError(f"Échec de l'action prédite: {result}")
        return result

    async def _get_prediction(self) -> Optional[Dict[str, Any]]:
        # Cette méthode sera connectée au NanoPredictor
        return None

    def execute_semantic_parsing(self, query: str) -> str:
        tools_desc = [
            f"- {name}.{tool.name}: {tool.description}"
            for name, agent in self.registry.agents.items()
            for tool in agent.get_tools()
        ]
        tools_str = "\n".join(tools_desc)
        prompt = (
            f"Tu es un assistant qui traduit des demandes en actions JSON.\n"
            f"Outils disponibles :\n{tools_str}\n\n"
            f'Demande : "{query}"\n\n'
            f"Génère une liste JSON d'actions. Réponds uniquement avec le JSON."
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
                    raise PathExecutionError("Impossible de parser la réponse")
                actions = parse_json_safely(match.group(1), expected_type=list)

            if not actions:
                raise PathExecutionError("Aucune action générée")

            results = []
            for act in actions:
                agent_name = act.get("agent")
                tool_name = act.get("tool")
                params = act.get("parameters", {})
                agent = self.registry.get_agent(agent_name)
                result = self._run_coro_sync(agent.execute_tool(tool_name, params))
                if result.startswith("❌"):
                    raise PathExecutionError(f"Échec de l'action {tool_name}: {result}")
                results.append(result)
            return "\n".join(results)
        except Exception as exc:
            raise PathExecutionError(f"Échec parsing sémantique: {exc}") from exc

    def get_cached_response(self, query: str) -> str:
        systems = [self._get_nano_system(), self.default_system]
        for system in systems:
            cached = self.prompt_cache.get(query, system=system, model="balanced")
            if cached:
                return cached
        raise PathExecutionError("Cache miss")

    def _get_nano_system(self) -> str:
        return (
            "Tu es un assistant personnel local, amical et direct. "
            "Tu réponds en français, de façon concise (1-3 phrases max). "
            "Tu peux aider sur tous les sujets du quotidien."
        )

    def call_llm(self, query: str, model_profile: str) -> str:
        model_name = self.model_mapping.get(model_profile)
        if not model_name:
            raise PathExecutionError(f"Profil de modèle inconnu: {model_profile}")

        enriched = self._enrich_query(query)
        word_count = len(query.split())
        timeout = min(5.0 * (1 + word_count / 50), 30.0)

        if model_profile == "nano":
            system = self._get_nano_system()
        else:
            system = self.default_system

        def _generate() -> str:
            return self.manager.generate(
                prompt=enriched, system=system,
                model=model_name, temperature=0.5, max_tokens=256, timeout=timeout,
            )

        try:
            response: str = (
                self.llm_circuit_breaker.call(_generate)
                if self.llm_circuit_breaker is not None
                else _generate()
            )
        except Exception as e:
            raise PathExecutionError(f"Échec de l'appel LLM: {e}") from e

        self.prompt_cache.put(query, system, "balanced", response)
        if self.enable_memory:
            self.memory.add_to_working(query, response)
            asyncio.run_coroutine_threadsafe(
                self.memory.add_episode(query, response, metadata={"latency": time.time()}),
                self.loop
            )
        return response

    async def generate_and_execute_plan(self, query: str) -> str:
        plan_dicts = self._get_cached_plan(query)
        if plan_dicts:
            from app.agents.planner_agent import PlanStep
            steps = [PlanStep(**step) for step in plan_dicts]
        else:
            steps = await self.planner.create_plan(query)
            if not steps:
                raise PathExecutionError("Impossible de générer un plan")
            plan_dicts = [step.dict() for step in steps]
            self._cache_plan(query, plan_dicts)

        timeout = self._get_dynamic_timeout(query, plan_needed=True)
        try:
            result = await asyncio.wait_for(
                self.planner.execute_plan(steps),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout lors de l'exécution du plan")
            raise PathExecutionError("Le plan a pris trop de temps")
        return result

    async def execute_creation_agent(self, query: str) -> str:
        creator = self.registry.get_agent("CreatorAgent")
        q = query.lower()
        for prefix in ["crée un agent", "créer un agent", "génère un agent", "fabrique un agent"]:
            if prefix in q:
                description = q.split(prefix, 1)[1].strip()
                if description:
                    result = await creator.execute_tool("create_agent", {"description": description})
                    return result
        return await creator.execute_tool("create_agent", {"description": query})

    def _route_simple_action(self, query: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        q = query.lower()
        for keyword, (agent_name, tool_name) in self.SIMPLE_ACTIONS.items():
            if keyword not in q:
                continue
            if tool_name == "open_application":
                rest = q.replace(keyword, "").strip()
                match = re.search(r"^(.*?)(?:\s+(?:et|puis)\s+|$)", rest)
                if match:
                    rest = match.group(1).strip()
                if not rest:
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
                params = {"text": text}
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
        base = self.base_plan_timeout if plan_needed else 5.0
        estimated = base * (1 + len(query.split()) / 100)
        return min(estimated, self.base_plan_timeout * 2)

    def _enrich_query(self, query: str) -> str:
        if self.enable_memory:
            ctx = self.memory.get_working_context(n=3)
            if ctx:
                return f"Contexte récent:\n{ctx}\n\n{query}"
        return query

    def _get_cached_plan(self, query: str) -> Optional[List[Dict[str, Any]]]:
        try:
            return self.prompt_cache.get_plan(query, similarity_threshold=0.75)
        except Exception as exc:
            logger.error(f"Erreur récupération plan cache: {exc}")
            return None

    def _cache_plan(self, query: str, plan: List[Dict[str, Any]]) -> None:
        try:
            self.prompt_cache.put_plan(query, plan)
        except Exception as exc:
            logger.error(f"Erreur stockage plan cache: {exc}")


# -----------------------------------------------------------------------------
# Collecteur de métriques
# -----------------------------------------------------------------------------
class MetricsCollector:
    """Centralise les métriques pour le cortex."""
    def record_step(self, path_id: str, duration: float):
        record_cortex_step(path_id, duration)

    def record_error(self, path_id: str, error: str):
        logger.debug(f"Métrique erreur: {path_id} - {error}")


# -----------------------------------------------------------------------------
# Configuration du cortex
# -----------------------------------------------------------------------------
@dataclass
class CortexConfig:
    """Configuration du cortex."""
    plan_timeout: float = 30.0
    max_plan_retries: int = 1
    enable_memory: bool = True
    enable_elasticity: bool = True
    enable_circuit_breaker: bool = True
    cb_failure_threshold: int = 5
    cb_recovery_timeout: int = 60
    web_search: bool = True
    speed_model: str = "qwen2.5:3b"
    balanced_model: str = "qwen2.5:7b"
    quality_model: str = "qwen2.5:14b"
    nano_model: str = "qwen2.5:0.5b"
    retrain_classifier: bool = False
    custom_agents_dir: str = "./data/custom_agents"
    api_keys: Dict[str, str] = field(default_factory=dict)
    vision: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CortexConfig:
        return cls(
            plan_timeout=data.get("plan_timeout", 30.0),
            max_plan_retries=data.get("max_plan_retries", 1),
            enable_memory=data.get("enable_memory", True),
            enable_elasticity=data.get("enable_elasticity", True),
            enable_circuit_breaker=data.get("enable_circuit_breaker", True),
            cb_failure_threshold=data.get("cb_failure_threshold", 5),
            cb_recovery_timeout=data.get("cb_recovery_timeout", 60),
            web_search=data.get("web_search", True),
            speed_model=data.get("speed_model", "qwen2.5:3b"),
            balanced_model=data.get("balanced_model", "qwen2.5:7b"),
            quality_model=data.get("quality_model", "qwen2.5:14b"),
            nano_model=data.get("nano_model", "qwen2.5:0.5b"),
            retrain_classifier=data.get("retrain_classifier", False),
            custom_agents_dir=data.get("custom_agents_dir", "./data/custom_agents"),
            api_keys=data.get("api_keys", {}),
            vision=data.get("vision", {}),
        )


# =============================================================================
# Cortex frontal (version allégée)
# =============================================================================
class FrontalCortex:
    """
    Cortex frontal — Orchestrateur principal.
    Délègue aux sous-composants pour l'exécution.
    """

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
        self.raw_config = config
        self.cortex_config = CortexConfig.from_dict(config)

        self.executor = TaskExecutor(max_workers=3, persist_path=None)

        self.custom_agents_dir = Path(self.cortex_config.custom_agents_dir)
        self.custom_agents_dir.mkdir(parents=True, exist_ok=True)

        # Enregistrer le cortex comme source sur l'event bus
        self._cortex_token = self.event_bus.register_source(
            source="cortex",
            publish_channels=["tool.error"],
            subscribe_channels=[]
        )
        logger.debug(f"Cortex enregistré avec token {self._cortex_token[:8]}...")

        # Registre des agents (nécessite le token du cortex pour publier)
        self.agent_registry = AgentRegistry(
            manager, bus, event_bus, config, self.custom_agents_dir, self._cortex_token
        )

        self.memory_manager = MemoryManager(memory_service, config)

        self.planner = PlannerAgent(manager, bus, event_bus, config)
        self.planner.set_agents(self.agent_registry.agents)

        # Modèles
        self.model_mapping: Dict[str, str] = {
            "speed": self.cortex_config.speed_model,
            "balanced": self.cortex_config.balanced_model,
            "quality": self.cortex_config.quality_model,
            "nano": self.cortex_config.nano_model,
        }

        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Classifieur
        self.classifier = EmbeddingClassifier(retrain=self.cortex_config.retrain_classifier)

        # Prédicteur (à connecter)
        self.predictor: Optional[NanoPredictor] = None
        self._predictor_started = False

        # Circuit breaker
        self._llm_circuit_breaker: Optional[CircuitBreaker] = None
        if self.cortex_config.enable_circuit_breaker:
            self._llm_circuit_breaker = CircuitBreaker(
                name="llm",
                failure_threshold=self.cortex_config.cb_failure_threshold,
                recovery_timeout=self.cortex_config.cb_recovery_timeout,
            )

        # Moteur d'exécution (créé plus tard car besoin de loop)
        self.execution_engine: Optional[ExecutionEngine] = None

        # Gestionnaire de chemins
        self.action_selector = ActionSelector(self.classifier)
        self.path_manager = PathManager(self.classifier, self.action_selector)

        # Métriques
        self.metrics = MetricsCollector()

        # Démarrer le watcher
        self.agent_registry.start_watcher()

        logger.info(f"🧠 FrontalCortex initialisé avec {len(self.agent_registry.agents)} agents.")

    async def think(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        allow_web_search: bool = True,
    ) -> Tuple[str, float]:
        self._loop = asyncio.get_running_loop()

        # Initialisation tardive de l'execution engine
        if self.execution_engine is None:
            self.execution_engine = ExecutionEngine(
                registry=self.agent_registry,
                planner=self.planner,
                manager=self.manager,
                prompt_cache=self.prompt_cache,
                memory=self.memory,
                event_bus=self.event_bus,
                config=self.raw_config,
                loop=self._loop,
                model_mapping=self.model_mapping,
                llm_circuit_breaker=self._llm_circuit_breaker,
            )
            self.path_manager.register_all_paths(self.execution_engine)

        if not self._predictor_started:
            # Note: NanoPredictor nécessiterait d'être importé et instancié
            # self.predictor = NanoPredictor(...)
            self._predictor_started = True

        start = time.time()
        logger.info(f"🧠 think() — Requête: {query[:60]}…")

        try:
            user_query = UserQuery.from_raw(query, allow_web_search=allow_web_search, system_prompt=system_prompt)
        except ValueError as e:
            logger.error(f"Requête invalide: {e}")
            return "Désolé, votre requête est invalide.", time.time() - start

        paths = await self.path_manager.select_paths(user_query.text)
        logger.info(f"⚡ Ordre des chemins: {[p[0] for p in paths]}")

        last_error: Optional[Exception] = None
        for path_id, path_func in paths:
            try:
                if asyncio.iscoroutinefunction(path_func):
                    response = await path_func(user_query.text)
                else:
                    response = path_func(user_query.text)
                duration = time.time() - start
                self.path_manager.record_success(user_query.text, path_id, duration)
                self.metrics.record_step(path_id, duration)
                logger.info(f"✅ Chemin '{path_id}' réussi en {duration:.3f}s")
                return response, duration
            except Exception as exc:
                logger.warning(f"⚠️  Chemin '{path_id}' échoué: {exc}")
                self.path_manager.record_failure(user_query.text, path_id)
                self.metrics.record_error(path_id, str(exc))
                last_error = exc
                # Publier l'erreur avec le token du cortex
                try:
                    await self.event_bus.publish(
                        channel="tool.error",
                        data={
                            "agent": "cortex",
                            "path": path_id,
                            "error": str(exc),
                            "suggestion": "Un autre chemin va être essayé."
                        },
                        source="cortex",
                        token=self._cortex_token
                    )
                except Exception as pub_err:
                    logger.error(f"Échec publication erreur sur event bus: {pub_err}")

        logger.error(f"Tous les chemins ont échoué.")
        response = self._safe_fallback(user_query.text)
        duration = time.time() - start
        self.metrics.record_step("safe_fallback", duration)
        return response, duration

    def _safe_fallback(self, query: str) -> str:
        logger.warning("Utilisation du fallback sécurisé.")
        return "Désolé, je n'ai pas pu traiter votre demande."

    async def stop(self) -> None:
        if self.predictor:
            await self.predictor.stop()
        self.agent_registry.stop_watcher()
        self.executor.shutdown()
        logger.info("🛑 Cortex arrêté.")