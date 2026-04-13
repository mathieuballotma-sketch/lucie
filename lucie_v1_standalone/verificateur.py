"""
VerificateurAgent — vérifie que les citations de la note correspondent aux sources.
Modèle : gemma4:e4b (speed).

Pour chaque [REFERENCE] dans la note :
  1. Vérifie qu'elle existe dans les sources fournies.
  2. Supprime les citations invalides.
  3. Calcule un score de fiabilité et rend un verdict.

Aucune dépendance au reste du repo.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from . import ollama_client
from .config import VERIFICATEUR_PARAMS

_SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "verificateur_system.txt"


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
    Vérifie la note contre les sources.

    Args:
        note_markdown: Note rédigée par redacteur.handle().
        sources_json: JSON des sources (retriever.handle()).

    Returns:
        JSON string avec rapport de vérification + note corrigée.
    """
    source_ids = _build_source_ids(sources_json)
    citations = _extract_citations(note_markdown)

    # ── Cas : aucune citation dans la note ────────────────────────────────────
    if not citations:
        result: Dict[str, Any] = {
            "citations_verifiees": [],
            "citations_invalides": [],
            "note_corrigee": note_markdown,
            "score_fiabilite": 1.0,
            "verdict": "VALIDÉ",
            "avertissement": "Aucune citation [REF] détectée dans la note.",
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
        else:
            invalides.append({
                "reference": cit,
                "statut": "INTROUVABLE",
                "action": "supprimé",
            })

    # ── Si des citations sont invalides → affiner avec le LLM ─────────────────
    if invalides:
        system = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        prompt = (
            "## Note à vérifier\n\n"
            f"{note_markdown}\n\n"
            "## Sources disponibles (IDs valides)\n\n"
            f"```json\n{sources_json}\n```\n\n"
            "Vérifie chaque citation [XXX] dans la note. "
            "Pour les citations invalides, supprime-les du texte et retourne le JSON demandé "
            "avec la note corrigée dans le champ `note_corrigee`."
        )

        options = {k: v for k, v in VERIFICATEUR_PARAMS.items() if k != "model"}

        response = await ollama_client.generate(
            model=VERIFICATEUR_PARAMS["model"],
            prompt=prompt,
            system=system,
            options=options,
        )
        llm_parsed = ollama_client.extract_json_from_response(response)
        if llm_parsed and "note_corrigee" in llm_parsed:
            return json.dumps(llm_parsed, ensure_ascii=False, indent=2)
        # Fallback si LLM ne produit pas le JSON attendu

    # ── Construction locale de la note corrigée ───────────────────────────────
    note_corrigee = note_markdown
    for inv in invalides:
        ref = re.escape(inv["reference"])
        note_corrigee = re.sub(rf'\[{ref}\]', '', note_corrigee)

    nb_total = len(citations)
    nb_ok = len(verifiees)
    score = nb_ok / nb_total if nb_total > 0 else 1.0

    if invalides:
        verdict = "CORRIGÉ" if score >= 0.5 else "INSUFFISANT"
    else:
        verdict = "VALIDÉ"

    result = {
        "citations_verifiees": verifiees,
        "citations_invalides": invalides,
        "note_corrigee": note_corrigee,
        "score_fiabilite": round(score, 2),
        "verdict": verdict,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)
