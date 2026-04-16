"""
LegalPipeline — orchestrateur intelligent à 3 niveaux.

Niveaux de traitement :
  1. direct   → 1 appel LLM avec prompt minimaliste (2-3s)
  2. search   → Retriever → Rédacteur → Vérificateur, sans Lecteur (15-20s)
  3. document → Pipeline complet : Lecteur → Retriever → Rédacteur → Vérificateur (30-45s)

Aucune dépendance au reste du repo.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

from . import dossier_analyzer, lecteur, ollama_client, redacteur, retriever, verificateur
from .config import DIRECT_PARAMS, DOSSIER_TIMEOUT, PIPELINE_TIMEOUT
from .router import is_dossier, route as router_route, validate as router_validate

_DIRECT_SYSTEM_PATH = Path(__file__).parent / "prompts" / "direct_system.txt"


async def run(
    query: str,
    document_text: Optional[str] = None,
    dossier_path: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> str:
    """
    Exécute le pipeline au niveau approprié avec timeout global.

    Args:
        query: Requête de l'utilisateur.
        document_text: Texte du document à analyser (optionnel).
        dossier_path: Chemin vers un dossier complet (optionnel).
        force: Force le mode search sans routing (pour les démos).
        verbose: Affiche les étapes dans le terminal.

    Returns:
        Réponse en Markdown, ou message d'erreur.
    """
    # Mode dossier : pipeline dédié avec timeout étendu
    if dossier_path and is_dossier(dossier_path):
        return await _run_dossier(query, dossier_path, force, verbose)

    start = time.time()
    if verbose:
        print(f"⚖️  Pipeline démarré — {query[:80]}…", flush=True)
    try:
        result = await asyncio.wait_for(
            _run_pipeline(query, document_text, force, verbose),
            timeout=PIPELINE_TIMEOUT,
        )
        elapsed = time.time() - start
        if verbose:
            print(f"⚖️  Pipeline terminé en {elapsed:.1f}s", flush=True)
        return result
    except asyncio.TimeoutError:
        elapsed = time.time() - start
        return (
            f"**Erreur** : le pipeline a dépassé le timeout de "
            f"{PIPELINE_TIMEOUT:.0f}s après {elapsed:.1f}s. "
            "Réessayez ou réduisez la taille du document."
        )
    except Exception as exc:
        return f"**Erreur pipeline** : {exc}"


async def _run_dossier(
    query: str,
    dossier_path: str,
    force: bool,
    verbose: bool,
) -> str:
    """Exécute l'analyse de dossier complet."""
    start = time.time()
    if verbose:
        print(f"📁 Pipeline DOSSIER démarré — {query[:80]}…", flush=True)

    # Router (scope check) — on utilise force pour les dossiers si demandé
    if not force:
        routing = router_validate(query, force=False)
        if not routing["valid"]:
            return str(routing["refusal_reason"])

    try:
        report = await asyncio.wait_for(
            dossier_analyzer.analyze_dossier(
                folder_path=dossier_path,
                instruction=query,
                verbose=verbose,
            ),
            timeout=DOSSIER_TIMEOUT,
        )
        elapsed = time.time() - start
        if verbose:
            print(f"📁 Pipeline DOSSIER terminé en {elapsed:.1f}s", flush=True)
        return dossier_analyzer.format_report(report)
    except asyncio.TimeoutError:
        elapsed = time.time() - start
        return (
            f"**Erreur** : l'analyse du dossier a dépassé le timeout de "
            f"{DOSSIER_TIMEOUT:.0f}s après {elapsed:.1f}s. "
            "Réduisez le nombre de fichiers ou la taille du dossier."
        )
    except Exception as exc:
        return f"**Erreur analyse dossier** : {exc}"


async def _run_pipeline(
    query: str,
    document_text: Optional[str],
    force: bool,
    verbose: bool,
) -> str:

    # ── Vérification du scope (< 1ms) ─────────────────────────────────────────
    if not force:
        scope = router_validate(query, document_text)
        if not scope["valid"]:
            return str(scope["refusal_reason"])

    # ── Routage (< 1ms) ───────────────────────────────────────────────────────
    routing = router_route(query, document_text, force=force)
    level = routing["level"]

    if verbose:
        print(f"🔀 Router → niveau {level} ({routing['intent']})", flush=True)

    # ── Niveau 1 : Réponse directe ────────────────────────────────────────────
    if level == "direct":
        return await _direct_response(query, verbose)

    # ── Niveau 2 : Recherche juridique (sans document) ────────────────────────
    if level == "search":
        faits_json = json.dumps(
            {"type_document": "requete", "query": query},
            ensure_ascii=False,
        )
        return await _search_and_write(query, faits_json, verbose)

    # ── Niveau 3 : Pipeline complet (avec document) ───────────────────────────
    # level == "document"
    doc = routing.get("document") or document_text
    return await _full_pipeline(query, doc, verbose)


# ─── Niveau 1 ─────────────────────────────────────────────────────────────────

async def _direct_response(query: str, verbose: bool) -> str:
    """Réponse directe sans pipeline — prompt minimaliste, ~2-3s."""
    if verbose:
        print("💬 Réponse directe…", flush=True)

    system = _DIRECT_SYSTEM_PATH.read_text(encoding="utf-8")
    options = {k: v for k, v in DIRECT_PARAMS.items() if k != "model"}

    return await ollama_client.generate(
        model=DIRECT_PARAMS["model"],
        prompt=query,
        system=system,
        options=options,
    )


# ─── Niveau 2 ─────────────────────────────────────────────────────────────────

async def _search_and_write(query: str, faits_json: str, verbose: bool) -> str:
    """Recherche dans la base + rédaction, sans Lecteur — ~15-20s."""

    # Retriever
    if verbose:
        print("🔍 Retriever : recherche dans la base curatée…", flush=True)
    sources_json = await retriever.handle(faits_json)
    if verbose:
        print("✅ Retriever : sources récupérées", flush=True)

    # Rédacteur (mode search : prompt dédié)
    if verbose:
        print("✍️  Rédacteur : rédaction de la réponse…", flush=True)
    note_markdown = await redacteur.handle(faits_json, sources_json, mode="search")

    if note_markdown.startswith("**RÉDACTION IMPOSSIBLE**"):
        # Pas de sources → réponse directe de secours
        return await _direct_response(query, verbose)

    if verbose:
        print("✅ Rédacteur : réponse rédigée", flush=True)

    # Vérificateur
    if verbose:
        print("🔎 Vérificateur : contrôle des citations…", flush=True)
    verification_json = await verificateur.handle(note_markdown, sources_json)

    return _format_final(note_markdown, verification_json, verbose)


# ─── Niveau 3 ─────────────────────────────────────────────────────────────────

async def _full_pipeline(query: str, doc: Optional[str], verbose: bool) -> str:
    """Pipeline complet avec Lecteur — ~30-45s."""

    # Lecteur
    if verbose:
        print("📄 Lecteur : extraction des faits…", flush=True)
    faits_json = await lecteur.handle(doc)

    try:
        faits_data = json.loads(faits_json)
        if "erreur" in faits_data:
            return (
                f"**Erreur Lecteur** : {faits_data['erreur']}\n\n"
                "Le document fourni ne semble pas être une lettre "
                "de licenciement économique."
            )
    except json.JSONDecodeError:
        pass

    if verbose:
        print("✅ Lecteur : faits extraits", flush=True)

    # Retriever
    if verbose:
        print("🔍 Retriever : recherche dans la base curatée…", flush=True)
    sources_json = await retriever.handle(faits_json)
    if verbose:
        print("✅ Retriever : sources récupérées", flush=True)

    # Rédacteur (mode document : prompt formel complet)
    if verbose:
        print("✍️  Rédacteur : rédaction de la note…", flush=True)
    note_markdown = await redacteur.handle(faits_json, sources_json, mode="document")

    if note_markdown.startswith("**RÉDACTION IMPOSSIBLE**"):
        return (
            "# Note d'analyse — Licenciement économique\n\n"
            "> **Analyse partielle** — base curatée insuffisante.\n\n"
            "## Faits extraits\n\n"
            f"```json\n{faits_json}\n```\n\n"
            "## Sources disponibles\n\n"
            f"{note_markdown}\n\n"
            "_Note générée par Lucie V1 — à vérifier par un avocat qualifié._"
        )

    if verbose:
        print("✅ Rédacteur : note rédigée", flush=True)

    # Vérificateur
    if verbose:
        print("🔎 Vérificateur : contrôle des citations…", flush=True)
    verification_json = await verificateur.handle(note_markdown, sources_json)

    return _format_final(note_markdown, verification_json, verbose)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _format_final(note_markdown: str, verification_json: str, verbose: bool) -> str:
    """Applique le résultat du vérificateur et ajoute le disclaimer."""
    try:
        verification = json.loads(verification_json)
        note_finale = verification.get("note_corrigee", note_markdown)
        score = verification.get("score_fiabilite", 1.0)
        verdict = verification.get("verdict", "INCONNU")
    except json.JSONDecodeError:
        note_finale = note_markdown
        score = 0.0
        verdict = "ERREUR VÉRIFICATION"

    if verbose:
        print(f"✅ Vérificateur : {verdict} (score={score:.2f})", flush=True)

    disclaimer = (
        "\n\n---\n"
        f"_Note générée par Lucie V1 — "
        f"Score de fiabilité : {score:.0%} — Verdict : {verdict}_\n"
        "_À vérifier par un avocat qualifié avant tout usage professionnel._"
    )
    return note_finale + disclaimer
