"""
LegalPipeline — orchestrateur linéaire du pipeline V1 droit social.

Flux : Router → Lecteur → Retriever → Rédacteur → Vérificateur

Aucune dépendance au reste du repo.
"""

import asyncio
import json
import time
from typing import Optional

from . import dossier_analyzer, lecteur, redacteur, retriever, verificateur
from .config import DOSSIER_TIMEOUT, PIPELINE_TIMEOUT
from .router import is_dossier, validate as router_validate


async def run(
    query: str,
    document_text: Optional[str] = None,
    dossier_path: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> str:
    """
    Exécute le pipeline complet avec timeout global.

    Args:
        query: Requête de l'avocat.
        document_text: Texte du document à analyser (optionnel).
        dossier_path: Chemin vers un dossier complet (optionnel).
        force: Bypass le filtrage du Router (pour les démos).
        verbose: Affiche les étapes dans le terminal.

    Returns:
        Note finale validée en Markdown, ou message de refus/erreur.
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

    # ── Étape 1 : Router (< 10ms) ─────────────────────────────────────────────
    routing = router_validate(query, document_text, force=force)
    if not routing["valid"]:
        if verbose:
            print(f"❌ Router : refus — {routing['refusal_reason'][:60]}…", flush=True)
        return str(routing["refusal_reason"])

    doc = routing.get("document") or document_text
    if verbose:
        print("✅ Router : scope validé", flush=True)

    # ── Étape 2 : Lecteur (~3-5s) — uniquement si un document est fourni ──────
    if doc:
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
            pass  # JSON mal formé mais on continue

        if verbose:
            print("✅ Lecteur : faits extraits", flush=True)
    else:
        # Mode question pure — pas de document à analyser
        faits_json = json.dumps({"type_document": "requete", "query": query}, ensure_ascii=False)
        if verbose:
            print("ℹ️  Lecteur : mode requête (sans document)", flush=True)

    # ── Étape 3 : Retriever (~2-4s) ───────────────────────────────────────────
    if verbose:
        print("🔍 Retriever : recherche dans la base curatée…", flush=True)
    sources_json = await retriever.handle(faits_json)
    if verbose:
        print("✅ Retriever : sources récupérées", flush=True)

    # ── Étape 4 : Rédacteur (~8-15s) ──────────────────────────────────────────
    if verbose:
        print("✍️  Rédacteur : rédaction de la note…", flush=True)
    note_markdown = await redacteur.handle(faits_json, sources_json)

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

    # ── Étape 5 : Vérificateur (~2-3s) ────────────────────────────────────────
    if verbose:
        print("🔎 Vérificateur : contrôle des citations…", flush=True)
    verification_json = await verificateur.handle(note_markdown, sources_json)

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

    # ── Réponse finale ────────────────────────────────────────────────────────
    disclaimer = (
        "\n\n---\n"
        f"_Note générée par Lucie V1 — "
        f"Score de fiabilité : {score:.0%} — Verdict : {verdict}_\n"
        "_À vérifier par un avocat qualifié avant tout usage professionnel._"
    )
    return note_finale + disclaimer
