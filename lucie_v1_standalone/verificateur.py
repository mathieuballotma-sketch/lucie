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
import os
import re
import time
from typing import Any, Dict, List

from .perf.events import emit

logger = logging.getLogger(__name__)


# Sprint 6 P2a — B-6 sol 1 : feature flag de normalisation des citations.
# - flag=1 : regex étendue (4 formats : [REF: xxx] / [xxx] / (xxx) / "article xxx")
#   + canonicalisation strip/dots/upper sur citations ET ids sources pour le
#   matching, tout en préservant la forme originale dans le JSON de retour.
# - flag=0 : comportement legacy strict (regex pré-P2a, matching `upper()` seul).
_NORMALISE = os.environ.get("BEAUME_VERIFICATEUR_NORMALISE", "1") == "1"

_CITATION_RE = re.compile(
    r"\[REF:\s*([^\]]+)\]"                                                # [REF: xxx]
    r"|\[([A-Za-z0-9_\-\.\s]+?)\]"                                         # [xxx] avec espaces tolérés
    r"|\(([LRDA]\.?\s*\d{3,4}-\d+(?:-\d+)?)\)"                            # (L.1233-3)
    r"|(?<![A-Za-z0-9])article\s+([LRDA]\.?\s*\d{3,4}-\d+(?:-\d+)?)",     # « article L.1234-9 » (prose)
    re.IGNORECASE,
)

_LEGACY_CITATION_RE = re.compile(r"\[REF:\s*([^\]]+)\]|\[([A-Za-z0-9_\-\.]+)\]")


def _canonicalize(s: str) -> str:
    """Strip + remove dots/spaces + upper — clé de matching commune entre
    citations Rédacteur (« L.1233-3 », « L. 1233-3 ») et IDs Légifrance
    (« L1233-3 »). Préserve les chiffres et lettres pour les jurisprudences."""
    return re.sub(r"\s+", "", s).replace(".", "").upper()


def _extract_citations(note: str) -> List[str]:
    """Extrait toutes les références citations de la note.

    flag=1 (normalise) : 4 formats acceptés (cf. `_CITATION_RE`), dédupliqué
    sur la forme canonique en conservant la première forme rencontrée.
    flag=0 (legacy) : regex pré-P2a, matching `[REF: xxx]` et `[xxx]` stricts.
    """
    if _NORMALISE:
        seen: Dict[str, str] = {}
        for groups in _CITATION_RE.findall(note):
            cit = next((g for g in groups if g), "").strip()
            if not cit:
                continue
            key = _canonicalize(cit)
            if key and key not in seen:
                seen[key] = cit
        return list(seen.values())
    matches = _LEGACY_CITATION_RE.findall(note)
    return [m[0].strip() or m[1] for m in matches if m[0] or m[1]]


def _build_source_ids(sources_json: str) -> Dict[str, str]:
    """Construit un dict {clé_normalisée: extrait} depuis le JSON des sources.

    flag=1 : clé canonicalisée (strip/dots/upper) → tolère « L.1233-3 » vs
    « L1233-3 » entre Rédacteur et Légifrance. flag=0 : clé `upper()` seule."""
    try:
        data = json.loads(sources_json)
        result: Dict[str, str] = {}
        for s in data.get("sources", []) + data.get("jurisprudences", []):
            sid = s.get("id", "")
            if sid:
                key = _canonicalize(sid) if _NORMALISE else sid.upper()
                result[key] = s.get("extrait", "")
        return result
    except json.JSONDecodeError as exc:
        # Audit 2026-05-12 P0 #1 : avant ce log, un sources_json malformé
        # produisait silencieusement source_ids={}, rendant TOUTES les citations
        # INVALIDES sans trace. Retour {} reste pour ne pas casser la pipeline,
        # mais l'erreur est désormais tracée pour diagnostic.
        logger.error(
            "Vérificateur : sources_json malformé, source_ids vide (%s)",
            exc,
        )
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
        # Discriminant : une note "0 citation" peut être un refus poli du
        # rédacteur (sources insuffisantes — comportement attendu) ou une
        # hallucination (texte sans la moindre référence). Le log distingue
        # les deux pour faciliter le triage des régressions.
        is_kb_refusal = (
            "RÉDACTION IMPOSSIBLE" in note_markdown
            or "Cette information n'est pas dans mes sources" in note_markdown
        )
        emit(
            "cerveau_oiseau",
            "completed",
            hook_name="verifie_citations",
            duration_ms=dt_ms,
            n_total=0,
            n_ok=0,
            n_invalid=0,
            kb_refusal=is_kb_refusal,
        )
        if is_kb_refusal:
            logger.info(
                "[CerveauOiseau] Vérificateur: 0 citation (refus poli — "
                "couverture KB insuffisante) (%.0fms)",
                dt_ms,
            )
        else:
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
        key = _canonicalize(cit) if _NORMALISE else cit.upper()
        if key in source_ids:
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
