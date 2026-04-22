"""
VerificateurAgent — vérifie que les citations de la note correspondent aux sources.

Phase A Cerveau Oiseaux : 100 % déterministe. Pas de LLM.

Pour chaque [REF: xxx] ou [xxx] dans la note :
  1. Vérifie l'existence dans les sources fournies (matching exact sur IDs).
  2. Supprime les citations invalides par regex (couvre les deux formats).
  3. Calcule un score de fiabilité et rend un verdict.

Le gain principal n'est pas sur le cas général (déjà ~50 ms sans appel LLM) :
c'est sur le cas *hallucinations détectées* qui appelait auparavant gemma4:e4b
(~10 s). Désormais, même dans ce cas, on reste local et déterministe.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List

from .perf.events import emit

logger = logging.getLogger(__name__)


def _extract_citations(note: str) -> List[str]:
    """Extrait toutes les références [REF: xxx] et [xxx] présentes dans la note."""
    matches = re.findall(r'\[REF:\s*([^\]]+)\]|\[([A-Za-z0-9_\-\.]+)\]', note)
    return [m[0].strip() or m[1] for m in matches if m[0] or m[1]]


def _build_source_ids(sources_json: str) -> Dict[str, str]:
    """Construit un dict {ID_UPPER: extrait} depuis le JSON des sources."""
    try:
        data = json.loads(sources_json)
        result: Dict[str, str] = {}
        for s in data.get("sources", []) + data.get("jurisprudences", []):
            sid = s.get("id", "")
            if sid:
                result[sid.upper()] = s.get("extrait", "")
        return result
    except Exception:
        return {}


async def handle(note_markdown: str, sources_json: str) -> str:
    """
    Vérifie la note contre les sources — 100 % déterministe.

    Args:
        note_markdown: Note rédigée par redacteur.handle().
        sources_json: JSON des sources (retriever.handle()).

    Returns:
        JSON string avec rapport de vérification + note corrigée.
    """
    t0 = time.perf_counter()

    source_ids = _build_source_ids(sources_json)
    citations = _extract_citations(note_markdown)

    # ── Cas : aucune citation dans la note ────────────────────────────────────
    if not citations:
        dt_ms = (time.perf_counter() - t0) * 1000
        emit(
            "cerveau_oiseau",
            "completed",
            hook_name="verifie_citations",
            duration_ms=dt_ms,
            n_total=0,
            n_ok=0,
            n_invalid=0,
        )
        logger.info(
            "[CerveauOiseau] Vérificateur: 0 citation détectée → NON VÉRIFIABLE (%.0fms)",
            dt_ms,
        )
        result: Dict[str, Any] = {
            "citations_verifiees": [],
            "citations_invalides": [],
            "note_corrigee": note_markdown,
            "score_fiabilite": 0.0,
            "verdict": "NON VÉRIFIABLE",
            "avertissement": (
                "Aucune citation [REF] détectée dans la note. "
                "La note ne peut pas être vérifiée sans référence aux sources."
            ),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ── Vérification locale (matching exact sur IDs) ──────────────────────────
    verifiees: List[Dict[str, Any]] = []
    invalides: List[Dict[str, Any]] = []
    for cit in citations:
        if cit.upper() in source_ids:
            verifiees.append({
                "reference": cit,
                "statut": "OK",
                "correspondance": 1.0,
            })
            emit(
                "verificateur",
                "completed",
                hook_name="verifie_citation",
                cite=cit,
                ok=True,
            )
        else:
            invalides.append({
                "reference": cit,
                "statut": "INTROUVABLE",
                "action": "supprimé",
            })
            emit(
                "verificateur",
                "completed",
                hook_name="verifie_citation",
                cite=cit,
                ok=False,
            )

    # ── Suppression déterministe des citations hallucinées ────────────────────
    # Couvre les deux formats produits par le Rédacteur :
    #   [REF: xxx] (prompts/redacteur_system.txt)
    #   [xxx]     (prompts/redacteur_search_system.txt)
    note_corrigee = note_markdown
    for inv in invalides:
        ref = re.escape(inv["reference"])
        note_corrigee = re.sub(rf'\[REF:\s*{ref}\]|\[{ref}\]', '', note_corrigee)

    nb_total = len(citations)
    nb_ok = len(verifiees)
    score = nb_ok / nb_total if nb_total > 0 else 1.0

    if invalides:
        verdict = "CORRIGÉ" if score >= 0.5 else "INSUFFISANT"
    else:
        verdict = "VALIDÉ"

    dt_ms = (time.perf_counter() - t0) * 1000
    emit(
        "cerveau_oiseau",
        "completed",
        hook_name="verifie_citations",
        duration_ms=dt_ms,
        n_total=nb_total,
        n_ok=nb_ok,
        n_invalid=len(invalides),
    )
    logger.info(
        "[CerveauOiseau] Vérificateur: %d citations, %d validées, "
        "%d hallucinée(s) supprimée(s) → %s (%.0fms)",
        nb_total,
        nb_ok,
        len(invalides),
        verdict,
        dt_ms,
    )

    result = {
        "citations_verifiees": verifiees,
        "citations_invalides": invalides,
        "note_corrigee": note_corrigee,
        "score_fiabilite": round(score, 2),
        "verdict": verdict,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)
