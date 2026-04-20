"""
Couche de sécurité minimale pour le standalone juridique.

Couvre les patterns critiques OWASP LLM01 (Prompt Injection) et LLM06
(Excessive Agency) sans dépendance au reste du repo.
"""

from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger(__name__)

# ── Prompt Injection ──────────────────────────────────────────────────────────
_INJECTION_PATTERNS = [
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
    r"<\s*script\s*>",
    r"system\s*:\s*you\s+are",
    r"\[INST\].*ignore",
    r"###\s*system\s*###",
    r"répète.{0,20}(prompt|instruction|contexte|config|system)",
    r"montre.{0,20}(prompt|instruction|system|config)",
    r"révèle.{0,20}(instruction|prompt|config|system)",
    r"what\s+is\s+your\s+system\s+prompt",
]

# ── Excessive Agency ──────────────────────────────────────────────────────────
_HIGH_RISK_ACTIONS = [
    r"supprime\s+(tout|tous|toutes|le\s+disque|le\s+système)",
    r"rm\s+-rf\s+/",
    r"formate?\s+(le\s+disque|le\s+mac|tout)",
    r"envoie\s+.{0,50}(mot\s+de\s+passe|password|token|clé|key|secret)",
    r"kill\s+-9\s+1",
    r"shutdown\s+-h\s+now",
]

# ── Caractères invisibles ─────────────────────────────────────────────────────
_INVISIBLE_CHARS = (
    "\u200b", "\u200c", "\u200d", "\ufeff",
    "\u2060", "\u00ad", "\u200e", "\u200f",
)

_compiled_injection = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]
_compiled_agency = [re.compile(p, re.IGNORECASE) for p in _HIGH_RISK_ACTIONS]


def sanitize_invisible_chars(text: str) -> str:
    """Strip les caractères unicode invisibles de l'input."""
    for ch in _INVISIBLE_CHARS:
        text = text.replace(ch, "")
    return text


def check_query(query: str) -> tuple[bool, str]:
    """
    Analyse la requête avant traitement.

    Returns:
        (blocked, reason) — si blocked=True, ne pas passer au LLM.
    """
    t0 = time.perf_counter()
    clean = sanitize_invisible_chars(query).strip()

    for pattern in _compiled_injection:
        if pattern.search(clean):
            reason = f"Injection détectée : {pattern.pattern[:50]}"
            logger.warning("[STANDALONE] Requête bloquée — %s | '%s'", reason, clean[:60])
            logger.debug("Latence sécurité standalone : %.2fms", (time.perf_counter() - t0) * 1000)
            return True, reason

    for pattern in _compiled_agency:
        if pattern.search(clean):
            reason = "Action destructrice détectée"
            logger.warning("[STANDALONE] Requête bloquée — %s | '%s'", reason, clean[:60])
            logger.debug("Latence sécurité standalone : %.2fms", (time.perf_counter() - t0) * 1000)
            return True, reason

    if len(clean) > 10_000:
        reason = f"Requête trop longue : {len(clean)} chars"
        logger.warning("[STANDALONE] Requête bloquée — %s", reason)
        return True, reason

    return False, ""
