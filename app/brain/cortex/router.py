"""
PathRouter — 9 chemins de routage avec Fast Path intégré
Loi : moindre action — 80% des requêtes sans LLM en < 100ms
"""

from __future__ import annotations

import logging
import re
import time
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from app.brain.cortex.predictor import NanoPredictor

logger = logging.getLogger(__name__)


class RoutePath(Enum):
    """3 chemins de routage actifs."""
    FAST_PATH        = "fast_path"        # sans LLM
    VISUAL_RESEARCH  = "visual_research"  # Safari recherche visible
    FALLBACK         = "fallback"


@dataclass
class RouteResult:
    """Résultat d'un routage."""
    path: RoutePath
    agent: str
    confidence: float
    latency_ms: float
    via_fast_path: bool = False


def _levenshtein(a: str, b: str) -> int:
    """Distance de Levenshtein entre deux chaînes (< 1µs sur mots courts)."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]


class PathRouter:
    """
    Router 9 chemins avec Fast Path.

    Fast Path : classification par embeddings légers (< 10ms)
    → si confiance >= seuil → agent direct, zéro LLM
    → sinon → LLM classique

    Objectif : 80% des requêtes via Fast Path.
    """

    # Mots-clés ultra-rapides (< 1ms) — avant même les embeddings
    _KEYWORD_MAP = {
        "visual_research": [
            "recherche et consulte",
            "cherche et fais une synthèse",
            "consulte les sites",
            "consulte 3 sites",
            "consulte 3 site",
            "recherche sur safari",
            "fais une synthèse",
            "fis une synthese",
            "fis une syntese",
            "fait une synthese",
            "fait une syntese",
            "consulte des sites",
            "recherche et synthèse",
            "recherche et syntese",
        ],
        "computer_control": [
            "ouvre", "ouvrir", "ferme", "lance", "lancer", "quitte", "volume", "son",
            "screenshot", "capture", "luminosité", "wifi", "bluetooth",
            "redémarre", "éteins", "verrouille", "dock", "spotlight",
            "va sur", "aller sur", "affiche", "montre", "démarre", "démarrer",
        ],
        "reminder": [
            "rappelle", "rappel", "alarme", "alerte", "réveille",
            "notification", "deadline", "échéance"
        ],
        "file_agent": [
            "crée un fichier", "crée un dossier", "supprime le fichier",
            "déplace le fichier", "renomme", "compresse", "décompresse",
            "sauvegarde le fichier"
        ],
        "workspace_agent": [
            "fenêtres", "layout", "côte à côte", "split", "plein écran",
            "organise les fenêtres", "arrange"
        ],
    }

    def __init__(self) -> None:
        self._classifier: Any = None
        self._trained: bool = False
        self._fast_path_enabled: bool = False
        self._stats = {
            "total": 0,
            "fast_path": 0,
            "llm_path": 0,
        }

    def initialize(self) -> bool:
        """
        Initialise le classifier et charge les 300 exemples.
        Retourne True si le Fast Path est opérationnel.
        """
        try:
            from app.brain.cortex.classifier import EmbeddingClassifier
            from app.brain.cortex.training_data import get_training_examples

            self._classifier = EmbeddingClassifier()
            self._classifier.confidence_threshold = 0.62

            if not self._classifier.initialize():
                logger.warning("⚠️ Classifier non initialisé — Fast Path désactivé")
                return False

            # Chargement des 300 exemples en batch
            t0 = time.perf_counter()
            examples = get_training_examples()

            texts = [text for text, _ in examples]
            labels = [label for _, label in examples]

            # Batch embed — bien plus rapide que un par un
            vecs = self._classifier.embed_batch(texts)
            if vecs is not None:
                import numpy as np
                for i, (vec, label) in enumerate(zip(vecs, labels)):
                    self._classifier._examples.append(
                        (vec.astype(np.float32), label)
                    )
            else:
                # Fallback un par un
                for text, label in examples:
                    self._classifier.add_example(text, label)

            elapsed = (time.perf_counter() - t0) * 1000
            self._trained = True
            self._fast_path_enabled = True

            logger.info(
                f"✅ Fast Path opérationnel — "
                f"{len(examples)} exemples chargés en {elapsed:.0f}ms"
            )
            return True

        except Exception as e:
            logger.error(f"Erreur initialisation router : {e}")
            return False

    def route(self, query: str) -> RouteResult:
        """
        Route une requête vers l'agent approprié.

        1. Keyword match (< 1ms)
        2. Embedding classify (< 10ms)
        3. Fallback LLM
        """
        t0 = time.perf_counter()
        self._stats["total"] += 1
        query_lower = query.lower().strip()

        # ── Étape 1 : Keyword match ultra-rapide ──────────────────
        keyword_agent = self._keyword_match(query_lower)
        if keyword_agent:
            latency = (time.perf_counter() - t0) * 1000
            self._stats["fast_path"] += 1
            # Chemin spécial pour la recherche visuelle Safari
            route_path = (RoutePath.VISUAL_RESEARCH
                          if keyword_agent == "visual_research"
                          else RoutePath.FAST_PATH)
            logger.debug(f"⚡ Keyword match → {keyword_agent} ({latency:.1f}ms)")
            return RouteResult(
                path=route_path,
                agent=keyword_agent,
                confidence=0.95,
                latency_ms=latency,
                via_fast_path=True,
            )

        # ── Étape 1b : Fuzzy keyword match (typos distance ≤ 1) ──
        fuzzy_agent = self._fuzzy_keyword_match(query_lower)
        if fuzzy_agent:
            latency = (time.perf_counter() - t0) * 1000
            self._stats["fast_path"] += 1
            route_path = (RoutePath.VISUAL_RESEARCH
                          if fuzzy_agent == "visual_research"
                          else RoutePath.FAST_PATH)
            logger.debug(f"🔤 Fuzzy match → {fuzzy_agent} ({latency:.1f}ms)")
            return RouteResult(
                path=route_path,
                agent=fuzzy_agent,
                confidence=0.80,
                latency_ms=latency,
                via_fast_path=True,
            )

        # ── Étape 2 : Embedding classify ──────────────────────────
        if self._fast_path_enabled and self._classifier:
            label, confidence = self._classifier.classify(query)
            if label is not None:
                latency = (time.perf_counter() - t0) * 1000
                self._stats["fast_path"] += 1
                logger.debug(
                    f"⚡ Fast Path → {label} "
                    f"({confidence:.3f}) {latency:.1f}ms"
                )
                return RouteResult(
                    path=RoutePath.FAST_PATH,
                    agent=label,
                    confidence=confidence,
                    latency_ms=latency,
                    via_fast_path=True,
                )

        # ── Étape 3 : Thalamus fallback (détection de fréquence) ──
        try:
            from app.brain.synapses.thalamus import detect_frequency
            frequency = detect_frequency(query)
            # Mapper les fréquences Thalamus vers des chemins concrets
            _FREQUENCY_TO_PATH = {
                "mac_query": RoutePath.FAST_PATH,
                "file_query": RoutePath.FAST_PATH,
                "research_query": RoutePath.VISUAL_RESEARCH,
                "finance_query": RoutePath.VISUAL_RESEARCH,
            }
            thalamus_path = _FREQUENCY_TO_PATH.get(frequency)
            if thalamus_path:
                latency = (time.perf_counter() - t0) * 1000
                self._stats["fast_path"] += 1
                logger.debug(f"🔮 Thalamus → {frequency} → {thalamus_path.value} ({latency:.1f}ms)")
                return RouteResult(
                    path=thalamus_path,
                    agent=frequency,
                    confidence=0.5,
                    latency_ms=latency,
                    via_fast_path=True,
                )
        except Exception as _th_err:
            logger.debug(f"Thalamus fallback échoué : {_th_err}")

        # ── Étape 4 : Fallback LLM ────────────────────────────────
        latency = (time.perf_counter() - t0) * 1000
        self._stats["llm_path"] += 1
        logger.debug(f"🤖 LLM Path → fallback ({latency:.1f}ms)")
        return RouteResult(
            path=RoutePath.FALLBACK,
            agent="planner",
            confidence=0.0,
            latency_ms=latency,
            via_fast_path=False,
        )

    def _keyword_match(self, query: str) -> Optional[str]:
        """Match par mots-clés avec limites de mots — < 1ms."""
        for agent, keywords in self._KEYWORD_MAP.items():
            for kw in keywords:
                # Multi-mots → recherche directe (ex: "crée un fichier")
                if " " in kw:
                    if kw in query:
                        return agent
                else:
                    # Mot simple → frontière de mot pour éviter faux positifs
                    if re.search(r'\b' + re.escape(kw) + r'\b', query, re.IGNORECASE):
                        return agent
        # Détection visual_research par co-occurrence
        q = query.lower()
        has_search = any(w in q for w in [
            "recherche", "cherche", "trouve", "googl"
        ])
        has_visit = any(w in q for w in [
            "consulte", "visite", "regarde", "site", "sites"
        ])
        has_synthesis = any(w in q for w in [
            "synth", "resum", "résume", "résumé", "bilan", "rapport"
        ])
        if has_search and (has_visit or has_synthesis):
            return "visual_research"

        return None

    def _fuzzy_keyword_match(self, query: str) -> Optional[str]:
        """Fuzzy match (Levenshtein ≤ 1) sur les mots-clés mono-mots de longueur ≥ 4.

        Détecte les typos courants : 'ouvr' → 'ouvre', 'lanc' → 'lance', etc.
        Ne tente pas le fuzzy sur les mots-clés multi-mots (trop de faux positifs).
        """
        words = query.lower().split()
        for agent, keywords in self._KEYWORD_MAP.items():
            for kw in keywords:
                if " " in kw or len(kw) < 4:
                    continue  # Ignorer multi-mots et mots très courts
                for word in words:
                    if abs(len(word) - len(kw)) <= 1:
                        if _levenshtein(word, kw) <= 1:
                            return agent
        return None

    @property
    def fast_path_ratio(self) -> float:
        """Pourcentage de requêtes traitées via Fast Path."""
        if self._stats["total"] == 0:
            return 0.0
        return self._stats["fast_path"] / self._stats["total"]

    @property
    def stats(self) -> dict[str, object]:
        return {**self._stats, "fast_path_ratio": f"{self.fast_path_ratio:.0%}"}

    @property
    def is_ready(self) -> bool:
        return self._fast_path_enabled


# ── Intégration NanoPredictor ────────────────────────────────────────

_predictor = None


def get_predictor() -> NanoPredictor:
    """Retourne l'instance globale du NanoPredictor."""
    global _predictor
    if _predictor is None:
        from app.brain.cortex.predictor import NanoPredictor
        _predictor = NanoPredictor()
    return _predictor
