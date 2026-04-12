"""
Configuration centralisée pour le pipeline juridique V1 standalone.
Aucune dépendance au reste du repo.
"""

from pathlib import Path

# ─── Ollama ───────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434"

# ─── Modèles ──────────────────────────────────────────────────────────────────
SPEED_MODEL = "gemma4:e4b"    # Léger, pour extraction / vérification
QUALITY_MODEL = "gemma4:26b"  # Pour plus tard (rédaction qualité)

# ─── Base de connaissances ────────────────────────────────────────────────────
KNOWLEDGE_BASE_PATH = Path("knowledge/droit_social/licenciement_economique")

# ─── Timeouts ─────────────────────────────────────────────────────────────────
PIPELINE_TIMEOUT = 300.0   # 5 minutes — confortable pour les gros modèles
OLLAMA_TIMEOUT = 120.0     # Timeout par appel Ollama

# ─── BM25 ─────────────────────────────────────────────────────────────────────
BM25_K1 = 1.5
BM25_B = 0.75
MAX_SOURCES = 5

# ─── Sampling params par agent ────────────────────────────────────────────────
LECTEUR_PARAMS = {
    "model": SPEED_MODEL,
    "temperature": 0,
    "top_p": 1,
    "num_predict": 1024,
}

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
    "num_predict": 2048,
}

VERIFICATEUR_PARAMS = {
    "model": SPEED_MODEL,
    "temperature": 0,
    "top_p": 1,
    "num_predict": 2048,
}
