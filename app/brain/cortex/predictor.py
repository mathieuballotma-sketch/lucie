"""
NanoPredictor — apprentissage automatique à partir des requêtes réelles
Loi : évolution — chaque interaction rend Lucie plus intelligente
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PREDICTOR_DB = Path("memory/journals/nano_predictor.jsonl")


@dataclass
class Prediction:
    """Une prédiction enregistrée."""
    query: str
    agent: str
    confidence: float
    confirmed: bool = False
    timestamp: float = field(default_factory=time.time)


class NanoPredictor:
    """
    Apprend automatiquement de chaque requête traitée.

    Fonctionnement :
    1. Chaque requête routée est enregistrée
    2. Si le routage est confirmé correct → renforce l'exemple
    3. Si incorrect → enregistre la correction
    4. Génère de nouveaux exemples pour le classifier
    5. Sauvegarde en JSONL pour persistance entre sessions

    Objectif : améliorer le Fast Path de 80% → 95% en 1 semaine.
    """

    def __init__(self) -> None:
        self._predictions: List[Prediction] = []
        self._corrections: Dict[str, str] = {}
        self._agent_counts: Dict[str, int] = defaultdict(int)
        self._new_examples: List[Tuple[str, str]] = []
        self._router: Optional[object] = None
        self._write_lock = threading.Lock()
        PREDICTOR_DB.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def set_router(self, router: object) -> None:
        """Connecte le NanoPredictor au PathRouter pour enrichir les exemples."""
        self._router = router

    def record(self, query: str, agent: str, confidence: float) -> None:
        """
        Enregistre une prédiction après routage.
        Appelé automatiquement par le PathRouter.
        """
        pred = Prediction(query=query, agent=agent, confidence=confidence)
        self._predictions.append(pred)
        self._agent_counts[agent] += 1

        # Auto-confirmation si confiance très haute
        if confidence >= 0.85:
            self._confirm(pred)

        self._save_entry(pred)
        logger.debug(f"📝 Enregistré : '{query[:30]}' → {agent} ({confidence:.3f})")

    def correct(self, query: str, wrong_agent: str, correct_agent: str) -> None:
        """
        Enregistre une correction manuelle.
        Appelé quand Lucie se trompe d'agent.
        """
        self._corrections[query] = correct_agent
        logger.info(f"✏️ Correction : '{query[:30]}' {wrong_agent} → {correct_agent}")

        # Ajoute immédiatement au classifier si connecté
        if self._router and hasattr(self._router, '_classifier'):
            clf = self._router._classifier
            if clf and clf.is_ready:
                clf.add_example(query, correct_agent)
                self._new_examples.append((query, correct_agent))
                logger.info(f"✅ Exemple ajouté au classifier : {correct_agent}")

        # Sauvegarde la correction (thread-safe)
        entry = {
            "type": "correction",
            "query": query,
            "wrong": wrong_agent,
            "correct": correct_agent,
            "timestamp": time.time()
        }
        with self._write_lock:
            with open(PREDICTOR_DB, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _confirm(self, pred: Prediction) -> None:
        """Confirme une prédiction et enrichit le classifier."""
        pred.confirmed = True
        if self._router and hasattr(self._router, '_classifier'):
            clf = self._router._classifier
            if clf and clf.is_ready:
                # N'ajoute que les nouvelles formulations
                if pred.query not in [q for q, _ in self._new_examples]:
                    clf.add_example(pred.query, pred.agent)
                    self._new_examples.append((pred.query, pred.agent))

    def generate_new_examples(self) -> List[Tuple[str, str]]:
        """
        Retourne les nouveaux exemples appris depuis le dernier démarrage.
        Utilisé par le self_improver du Bloc 5.
        """
        return self._new_examples.copy()

    def stats(self) -> dict:
        """Statistiques d'apprentissage."""
        total = len(self._predictions)
        confirmed = sum(1 for p in self._predictions if p.confirmed)
        return {
            "total_predictions": total,
            "confirmed": confirmed,
            "corrections": len(self._corrections),
            "new_examples": len(self._new_examples),
            "agent_distribution": dict(self._agent_counts),
            "auto_confirm_rate": f"{confirmed/total:.0%}" if total > 0 else "0%",
        }

    def _save_entry(self, pred: Prediction) -> None:
        """Sauvegarde une prédiction en JSONL (thread-safe)."""
        entry = {
            "type": "prediction",
            "query": pred.query,
            "agent": pred.agent,
            "confidence": pred.confidence,
            "confirmed": pred.confirmed,
            "timestamp": pred.timestamp,
        }
        try:
            with self._write_lock:
                with open(PREDICTOR_DB, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Erreur sauvegarde predictor : {e}")

    def _load(self) -> None:
        """Charge l'historique des prédictions au démarrage."""
        if not PREDICTOR_DB.exists():
            return
        try:
            with open(PREDICTOR_DB, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if entry.get("type") == "correction":
                        self._corrections[entry["query"]] = entry["correct"]
                    elif entry.get("type") == "prediction":
                        self._agent_counts[entry["agent"]] += 1
            logger.info(
                f"✅ NanoPredictor chargé — "
                f"{len(self._corrections)} corrections historiques"
            )
        except Exception as e:
            logger.error(f"Erreur chargement predictor : {e}")

    def update_partial_input(self, text: str) -> None:
        """Stub — partial input tracking pas encore implémenté."""
        pass
