"""
Router intelligent de modèles LLM pour Agent Lucide.
Détecte automatiquement le type de tâche et sélectionne le modèle optimal.
Chaque modèle a ses paramètres (num_ctx, temperature, num_predict) adaptés.
"""

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..utils.logger import logger


@dataclass
class ModelProfile:
    """Profil complet d'un modèle avec ses paramètres optimisés."""

    name: str
    category: str
    num_ctx: int = 4096
    temperature: float = 0.7
    num_predict: int = 512
    priority: int = 0

    def to_options(self, override_temp: Optional[float] = None,
                   override_max_tokens: Optional[int] = None) -> Dict[str, Any]:
        """Retourne les options Ollama optimisées pour ce modèle."""
        return {
            "num_ctx": self.num_ctx,
            "temperature": override_temp if override_temp is not None else self.temperature,
            "num_predict": (override_max_tokens if override_max_tokens is not None
                           else self.num_predict),
        }


@dataclass
class RouteDecision:
    """Résultat d'une décision de routage."""

    model: ModelProfile
    reason: str
    confidence: float
    latency_ms: float = 0.0


# Patterns de détection par catégorie (compilés une seule fois)
_PATTERNS: Dict[str, List[re.Pattern[str]]] = {
    "code": [
        re.compile(
            r"\b(code|coder|script|fonction|function|programme|class|def |import |"
            r"variable|boucle|loop|algorithm|refactor|syntaxe|compile|debug|bug|"
            r"erreur de code|exception|traceback|pip install|npm|git|python|java|"
            r"javascript|typescript|rust|golang|html|css|sql|regex|api)\b",
            re.IGNORECASE,
        ),
    ],
    "writing": [
        re.compile(
            r"\b(rédige|écri[st]|email|mail|lettre|texte|article|blog|"
            r"reformule|résume|synthèse|rapport|document|brouillon|"
            r"corrige|orthographe|grammaire|style|ton|formel|informel|"
            r"poème|histoire|conte|narration|créatif|rédaction)\b",
            re.IGNORECASE,
        ),
    ],
    "reasoning": [
        re.compile(
            r"\b(analyse|raisonne|explique|pourquoi|comment ça marche|"
            r"compare|avantages|inconvénients|stratégie|planifie|évalue|"
            r"logique|déduction|hypothèse|argument|conclusion|"
            r"calcul|mathématique|probabilité|statistique|"
            r"réfléchis|pense|considère|examine)\b",
            re.IGNORECASE,
        ),
    ],
    # Recherche approfondie et raisonnement long — tier "deep"
    "deep": [
        re.compile(
            r"\b(recherche|research|approfondi|deep.dive|étude.complète|"
            r"investigation|rapport.détaillé|analyse.complète|"
            r"synthèse.exhaustive|revue.littérature|état.de.l.art)\b",
            re.IGNORECASE,
        ),
    ],
    "vision": [
        re.compile(
            r"\b(image|screenshot|capture|photo|écran|visuel|"
            r"regarde|vois|montre|affiche|interface|ui|ux|"
            r"describe.*image|what.*see|que vois)\b",
            re.IGNORECASE,
        ),
    ],
    "quick": [
        re.compile(
            r"^(bonjour|salut|hello|hi|hey|merci|ok|oui|non|"
            r"ça va|comment vas|quelle heure|quel jour|"
            r"c'est quoi|dis.moi|rappelle|"
            r"test|ping)\b",
            re.IGNORECASE,
        ),
    ],
    "mathieu": [
        re.compile(
            r"\b(mathieu|mon profil|qui suis.je|mes préférences|"
            r"ma config|mon style|personnalis)\b",
            re.IGNORECASE,
        ),
    ],
}


class ModelRouter:
    """
    Router intelligent de modèles LLM.
    Détecte le type de tâche et sélectionne le modèle optimal parmi ceux disponibles.
    """

    # Catalogue complet des modèles et leurs profils optimisés
    MODEL_CATALOG: Dict[str, ModelProfile] = {
        # Code
        "codestral:latest": ModelProfile(
            name="codestral:latest", category="code",
            num_ctx=4096, temperature=0.2, num_predict=1024, priority=10,
        ),
        "deepseek-coder:6.7b": ModelProfile(
            name="deepseek-coder:6.7b", category="code",
            num_ctx=4096, temperature=0.2, num_predict=1024, priority=8,
        ),
        # Raisonnement
        "deepseek-r1:7b": ModelProfile(
            name="deepseek-r1:7b", category="reasoning",
            num_ctx=4096, temperature=0.3, num_predict=1024, priority=10,
        ),
        # Recherche approfondie (tier "deep")
        "deepseek-r1:14b": ModelProfile(
            name="deepseek-r1:14b", category="deep",
            num_ctx=8192, temperature=0.3, num_predict=4096, priority=10,
        ),
        # Vision
        "llava:latest": ModelProfile(
            name="llava:latest", category="vision",
            num_ctx=2048, temperature=0.5, num_predict=512, priority=10,
        ),
        "moondream:latest": ModelProfile(
            name="moondream:latest", category="vision",
            num_ctx=2048, temperature=0.5, num_predict=256, priority=5,
        ),
        # Rapide
        "qwen2.5:3b": ModelProfile(
            name="qwen2.5:3b", category="quick",
            num_ctx=2048, temperature=0.5, num_predict=256, priority=10,
        ),
        "qwen2.5:0.5b": ModelProfile(
            name="qwen2.5:0.5b", category="quick",
            num_ctx=2048, temperature=0.5, num_predict=128, priority=8,
        ),
        # Complexe / qualité
        "qwen3:14b": ModelProfile(
            name="qwen3:14b", category="quality",
            num_ctx=8192, temperature=0.6, num_predict=1024, priority=10,
        ),
        "qwen2.5:14b": ModelProfile(
            name="qwen2.5:14b", category="quality",
            num_ctx=8192, temperature=0.6, num_predict=1024, priority=8,
        ),
        "gpt-oss:20b": ModelProfile(
            name="gpt-oss:20b", category="quality",
            num_ctx=4096, temperature=0.6, num_predict=1024, priority=6,
        ),
        # Généraliste / fallback
        "qwen2.5:7b": ModelProfile(
            name="qwen2.5:7b", category="balanced",
            num_ctx=4096, temperature=0.7, num_predict=512, priority=9,
        ),
        "mistral:latest": ModelProfile(
            name="mistral:latest", category="balanced",
            num_ctx=4096, temperature=0.7, num_predict=512, priority=7,
        ),
        "llama3:latest": ModelProfile(
            name="llama3:latest", category="balanced",
            num_ctx=4096, temperature=0.7, num_predict=512, priority=5,
        ),
        # Personnalisé
        "mathieu-ia:latest": ModelProfile(
            name="mathieu-ia:latest", category="mathieu",
            num_ctx=4096, temperature=0.7, num_predict=512, priority=10,
        ),
        # Embeddings (pas pour le chat, mais référencé)
        "mxbai-embed-large:latest": ModelProfile(
            name="mxbai-embed-large:latest", category="embedding",
            num_ctx=512, temperature=0.0, num_predict=0, priority=10,
        ),
        "nomic-embed-text:latest": ModelProfile(
            name="nomic-embed-text:latest", category="embedding",
            num_ctx=512, temperature=0.0, num_predict=0, priority=5,
        ),
    }

    # Mapping catégorie → profils de modèle mapping dans le cortex
    CATEGORY_TO_PROFILE: Dict[str, str] = {
        "code": "balanced",
        "writing": "balanced",
        "reasoning": "quality",
        "vision": "balanced",
        "quick": "speed",
        "mathieu": "balanced",
        "quality": "quality",
        "deep": "deep",
        "balanced": "balanced",
        "speed": "speed",
        "nano": "nano",
    }

    def __init__(self, available_models: Optional[List[str]] = None) -> None:
        """
        Initialise le router avec la liste des modèles disponibles.

        Args:
            available_models: Liste des noms de modèles installés sur Ollama.
                              Si None, tous les modèles du catalogue sont considérés disponibles.
        """
        self._available: Dict[str, ModelProfile] = {}
        self._stats: Dict[str, List[float]] = {}  # model_name -> list of latencies

        if available_models is not None:
            self.update_available_models(available_models)
        else:
            self._available = dict(self.MODEL_CATALOG)

        logger.info(
            f"🧭 ModelRouter initialisé avec {len(self._available)} modèles disponibles"
        )

    def update_available_models(self, model_names: List[str]) -> None:
        """Met à jour la liste des modèles disponibles."""
        self._available.clear()
        for name in model_names:
            if name in self.MODEL_CATALOG:
                self._available[name] = self.MODEL_CATALOG[name]
            else:
                # Modèle inconnu du catalogue — profil générique
                self._available[name] = ModelProfile(
                    name=name, category="balanced",
                    num_ctx=4096, temperature=0.7, num_predict=512, priority=3,
                )
        logger.debug(
            f"ModelRouter: {len(self._available)} modèles actifs: "
            f"{list(self._available.keys())}"
        )

    def route(self, query: str, force_category: Optional[str] = None) -> RouteDecision:
        """
        Analyse la requête et retourne le modèle optimal.

        Args:
            query: La requête utilisateur.
            force_category: Force une catégorie ("code", "writing", "reasoning", etc.).

        Returns:
            RouteDecision avec le modèle choisi, la raison et la confiance.
        """
        start = time.monotonic()

        if force_category:
            category = force_category
            confidence = 1.0
        else:
            category, confidence = self._classify(query)

        model = self._select_best_model(category)
        elapsed_ms = (time.monotonic() - start) * 1000

        decision = RouteDecision(
            model=model,
            reason=f"catégorie={category}",
            confidence=confidence,
            latency_ms=elapsed_ms,
        )

        logger.info(
            f"🧭 Route: '{query[:40]}…' → {model.name} "
            f"({category}, confiance={confidence:.0%}, {elapsed_ms:.1f}ms)"
        )
        return decision

    def record_latency(self, model_name: str, latency: float) -> None:
        """Enregistre la latence d'un appel pour les statistiques."""
        if model_name not in self._stats:
            self._stats[model_name] = []
        stats = self._stats[model_name]
        stats.append(latency)
        # Garder les 50 dernières mesures
        if len(stats) > 50:
            self._stats[model_name] = stats[-50:]

    def get_stats(self) -> Dict[str, Dict[str, float]]:
        """Retourne les statistiques de latence par modèle."""
        result: Dict[str, Dict[str, float]] = {}
        for name, latencies in self._stats.items():
            if latencies:
                result[name] = {
                    "avg": sum(latencies) / len(latencies),
                    "min": min(latencies),
                    "max": max(latencies),
                    "count": len(latencies),
                }
        return result

    def get_model_profile(self, model_name: str) -> Optional[ModelProfile]:
        """Retourne le profil d'un modèle spécifique."""
        return self._available.get(model_name)

    def _classify(self, query: str) -> Tuple[str, float]:
        """
        Classifie la requête en catégorie avec un score de confiance.
        Retourne (catégorie, confiance).
        """
        scores: Dict[str, int] = {}

        for category, patterns in _PATTERNS.items():
            for pattern in patterns:
                matches = pattern.findall(query)
                if matches:
                    scores[category] = scores.get(category, 0) + len(matches)

        if not scores:
            # Heuristiques de longueur
            word_count = len(query.split())
            if word_count <= 5:
                return "quick", 0.6
            elif word_count >= 30:
                return "reasoning", 0.4
            return "balanced", 0.3

        # Catégorie avec le plus de matches
        best_category = max(scores, key=lambda k: scores[k])
        total_matches = sum(scores.values())
        confidence = min(scores[best_category] / max(total_matches, 1), 1.0)

        # Boost de confiance si une seule catégorie matche
        if len(scores) == 1:
            confidence = min(confidence + 0.3, 1.0)

        return best_category, confidence

    def _select_best_model(self, category: str) -> ModelProfile:
        """Sélectionne le meilleur modèle disponible pour une catégorie."""
        # Chercher les modèles de cette catégorie
        candidates = [
            m for m in self._available.values()
            if m.category == category
        ]

        if candidates:
            # Trier par priorité décroissante
            candidates.sort(key=lambda m: m.priority, reverse=True)
            return candidates[0]

        # Fallback : catégorie "balanced"
        balanced = [
            m for m in self._available.values()
            if m.category == "balanced"
        ]
        if balanced:
            balanced.sort(key=lambda m: m.priority, reverse=True)
            return balanced[0]

        # Dernier recours : n'importe quel modèle non-embedding
        any_model = [
            m for m in self._available.values()
            if m.category != "embedding"
        ]
        if any_model:
            any_model.sort(key=lambda m: m.priority, reverse=True)
            return any_model[0]

        # Vraiment rien — modèle par défaut
        return ModelProfile(
            name="qwen2.5:7b", category="balanced",
            num_ctx=4096, temperature=0.7, num_predict=512,
        )
