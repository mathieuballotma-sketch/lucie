"""
Vérification de l'environnement au premier lancement de Lucie V1.

Vérifie dans l'ordre :
  1. Ollama est installé et en cours d'exécution
  2. Le modèle gemma4:e4b est disponible localement (sinon, le télécharge)
  3. La base juridique est présente et non vide

Usage interne :
    from .setup import ensure_ready
    status = await ensure_ready(verbose=True)
"""

import asyncio
import sys
from pathlib import Path

import httpx

from .config import KNOWLEDGE_BASE_PATH, OLLAMA_BASE_URL, SPEED_MODEL


# ─── Helpers privés ───────────────────────────────────────────────────────────


async def _check_ollama() -> dict:
    """Interroge GET /api/tags pour vérifier qu'Ollama répond."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            return {"ok": True, "models": resp.json().get("models", [])}
    except httpx.ConnectError:
        return {"ok": False, "error": "connect"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _model_available(models: list, model_name: str) -> bool:
    """
    Retourne True si model_name est dans la liste retournée par Ollama.
    Gère les variantes avec/sans tag ':latest'.
    """
    base = model_name.split(":")[0]
    tag = model_name.split(":")[1] if ":" in model_name else "latest"
    for m in models:
        name = m.get("name", "")
        # Correspondance exacte ou variante :latest implicite
        if name == model_name:
            return True
        if name == f"{base}:{tag}":
            return True
        if tag == "latest" and name == base:
            return True
    return False


async def _pull_model(model_name: str) -> bool:
    """
    Lance `ollama pull <model>` en sous-processus et stream la sortie.
    Retourne True si le téléchargement s'est terminé avec succès.
    """
    print(
        "\nTéléchargement du modèle en cours... (≈10 Go, première fois uniquement)",
        flush=True,
    )
    print("Cela peut prendre plusieurs minutes selon votre connexion.\n", flush=True)

    try:
        process = await asyncio.create_subprocess_exec(
            "ollama", "pull", model_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        async for raw_line in process.stdout:
            line = raw_line.decode(errors="replace").rstrip()
            if line:
                print(f"  {line}", flush=True)

        await process.wait()
        return process.returncode == 0

    except FileNotFoundError:
        print(
            "\nErreur : la commande `ollama` est introuvable dans votre PATH.",
            file=sys.stderr,
        )
        return False


def _check_knowledge_base(kb_path: Path) -> dict:
    """Vérifie que la base juridique existe et contient des fichiers .md."""
    if not kb_path.exists():
        return {"ok": False, "reason": "missing_dir"}
    md_files = list(kb_path.glob("*.md"))
    if not md_files:
        return {"ok": False, "reason": "empty"}
    return {"ok": True, "file_count": len(md_files)}


# ─── Fonction publique ────────────────────────────────────────────────────────


async def ensure_ready(verbose: bool = True) -> dict:
    """
    Vérifie que l'environnement Lucie est opérationnel avant le lancement du pipeline.

    Étapes :
      1. Ollama répond sur http://localhost:11434
      2. Le modèle SPEED_MODEL (gemma4:e4b) est disponible — sinon, le télécharge
      3. La base juridique contient des fichiers .md — sinon, crée le répertoire
         et affiche les instructions

    Returns:
        {
            "ollama_ok":    bool,
            "model_ok":     bool,
            "knowledge_ok": bool,
            "errors":       list[str],   # clés d'erreur lisibles par le code appelant
        }

    Note : une base juridique vide n'est pas bloquante (le pipeline tourne en mode
    dégradé et le rédacteur refusera de rédiger sans sources).
    """
    status: dict = {
        "ollama_ok": False,
        "model_ok": False,
        "knowledge_ok": False,
        "errors": [],
    }

    if verbose:
        print("Vérification de l'environnement Lucie...", flush=True)

    # ── 1. Ollama ──────────────────────────────────────────────────────────────
    ollama = await _check_ollama()

    if not ollama["ok"]:
        print(
            "\nOllama n'est pas installé ou n'est pas démarré.\n"
            "  → Téléchargez-le sur https://ollama.ai\n"
            "  → Puis lancez dans un terminal : ollama serve",
            file=sys.stderr,
        )
        status["errors"].append("ollama_not_running")
        return status  # Impossible de continuer sans Ollama

    status["ollama_ok"] = True
    if verbose:
        print("  ✓ Ollama opérationnel.", flush=True)

    # ── 2. Modèle ──────────────────────────────────────────────────────────────
    models = ollama["models"]

    if not _model_available(models, SPEED_MODEL):
        if verbose:
            print(
                f"  ⚠ Modèle {SPEED_MODEL} absent. Lancement du téléchargement...",
                flush=True,
            )
        ok = await _pull_model(SPEED_MODEL)
        if not ok:
            print(
                f"\nÉchec du téléchargement de {SPEED_MODEL}.\n"
                f"  → Relancez manuellement : ollama pull {SPEED_MODEL}",
                file=sys.stderr,
            )
            status["errors"].append("model_pull_failed")
            return status
        if verbose:
            print(f"  ✓ Modèle {SPEED_MODEL} téléchargé.", flush=True)
    else:
        if verbose:
            print(f"  ✓ Modèle {SPEED_MODEL} disponible.", flush=True)

    status["model_ok"] = True

    # ── 3. Base juridique ──────────────────────────────────────────────────────
    kb = _check_knowledge_base(KNOWLEDGE_BASE_PATH)

    if not kb["ok"]:
        if kb["reason"] == "missing_dir":
            KNOWLEDGE_BASE_PATH.mkdir(parents=True, exist_ok=True)
            print(
                f"\n⚠ Base juridique absente — répertoire créé : {KNOWLEDGE_BASE_PATH.resolve()}\n"
                f"  → Copiez vos fichiers .md dans ce dossier avant de relancer.",
                file=sys.stderr,
            )
        else:
            print(
                f"\n⚠ Base juridique vide ({KNOWLEDGE_BASE_PATH.resolve()})\n"
                f"  → Ajoutez des fichiers .md pour que Lucie puisse citer des sources.",
                file=sys.stderr,
            )
        status["errors"].append("knowledge_base_empty")
        # Non bloquant : le pipeline gère l'absence de sources en aval
    else:
        status["knowledge_ok"] = True
        if verbose:
            print(
                f"  ✓ Base juridique prête. ({kb['file_count']} source(s))",
                flush=True,
            )

    if verbose and not status["errors"]:
        print("Environnement prêt.\n", flush=True)

    return status
