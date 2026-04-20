"""
Configuration centralisée pour le pipeline juridique V1 standalone.
Aucune dépendance au reste du repo.
"""

import os
from pathlib import Path

# ─── Ollama ───────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434"

# ─── Modèles ──────────────────────────────────────────────────────────────────
SPEED_MODEL = "gemma4:e4b"    # Léger, pour extraction / vérification
QUALITY_MODEL = "gemma4:26b"  # Pour plus tard (rédaction qualité)

# ─── Base de connaissances ────────────────────────────────────────────────────
KNOWLEDGE_BASE_PATH = Path("knowledge/droit_social/licenciement_economique")

# ─── Légifrance (base DILA live) ──────────────────────────────────────────────
# Feature flag off par défaut — activer seulement après un premier sync.
LEGIFRANCE_ENABLED: bool = os.environ.get("LUCIE_LEGIFRANCE", "0") == "1"
LEGIFRANCE_SYNC_INTERVAL_HOURS: int = 48


def get_legifrance_db_path() -> Path:
    """
    Chemin de la base SQLite Légifrance.

    Override via `LUCIE_LEGIFRANCE_DIR` (utile en dev / tests pour
    pointer vers un répertoire isolé). Par défaut :
    `~/Library/Application Support/Lucie/legifrance/legi.sqlite`.
    """
    override = os.environ.get("LUCIE_LEGIFRANCE_DIR")
    if override:
        base = Path(override).expanduser()
    else:
        base = Path.home() / "Library" / "Application Support" / "Lucie" / "legifrance"
    return base / "legi.sqlite"

# ─── Timeouts ─────────────────────────────────────────────────────────────────
PIPELINE_TIMEOUT = 120.0   # 2 minutes — suffisant avec les params optimisés
OLLAMA_TIMEOUT = 90.0      # Timeout par appel Ollama (réduit avec num_ctx=4096)

# ─── BM25 ─────────────────────────────────────────────────────────────────────
BM25_K1 = 1.5
BM25_B = 0.75
MAX_SOURCES = 3  # Réduit de 5 → 3 : moins de tokens dans le prompt du Rédacteur

# ─── Options GPU/performance communes ─────────────────────────────────────────
_BASE_GPU_OPTIONS = {
    "num_ctx": 4096,   # Fenêtre réduite (défaut 8192 = lent sur Apple Silicon)
    "num_batch": 512,  # Batch size pour le prompt processing
    "num_gpu": 99,     # Tout sur GPU
}

# ─── Sampling params par agent ────────────────────────────────────────────────
LECTEUR_PARAMS = {
    "model": SPEED_MODEL,
    "temperature": 0,
    "top_p": 1,
    "num_predict": 1024,
    **_BASE_GPU_OPTIONS,
}

# RETRIEVER_PARAMS : non utilisé — le Retriever est 100% BM25, zéro appel LLM.
RETRIEVER_PARAMS = {
    "model": SPEED_MODEL,
    "temperature": 0.1,
    "top_p": 0.9,
}

REDACTEUR_PARAMS = {
    "model": SPEED_MODEL,
    "temperature": 0.3,
    "top_p": 0.9,
    "repeat_penalty": 1.1,
    "num_predict": 4096,   # Augmenté (2048 → 4096) : notes tronquées sinon
    **_BASE_GPU_OPTIONS,
}

VERIFICATEUR_PARAMS = {
    "model": SPEED_MODEL,
    "temperature": 0,
    "top_p": 1,
    "num_predict": 512,   # Réduit (2048 → 512) : réponse courte suffisante
    **_BASE_GPU_OPTIONS,
}

# ─── Niveau 1 — Réponse directe (chat simple, définitions, salutations) ───────
# Contexte minimal + num_predict court = 2-3s au lieu de 15-30s
DIRECT_PARAMS = {
    "model": SPEED_MODEL,
    "temperature": 0.3,
    "top_p": 0.9,
    "num_predict": 512,   # Court — réponse directe, pas de note longue
    "num_ctx": 2048,      # Fenêtre réduite (vs 4096) : prompt simple, moins de mémoire GPU
    "num_batch": 512,
    "num_gpu": 99,
}

# ─── Analyse de dossiers complets ────────────────────────────────────────────
DOSSIER_LECTEUR_PARAMS = {
    "model": SPEED_MODEL,
    "temperature": 0.1,   # Très bas pour l'extraction factuelle
    "top_p": 1,
    "num_predict": 1024,
    **_BASE_GPU_OPTIONS,
}

DOSSIER_SYNTHESE_PARAMS = {
    "model": SPEED_MODEL,
    "temperature": 0.3,
    "top_p": 0.9,
    "repeat_penalty": 1.1,
    "num_predict": 4096,
    **_BASE_GPU_OPTIONS,
}

MAX_CHUNK_TOKENS = 650        # Tokens max par chunk (optimal Gemma 4 avec contexte 4096)
MAX_FILES_PER_DOSSIER = 50    # Limite de fichiers par dossier
DOSSIER_TIMEOUT = 600.0       # 10 min — dossiers volumineux
