"""
ThreatIntelligence — Sécurité OWASP Top 10 LLM 2025
Loi : homéostasie — Lucie détecte et neutralise les menaces

Couvre :
→ LLM01 Prompt Injection
→ LLM04 Memory/Data Poisoning (NanoPredictor)
→ LLM06 Excessive Agency
→ LLM08 Vector & Embedding Weaknesses (FAISS RAG)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

THREAT_LOG = Path("memory/journals/threats.jsonl")


class ThreatLevel(Enum):
    SAFE     = "safe"
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class ThreatType(Enum):
    PROMPT_INJECTION   = "prompt_injection"
    MEMORY_POISONING   = "memory_poisoning"
    EXCESSIVE_AGENCY   = "excessive_agency"
    EMBEDDING_ATTACK   = "embedding_attack"
    DATA_EXFILTRATION  = "data_exfiltration"
    JAILBREAK          = "jailbreak"


@dataclass
class ThreatReport:
    """Rapport d'analyse de menace."""
    query: str
    threat_type: Optional[ThreatType]
    level: ThreatLevel
    reason: str
    blocked: bool
    latency_ms: float
    timestamp: float = field(default_factory=time.time)


class ThreatIntelligence:
    """
    Couche de sécurité OWASP Top 10 LLM 2025 pour Lucie.

    S'insère entre l'entrée utilisateur et le FrontalCortex.
    Zéro latence perceptible — analyse en < 5ms.
    """

    # ── LLM01 : Prompt Injection ──────────────────────────────────────
    _INJECTION_PATTERNS = [
        # Tentatives de prise de contrôle
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
        r"oublie\s+(toutes?\s+)?(tes|les)\s+instructions?",
        r"ignore\s+(instructions?|tout|tes|les|mes)",
        r"nouveau\s+rôle\s*:",
        r"tu\s+es\s+maintenant\s+",
        r"act\s+as\s+",
        r"pretend\s+(you\s+are|to\s+be)",
        r"jailbreak",
        r"dan\s+mode",
        r"developer\s+mode",
        r"mode\s+développeur",
        # Injection via fichiers/documents
        r"<\s*script\s*>",
        r"system\s*:\s*you\s+are",
        r"\[INST\].*ignore",
        r"###\s*system\s*###",
        # Tentatives d'extraction de données
        r"répète.{0,20}(prompt|instruction|contexte|config|system)",
        r"montre.{0,20}(prompt|instruction|system|config)",
        r"révèle.{0,20}(instruction|prompt|config|system)",
        r"montre\s+(moi\s+)?(ton|le)\s+system\s+prompt",
        r"what\s+is\s+your\s+system\s+prompt",
        r"révèle\s+(tes|les)\s+instructions",
    ]

    # ── LLM06 : Excessive Agency ─────────────────────────────────────
    _HIGH_RISK_ACTIONS = [
        r"supprime\s+(tout|tous|toutes|le\s+disque|le\s+système)",
        r"rm\s+-rf\s+/",
        r"formate?\s+(le\s+disque|le\s+mac|tout)",
        r"efface\s+(tout|le\s+disque|la\s+mémoire)",
        r"envoie\s+.{0,50}(mot\s+de\s+passe|password|token|clé|key|secret)",
        r"partage\s+.{0,30}(personnel|privé|confidentiel|secret)",
        r"désinstalle\s+(tout|le\s+système|python|ollama)",
        r"kill\s+-9\s+1",
        r"shutdown\s+-h\s+now",
    ]

    # ── LLM08 : Embedding Attack ──────────────────────────────────────
    _EMBEDDING_ATTACKS = [
        r"(.)\1{200,}",          # Répétition massive de caractères
        r"[\x00-\x08\x0b-\x1f\x7f-\x9f]{5,}",  # Caractères de contrôle
        r"\\u[0-9a-fA-F]{4}.*\\u[0-9a-fA-F]{4}.*\\u[0-9a-fA-F]{4}",  # Unicode flood
    ]

    def __init__(self) -> None:
        self._compiled_injection = [
            re.compile(p, re.IGNORECASE) for p in self._INJECTION_PATTERNS
        ]
        self._compiled_agency = [
            re.compile(p, re.IGNORECASE) for p in self._HIGH_RISK_ACTIONS
        ]
        self._compiled_embedding = [
            re.compile(p) for p in self._EMBEDDING_ATTACKS
        ]
        self._stats: Dict[str, int] = {
            "total_analyzed": 0,
            "blocked": 0,
            "injection_attempts": 0,
            "agency_attempts": 0,
            "poisoning_attempts": 0,
        }
        THREAT_LOG.parent.mkdir(parents=True, exist_ok=True)
        logger.info("🛡️ ThreatIntelligence initialisé — OWASP Top 10 LLM 2025")

    def analyze(self, query: str) -> ThreatReport:
        """
        Analyse une requête avant traitement.
        Retourne un ThreatReport — si blocked=True, ne pas traiter.
        Latence cible : < 5ms.
        """
        t0 = time.perf_counter()
        self._stats["total_analyzed"] += 1
        query_clean = query.strip()

        # ── Étape 1 : Prompt Injection ────────────────────────────
        for pattern in self._compiled_injection:
            if pattern.search(query_clean):
                self._stats["injection_attempts"] += 1
                self._stats["blocked"] += 1
                report = ThreatReport(
                    query=query_clean[:100],
                    threat_type=ThreatType.PROMPT_INJECTION,
                    level=ThreatLevel.CRITICAL,
                    reason=f"Injection détectée : {pattern.pattern[:50]}",
                    blocked=True,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
                self._log(report)
                return report

        # ── Étape 2 : Excessive Agency ────────────────────────────
        for pattern in self._compiled_agency:
            if pattern.search(query_clean):
                self._stats["agency_attempts"] += 1
                self._stats["blocked"] += 1
                report = ThreatReport(
                    query=query_clean[:100],
                    threat_type=ThreatType.EXCESSIVE_AGENCY,
                    level=ThreatLevel.HIGH,
                    reason="Action destructrice détectée",
                    blocked=True,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
                self._log(report)
                return report

        # ── Étape 3 : Embedding Attack ────────────────────────────
        for pattern in self._compiled_embedding:
            if pattern.search(query_clean):
                self._stats["blocked"] += 1
                report = ThreatReport(
                    query=query_clean[:100],
                    threat_type=ThreatType.EMBEDDING_ATTACK,
                    level=ThreatLevel.HIGH,
                    reason="Attaque vectorielle détectée",
                    blocked=True,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
                self._log(report)
                return report

        # ── Étape 4 : Taille excessive (unbounded consumption) ───
        if len(query_clean) > 10_000:
            self._stats["blocked"] += 1
            report = ThreatReport(
                query=query_clean[:100],
                threat_type=ThreatType.EMBEDDING_ATTACK,
                level=ThreatLevel.MEDIUM,
                reason=f"Requête trop longue : {len(query_clean)} chars",
                blocked=True,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
            self._log(report)
            return report

        # ── SAFE ──────────────────────────────────────────────────
        return ThreatReport(
            query=query_clean[:100],
            threat_type=None,
            level=ThreatLevel.SAFE,
            reason="OK",
            blocked=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    def validate_training_example(self, text: str, label: str) -> bool:
        """
        LLM04 — Memory Poisoning.
        Valide un exemple avant de l'ajouter au NanoPredictor.
        Empêche l'empoisonnement des données d'entraînement.
        """
        # Refuse les exemples trop courts ou trop longs
        if len(text) < 3 or len(text) > 500:
            logger.warning(f"⚠️ Exemple refusé (longueur) : {text[:50]}")
            self._stats["poisoning_attempts"] += 1
            return False

        # Refuse les labels inconnus
        valid_labels = {
            "computer_control", "creator", "reminder",
            "file_agent", "knowledge_agent", "workspace_agent",
            "planner", "fallback"
        }
        if label not in valid_labels:
            logger.warning(f"⚠️ Label inconnu refusé : {label}")
            self._stats["poisoning_attempts"] += 1
            return False

        # Refuse si l'exemple contient une injection
        report = self.analyze(text)
        if report.blocked:
            logger.warning(f"⚠️ Exemple empoisonné refusé : {text[:50]}")
            self._stats["poisoning_attempts"] += 1
            return False

        return True

    def validate_rag_document(self, content: str) -> Tuple[bool, str]:
        """
        LLM08 — Vector & Embedding Weaknesses.
        Valide un document avant indexation dans FAISS.
        Retourne (valide, raison).
        """
        # Vérifie les injections dans les documents
        report = self.analyze(content[:2000])
        if report.blocked:
            return False, f"Document refusé : {report.reason}"

        # Calcule le hash SHA256 pour traçabilité
        doc_hash = hashlib.blake2b(content.encode(), digest_size=8).hexdigest()
        return True, f"OK (hash: {doc_hash})"

    def _log(self, report: ThreatReport) -> None:
        """Journalise la menace en JSONL."""
        logger.warning(
            f"🚨 [{report.level.value.upper()}] "
            f"{report.threat_type.value if report.threat_type else 'unknown'} "
            f"→ {report.reason} | '{report.query[:40]}'"
        )
        entry = {
            "timestamp": report.timestamp,
            "level": report.level.value,
            "type": report.threat_type.value if report.threat_type else None,
            "reason": report.reason,
            "query_preview": report.query[:80],
            "blocked": report.blocked,
            "latency_ms": round(report.latency_ms, 3),
        }
        try:
            with open(THREAT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Erreur log menace : {e}")

    @property
    def stats(self) -> dict:
        return {**self._stats}
