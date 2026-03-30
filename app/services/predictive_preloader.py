"""
PredictivePreloader — préchargement prédictif des modèles Ollama.

Anticipe les besoins en modèles en fusionnant trois sources de signal :
  1. Séquence Markov (50 %) : transitions agent→agent observées en session
  2. Temporel HabitsTracker (25 %) : habitudes horaires de l'utilisateur
  3. Workflow NanoPredictor (25 %) : patterns de routage appris

Un préchargement n'est déclenché que si la confiance dépasse 60 % et
qu'un cooldown de 30 s a été respecté depuis le dernier préchargement
du même modèle.

Composants :
  - AgentTransitionModel : Chaîne de Markov ordre 1, persistée en SQLite
  - TraceRecorder        : Enregistre les transitions d'agents en session
  - PredictivePreloader  : Orchestre les 3 sources et déclenche le préchargement
"""

import asyncio
import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..utils.logger import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

TRACES_DB_PATH: Path = Path.home() / ".lucie" / "agent_traces.db"

CONFIDENCE_THRESHOLD: float = 0.60   # Seuil minimal pour déclencher un préchargement
PRELOAD_COOLDOWN_S: float = 30.0     # Délai minimum entre deux préchargements du même modèle

# Poids des trois sources de signal
WEIGHT_SEQUENCE:  float = 0.50
WEIGHT_TEMPORAL:  float = 0.25
WEIGHT_WORKFLOW:  float = 0.25

# Correspondance agent → modèle (même mapping que MemoryGuardian)
AGENT_MODEL_MAP: Dict[str, str] = {
    "planner":      "mistral:7b-instruct",
    "coder":        "mistral:7b-instruct",
    "reviewer":     "llama3.2:3b",
    "summarizer":   "llama3.2:3b",
    "classifier":   "phi3:mini",
    "embedder":     "nomic-embed-text",
    "multi_modal":  "phi3:medium",
}


# ─────────────────────────────────────────────────────────────────────────────
# AgentTransitionModel — Markov ordre 1
# ─────────────────────────────────────────────────────────────────────────────

class AgentTransitionModel:
    """
    Modèle de Markov ordre 1 pour les transitions entre agents.

    Persisté dans SQLite (~/.lucie/agent_traces.db).
    Thread-safe via threading.Lock (accès synchrone depuis asyncio via run_in_executor).
    """

    def __init__(self, db_path: Path = TRACES_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_db()
        logger.debug(f"AgentTransitionModel initialisé ({db_path})")

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS transitions (
                from_agent TEXT NOT NULL,
                to_agent   TEXT NOT NULL,
                count      INTEGER DEFAULT 1,
                PRIMARY KEY (from_agent, to_agent)
            )
        """)
        self._conn.commit()

    def record(self, from_agent: str, to_agent: str) -> None:
        """Enregistre une transition agent→agent."""
        with self._lock:
            self._conn.execute("""
                INSERT INTO transitions (from_agent, to_agent, count)
                VALUES (?, ?, 1)
                ON CONFLICT(from_agent, to_agent) DO UPDATE SET count = count + 1
            """, (from_agent, to_agent))
            self._conn.commit()

    def predict_next(self, current_agent: str) -> List[Tuple[str, float]]:
        """
        Prédit les agents probables suivants à partir de l'agent courant.

        Retourne une liste de (agent, probabilité) triée par probabilité décroissante.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT to_agent, count FROM transitions WHERE from_agent = ?",
                (current_agent,)
            ).fetchall()

        if not rows:
            return []

        total = sum(count for _, count in rows)
        predictions = [(agent, count / total) for agent, count in rows]
        predictions.sort(key=lambda x: x[1], reverse=True)
        return predictions


# ─────────────────────────────────────────────────────────────────────────────
# TraceRecorder — enregistre les traces d'exécution
# ─────────────────────────────────────────────────────────────────────────────

class TraceRecorder:
    """
    Enregistre les traces d'activation des agents en session et alimente
    le modèle de transition Markov.
    """

    def __init__(self, transition_model: AgentTransitionModel) -> None:
        self._model = transition_model
        self._session_sequence: List[str] = []
        self._lock = threading.Lock()

    def record_activation(self, agent_name: str) -> None:
        """Enregistre l'activation d'un agent et met à jour le modèle Markov."""
        with self._lock:
            if self._session_sequence:
                previous = self._session_sequence[-1]
                if previous != agent_name:
                    self._model.record(previous, agent_name)
            self._session_sequence.append(agent_name)
            # Garder uniquement les 100 dernières activations en mémoire
            if len(self._session_sequence) > 100:
                self._session_sequence = self._session_sequence[-100:]

    def current_agent(self) -> Optional[str]:
        """Retourne le dernier agent activé, ou None si aucun."""
        with self._lock:
            return self._session_sequence[-1] if self._session_sequence else None

    def reset_session(self) -> None:
        """Réinitialise la séquence de session (nouveau démarrage)."""
        with self._lock:
            self._session_sequence = []


# ─────────────────────────────────────────────────────────────────────────────
# PredictivePreloader — orchestrateur
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PreloadCandidate:
    """Candidat au préchargement avec son score de confiance fusionné."""
    model: str
    confidence: float
    sources: Dict[str, float] = field(default_factory=dict)


class PredictivePreloader:
    """
    Préchargeur prédictif des modèles Ollama.

    Fusionne trois sources de signal pour anticiper les besoins :
    - Séquence Markov (50 %) depuis AgentTransitionModel
    - Temporel HabitsTracker (25 %) — patterns horaires
    - Workflow NanoPredictor (25 %) — patterns de routage

    Un préchargement est déclenché si confiance ≥ 60 % et cooldown ≥ 30 s.
    """

    def __init__(self,
                 memory_guardian: Optional[Any] = None,
                 habits_tracker: Optional[Any] = None,
                 nano_predictor: Optional[Any] = None,
                 db_path: Path = TRACES_DB_PATH) -> None:
        self._memory_guardian = memory_guardian
        self._habits_tracker = habits_tracker
        self._nano_predictor = nano_predictor

        self._transition_model = AgentTransitionModel(db_path=db_path)
        self._trace_recorder = TraceRecorder(self._transition_model)

        # Cooldown par modèle : timestamp du dernier préchargement
        self._last_preload: Dict[str, float] = {}
        self._lock = asyncio.Lock()

        logger.info("✅ PredictivePreloader initialisé")

    # ─────────────────────────────────────────────────────────────────────────
    # Points d'entrée principaux
    # ─────────────────────────────────────────────────────────────────────────

    async def on_agent_activated(self, agent_name: str) -> None:
        """
        Appelé chaque fois qu'un agent est activé.
        Enregistre la transition et déclenche le préchargement prédictif.
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, self._trace_recorder.record_activation, agent_name
        )
        await self._trigger_preload(current_agent=agent_name)

    async def on_session_start(self) -> None:
        """
        Appelé au démarrage d'une session.
        Réinitialise la séquence et précharge les modèles probables du début de journée.
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._trace_recorder.reset_session)
        logger.info("PredictivePreloader : nouvelle session démarrée")
        await self._preload_session_start_models()

    # ─────────────────────────────────────────────────────────────────────────
    # Construction et fusion des scores
    # ─────────────────────────────────────────────────────────────────────────

    async def _trigger_preload(self, current_agent: str) -> None:
        """
        Fusionne les trois sources de signal et précharge les modèles
        dont la confiance dépasse le seuil.
        """
        candidates = await self._build_candidates(current_agent)

        for candidate in candidates:
            if candidate.confidence < CONFIDENCE_THRESHOLD:
                continue
            await self._maybe_preload(candidate.model, candidate.confidence)

    async def _build_candidates(self, current_agent: str) -> List[PreloadCandidate]:
        """Construit la liste des candidats avec leurs scores fusionnés."""
        # Score source 1 : Markov (séquence)
        sequence_scores: Dict[str, float] = {}
        loop = asyncio.get_running_loop()
        predictions = await loop.run_in_executor(
            None, self._transition_model.predict_next, current_agent
        )
        for next_agent, prob in predictions:
            model = AGENT_MODEL_MAP.get(next_agent)
            if model:
                sequence_scores[model] = max(sequence_scores.get(model, 0.0), prob)

        # Score source 2 : temporel (HabitsTracker)
        temporal_scores: Dict[str, float] = await self._get_temporal_scores()

        # Score source 3 : workflow (NanoPredictor)
        workflow_scores: Dict[str, float] = await self._get_workflow_scores()

        # Fusion pondérée
        all_models = (
            set(sequence_scores.keys())
            | set(temporal_scores.keys())
            | set(workflow_scores.keys())
        )

        candidates: List[PreloadCandidate] = []
        for model in all_models:
            s = sequence_scores.get(model, 0.0)
            t = temporal_scores.get(model, 0.0)
            w = workflow_scores.get(model, 0.0)
            fused = WEIGHT_SEQUENCE * s + WEIGHT_TEMPORAL * t + WEIGHT_WORKFLOW * w
            candidates.append(PreloadCandidate(
                model=model,
                confidence=fused,
                sources={"sequence": s, "temporal": t, "workflow": w},
            ))

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    async def _get_temporal_scores(self) -> Dict[str, float]:
        """Interroge HabitsTracker pour obtenir des scores temporels."""
        if self._habits_tracker is None:
            return {}
        try:
            loop = asyncio.get_running_loop()
            suggestions = await loop.run_in_executor(
                None, self._habits_tracker.get_suggestions
            )
            scores: Dict[str, float] = {}
            for suggestion in suggestions:
                action = getattr(suggestion, "action", "")
                confidence = getattr(suggestion, "confidence", 0.0)
                model = AGENT_MODEL_MAP.get(action)
                if model:
                    scores[model] = max(scores.get(model, 0.0), confidence)
            return scores
        except Exception as e:
            logger.debug(f"HabitsTracker get_suggestions erreur: {e}")
            return {}

    async def _get_workflow_scores(self) -> Dict[str, float]:
        """Interroge NanoPredictor pour obtenir des scores de workflow."""
        if self._nano_predictor is None:
            return {}
        try:
            # NanoPredictor expose _agent_counts : agent → nombre d'utilisations
            agent_counts: Dict[str, int] = getattr(self._nano_predictor, "_agent_counts", {})
            if not agent_counts:
                return {}
            total = sum(agent_counts.values())
            scores: Dict[str, float] = {}
            for agent, count in agent_counts.items():
                model = AGENT_MODEL_MAP.get(agent)
                if model and total > 0:
                    scores[model] = max(scores.get(model, 0.0), count / total)
            return scores
        except Exception as e:
            logger.debug(f"NanoPredictor scores erreur: {e}")
            return {}

    # ─────────────────────────────────────────────────────────────────────────
    # Déclenchement du préchargement
    # ─────────────────────────────────────────────────────────────────────────

    async def _maybe_preload(self, model: str, confidence: float) -> None:
        """Précharge un modèle si le cooldown est respecté."""
        async with self._lock:
            last = self._last_preload.get(model, 0.0)
            if time.time() - last < PRELOAD_COOLDOWN_S:
                return
            self._last_preload[model] = time.time()

        logger.info(
            f"🔮 Préchargement prédictif : {model} "
            f"(confiance={confidence:.2%})"
        )

        if self._memory_guardian is not None:
            try:
                await self._memory_guardian.preload_model(model)
            except Exception as e:
                logger.warning(f"Préchargement {model} échoué: {e}")

    async def _preload_session_start_models(self) -> None:
        """
        Précharge les modèles les plus fréquents en début de session,
        d'après les stats NanoPredictor et HabitsTracker.
        """
        temporal_scores = await self._get_temporal_scores()
        workflow_scores = await self._get_workflow_scores()

        merged: Dict[str, float] = {}
        for model, score in temporal_scores.items():
            merged[model] = merged.get(model, 0.0) + WEIGHT_TEMPORAL * score
        for model, score in workflow_scores.items():
            merged[model] = merged.get(model, 0.0) + WEIGHT_WORKFLOW * score

        # Précharger les modèles au-dessus du seuil (sans le poids Markov au démarrage)
        threshold_session = CONFIDENCE_THRESHOLD * (WEIGHT_TEMPORAL + WEIGHT_WORKFLOW)
        for model, score in sorted(merged.items(), key=lambda x: x[1], reverse=True):
            if score >= threshold_session:
                await self._maybe_preload(model, score)

    # ─────────────────────────────────────────────────────────────────────────
    # Accesseurs publics
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def trace_recorder(self) -> TraceRecorder:
        """Retourne le TraceRecorder pour un usage externe."""
        return self._trace_recorder

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du preloader."""
        return {
            "last_preloads": {
                model: round(time.time() - ts, 1)
                for model, ts in self._last_preload.items()
            },
            "current_agent": self._trace_recorder.current_agent(),
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "cooldown_s": PRELOAD_COOLDOWN_S,
        }
