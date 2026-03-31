"""
Modèle de données pour le Brain Feed.
Chaque pensée de Lucie est une ThoughtEntry immuable.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class ThoughtType(Enum):
    """Types de pensées dans le flux."""
    ROUTING = "routing"          # Décision de routage (quel agent)
    AGENT_START = "agent_start"  # Un agent commence son travail
    AGENT_STEP = "agent_step"    # Étape intermédiaire d'un agent
    AGENT_DONE = "agent_done"    # Agent terminé
    THINKING = "thinking"        # Réflexion interne (LLM en cours)
    CONTEXT = "context"          # Changement de contexte utilisateur
    ERROR = "error"              # Erreur capturée et gérée
    INSIGHT = "insight"          # Découverte ou apprentissage
    SYSTEM = "system"            # Événement système (mémoire, énergie)


class ThoughtPriority(Enum):
    """Priorité d'affichage — filtre ce qui apparaît dans le feed."""
    WHISPER = 0    # Interne uniquement, pas affiché
    MURMUR = 1     # Affiché brièvement, disparaît vite
    NORMAL = 2     # Affiché normalement
    IMPORTANT = 3  # Mis en avant (highlight)
    CRITICAL = 4   # Toujours visible, ne disparaît pas


@dataclass(frozen=True)
class ThoughtEntry:
    """
    Une pensée immuable dans le flux de conscience de Lucie.
    frozen=True garantit l'immuabilité et le hashage.
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    thought_type: ThoughtType = ThoughtType.THINKING
    priority: ThoughtPriority = ThoughtPriority.NORMAL
    agent: str = ""              # Agent source (vide si système)
    text: str = ""               # Texte lisible par l'humain
    detail: str = ""             # Détail technique (tooltip)
    confidence: float = 0.0      # Confiance [0, 1] si applicable
    latency_ms: float = 0.0      # Latence en ms si applicable
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_notification_dict(self) -> Dict[str, str]:
        """
        Sérialise pour DistributedNotificationCenter.
        NSDistributedNotificationCenter ne supporte que des
        dictionnaires avec clés/valeurs String (plist-compatible).
        """
        return {
            "id": self.id,
            "timestamp": str(self.timestamp),
            "type": self.thought_type.value,
            "priority": str(self.priority.value),
            "agent": self.agent,
            "text": self.text,
            "detail": self.detail,
            "confidence": f"{self.confidence:.3f}",
            "latency_ms": f"{self.latency_ms:.1f}",
            "metadata": json.dumps(self.metadata) if self.metadata else "{}",
        }

    @classmethod
    def from_notification_dict(cls, d: Dict[str, str]) -> ThoughtEntry:
        """Désérialise depuis un dictionnaire de notification."""
        return cls(
            id=d.get("id", ""),
            timestamp=float(d.get("timestamp", 0)),
            thought_type=ThoughtType(d.get("type", "thinking")),
            priority=ThoughtPriority(int(d.get("priority", "2"))),
            agent=d.get("agent", ""),
            text=d.get("text", ""),
            detail=d.get("detail", ""),
            confidence=float(d.get("confidence", "0")),
            latency_ms=float(d.get("latency_ms", "0")),
            metadata=json.loads(d.get("metadata", "{}")),
        )
