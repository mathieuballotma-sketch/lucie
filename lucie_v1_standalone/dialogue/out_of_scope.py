"""OUT_OF_SCOPE — détection des questions hors périmètre Droit Social.

Chargé en amont du routage intent : si la query évoque un domaine
hors-scope (fiscal, immobilier, pénal, consommation, famille) ET
qu'aucun motif Code du travail ne la « ramène dans le périmètre »,
on court-circuite le pipeline avec une phrase de redirection.

Configuration : `out_of_scope_config.yaml` (éditable à chaud par
l'utilisateur, puis `clear_out_of_scope_cache()` pour invalider).

Aucun LLM impliqué — substring match normalisé + regex override.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from lucie_v1_standalone.dialogue.intent_classifier import _normalize_text

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent / "out_of_scope_config.yaml"


@dataclass(frozen=True)
class OutOfScopeMatch:
    """Résultat d'une détection hors-scope."""

    domain: str
    redirection: str


@lru_cache(maxsize=1)
def _load_config() -> dict:
    """Charge le YAML une fois. Retourne `{}` si le fichier est absent ou
    illisible — dans ce cas la détection est désactivée (fail-open)."""
    if not _CONFIG_PATH.exists():
        logger.warning("out_of_scope_config.yaml absent — détection désactivée")
        return {}
    try:
        # Réutilise le loader central pour cohérence (PyYAML + fallback).
        from lucie_v1_standalone.knowledge_legifrance.indexer import _load_yaml

        return _load_yaml(_CONFIG_PATH) or {}
    except (OSError, ValueError) as exc:
        logger.warning("out_of_scope_config.yaml illisible (%s)", exc)
        return {}


@lru_cache(maxsize=1)
def _compiled_overrides() -> tuple[re.Pattern, ...]:
    cfg = _load_config()
    patterns = cfg.get("priority_override", {}).get("patterns", []) or []
    compiled: list[re.Pattern] = []
    for pat in patterns:
        try:
            compiled.append(re.compile(pat, re.IGNORECASE | re.UNICODE))
        except re.error as exc:
            logger.warning("Pattern override invalide %r : %s", pat, exc)
    return tuple(compiled)


@lru_cache(maxsize=1)
def _normalized_domains() -> tuple[tuple[str, tuple[str, ...], str], ...]:
    """Retourne (domain_id, (normalized_keywords,...), redirection) pour
    chaque domaine. Tuples pour compat lru_cache."""
    cfg = _load_config()
    out: list[tuple[str, tuple[str, ...], str]] = []
    for domain_id, spec in (cfg.get("domains") or {}).items():
        kws_raw = spec.get("keywords") or []
        redirection = str(spec.get("redirection") or "").strip()
        if not redirection:
            continue
        kws = tuple(_normalize_text(str(k)) for k in kws_raw if k)
        if kws:
            out.append((domain_id, kws, redirection))
    return tuple(out)


def detect_out_of_scope(query: str) -> Optional[OutOfScopeMatch]:
    """Retourne un OutOfScopeMatch si la query sort du périmètre Droit Social,
    None sinon.

    Logique :
      1. Si la query (brut) matche l'un des `priority_override.patterns` →
         None (on continue le pipeline normal, la question est dans le scope
         Droit Social malgré la présence d'un mot-clé apparemment hors-scope).
      2. Pour chaque domaine (dans l'ordre du YAML), substring match normalisé
         sur les keywords. Premier match gagne.
      3. Aucun match → None.
    """
    if not query or not query.strip():
        return None

    # Phase 1 : override CT
    for pat in _compiled_overrides():
        if pat.search(query):
            return None

    # Phase 2 : match domaine
    normalized = _normalize_text(query)
    for domain_id, keywords, redirection in _normalized_domains():
        for kw in keywords:
            if kw and kw in normalized:
                logger.info(
                    "[OutOfScope] domain=%s matched=%r → refus avec redirection",
                    domain_id,
                    kw,
                )
                return OutOfScopeMatch(domain=domain_id, redirection=redirection)

    return None


def clear_out_of_scope_cache() -> None:
    """Invalide les trois caches (YAML, overrides, domaines). À appeler
    après modification du fichier YAML pour hot-reload."""
    _load_config.cache_clear()
    _compiled_overrides.cache_clear()
    _normalized_domains.cache_clear()


__all__ = [
    "OutOfScopeMatch",
    "detect_out_of_scope",
    "clear_out_of_scope_cache",
]
