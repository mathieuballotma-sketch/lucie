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
# Feature flag on par défaut (Bloquant #1 v1.0.0). Override avec LUCIE_LEGIFRANCE=0 pour désactiver.
LEGIFRANCE_ENABLED: bool = os.environ.get("LUCIE_LEGIFRANCE", "1") == "1"
LEGIFRANCE_SYNC_INTERVAL_HOURS: int = 48


def _get_app_support_dir() -> Path:
    """Répertoire Application Support utilisé par Beaume.

    Politique de migration (rebrand Lucie → Beaume, 2026-05-02) :
      - Si ``~/Library/Application Support/Lucie`` existe SEUL, on le copie
        vers ``Beaume`` au premier démarrage (idempotent : skip si Beaume
        existe déjà).
      - Le code interne continue à pointer vers Beaume après migration.

    Ne lève jamais — un échec de migration est loggé mais on retombe sur le
    legacy pour ne pas casser le démarrage HUD.
    """
    home = Path.home() / "Library" / "Application Support"
    legacy = home / "Lucie"
    current = home / "Beaume"

    if legacy.exists() and not current.exists():
        try:
            import shutil
            shutil.copytree(legacy, current)
        except Exception:
            # Migration best-effort. Si elle échoue, on continue sur le legacy
            # pour que le HUD démarre quand même.
            return legacy
    return current if current.exists() else legacy


def get_legifrance_db_path() -> Path:
    """
    Chemin de la base SQLite Légifrance.

    Override via `LUCIE_LEGIFRANCE_DIR` (utile en dev / tests pour
    pointer vers un répertoire isolé). Par défaut :
    `~/Library/Application Support/Beaume/legifrance/legi.sqlite`
    (migration auto depuis l'ancien répertoire ``Lucie/`` au premier démarrage).
    """
    override = os.environ.get("LUCIE_LEGIFRANCE_DIR")
    if override:
        base = Path(override).expanduser()
    else:
        base = _get_app_support_dir() / "legifrance"
    return base / "legi.sqlite"

# ─── Timeouts ─────────────────────────────────────────────────────────────────
# PIPELINE_TIMEOUT aligné sur le read-timeout Ollama : on laisse le LLM aller
# au bout d'une génération longue avant d'abandonner côté pipeline.
PIPELINE_TIMEOUT = 300.0   # 5 min — s'aligne sur le read-timeout Ollama ci-dessous

# Timeout composite Ollama : connect court (détecte un service down vite),
# read long (supporte les générations pesantes type Q analyse détaillée sur
# gemma4:e4b en CPU/GPU local). Retour d'incident 2026-04-22 : ReadTimeout
# après 90 s sur Q1 « explique-moi en détail les conditions… » faisait
# échouer silencieusement la requête. Tous les agents (Lecteur / Rédacteur
# / Vérificateur) passent par ici.
OLLAMA_TIMEOUT = 300.0             # compat — utilisé ailleurs comme durée "totale"
OLLAMA_CONNECT_TIMEOUT = 10.0      # ouverture socket Ollama (doit être court)
OLLAMA_READ_TIMEOUT = 300.0        # attente du premier octet d'une réponse
OLLAMA_WRITE_TIMEOUT = 10.0        # envoi du prompt (prompt texte, jamais lourd)
OLLAMA_POOL_TIMEOUT = 10.0         # acquisition connexion dans le pool httpx

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
# R1 sprint S1 (2026-04-27) : calé sur la config gagnante du sweep
# 2026-04-25 (`predict_200`, Phase 2, 18 prompts sur gemma4:e4b → TTFT
# moyen 1478 ms, 1er au classement). Quatre ajustements :
#   - num_predict 512 → 200 (réponses N1 courtes ; cap aligné sur sweep)
#   - num_ctx 2048 → 4096 (parité avec sweep + marge sécurité contexte)
#   - top_k = 20 (NEW — borne le sampling, réduit la variance latence)
#   - repeat_penalty = 1.1 (NEW — évite les boucles N1 courtes)
# REDACTEUR/LECTEUR/VERIFICATEUR délibérément exclus du tuning S1 (cf.
# rapport agent S1_Speed-Optimizer_R1-R2-R3.md pour la justification).
DIRECT_PARAMS = {
    "model": SPEED_MODEL,
    "temperature": 0.3,
    "top_p": 0.9,
    "top_k": 20,
    "repeat_penalty": 1.1,
    "num_predict": 200,
    "num_ctx": 4096,
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
