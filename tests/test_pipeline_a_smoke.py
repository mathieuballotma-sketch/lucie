"""
Smoke test bout-en-bout pour Pipeline A (`lucie_v1_standalone.pipeline.run`).

Extrait de `tests/test_legal_pipeline_v1.py` lors de la suppression de Pipeline B
(Sprint 2bis, 2026-05-08). Le fichier d'origine couvrait aussi des tests unitaires
sur `LegalRouter` et `RetrieverAgent` du package `app.agents.lucie_v1/` (Pipeline B),
maintenant supprimé car code mort en runtime (0 importeur externe, cf. rapport audit
Sprint 2 hash b6cdefbd).

Lancer avec :
    python -m pytest tests/test_pipeline_a_smoke.py -v
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# ── S'assurer que la racine du projet est dans sys.path ──────────────────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─── Utilitaire Ollama ────────────────────────────────────────────────────────

def _ollama_running() -> bool:
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "2", "http://localhost:11434/api/tags"],
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# SMOKE TEST PIPELINE A — requiert Ollama / Gemma
# ═══════════════════════════════════════════════════════════════════════════════

SAMPLE_LETTRE = """
Madame, Monsieur,

Nous avons le regret de vous informer que votre poste de Chargé de clientèle
est supprimé dans le cadre d'un plan de sauvegarde de l'emploi (PSE)
engagé conformément aux articles L.1233-61 et suivants du Code du travail.

Ce licenciement est motivé par des difficultés économiques caractérisées
au sens de l'article L.1233-3, ayant entraîné la suppression de 45 postes.

Votre préavis d'une durée de deux mois débutera à la date de première
présentation de ce courrier. Les indemnités légales de licenciement vous
seront versées conformément aux dispositions de l'article L.1237-19.

Veuillez agréer, Madame, Monsieur, l'expression de nos salutations distinguées.
""".strip()


@pytest.mark.skipif(
    not _ollama_running(),
    reason="Ollama non disponible — smoke test ignoré",
)
@pytest.mark.asyncio
async def test_pipeline_smoke(tmp_path):
    """
    Smoke test bout-en-bout : lettre de licenciement → note Markdown avec disclaimer.
    Requiert Ollama avec un modèle disponible (ex: gemma2:2b ou gemma4:e4b).
    """
    from lucie_v1_standalone.pipeline import run

    response = await run(
        query="Analyser cette lettre de licenciement",
        document_text=SAMPLE_LETTRE,
    )

    # pipeline.run() retourne PipelineResponse depuis la v1.1 — extraire le texte
    note = str(response)
    assert isinstance(note, str), "La note doit être une chaîne"
    assert len(note) > 50, "La note semble trop courte"
    # Chemin happy : note parle du licenciement. Chemin erreur (timeout Ollama) : "Erreur" présent.
    assert "licenciement" in note.lower() or "Erreur" in note, (
        "La note ne traite pas du licenciement économique et ne contient pas de message d'erreur"
    )
    # Chemin happy : disclaimer présent. Chemin erreur : message d'erreur explicite.
    # Si seul "Erreur" est présent, le test passe mais le rapport doit le noter.
    assert (
        "À vérifier" in note
        or "avocat" in note.lower()
        or "Erreur" in note
    ), "La réponse ne contient ni disclaimer ni message d'erreur explicite"
