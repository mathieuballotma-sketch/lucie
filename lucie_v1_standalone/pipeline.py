"""
LegalPipeline — orchestrateur intelligent à 3 niveaux.

Niveaux de traitement :
  1. direct   → 1 appel LLM avec prompt minimaliste (2-3s)
  2. search   → Retriever → Rédacteur → Vérificateur, sans Lecteur (15-20s)
  3. document → Pipeline complet : Lecteur → Retriever → Rédacteur → Vérificateur (30-45s)

Aucune dépendance au reste du repo.

Hooks mémoire (Bloc 1) :
  - run() accepte un MemoryStore optionnel (injection de dépendance)
  - observe() est appelé après chaque traitement réussi
  - recall() est disponible pour enrichissement futur (ProactiveEngine — Bloc 2)
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

from . import dossier_analyzer, document_writer, lecteur, ollama_client, redacteur, retriever, verificateur
from .cache import cache_dry_run_enabled, cache_enabled, get_query_cache
from .config import DIRECT_PARAMS, DOSSIER_TIMEOUT, PIPELINE_TIMEOUT
from .dialogue.intent_classifier import Intent, classify as classify_intent
from .dialogue.out_of_scope import detect_out_of_scope
from .dialogue.small_talk_handler import handle_or_default as small_talk_reply
from .perf import (
    bind_event_queue,
    current_queue,
    drain_nowait,
    emit,
    event_stage,
    profile_bucket,
    profile_step,
)
from .router import is_dossier, route as router_route, validate as router_validate

if TYPE_CHECKING:
    from .memory.store import MemoryStore

_DIRECT_SYSTEM_PATH = Path(__file__).parent / "prompts" / "direct_system.txt"

# Marqueur interne utilisé par le HUD pour transmettre la décision d'une proposition
# (bouton Oui/Non) sans perdre la query originale.
# Format : __decision__:<value>|original=<texte>
_DECISION_MARKER = "__decision__:"

# Verbes/locutions qui déclenchent une proposition de production avant exécution.
_PRODUCTION_VERBS = (
    "rédige", "redige", "rédiger", "rediger",
    "écris", "ecris", "écrire", "ecrire",
    "prépare", "prepare", "préparer", "preparer",
    "produis", "produire",
    "projet de",
    "génère", "genere", "générer", "generer",
    "fais-moi", "fais moi",
)

# Détection heuristique du "kind" (affiché à l'utilisateur + utilisé pour nom de fichier).
_KIND_KEYWORDS: Tuple[Tuple[str, str], ...] = (
    ("mise en demeure", "courrier"),
    ("courrier", "courrier"),
    ("lettre", "courrier"),
    ("email", "courrier"),
    ("assignation", "acte"),
    ("conclusions", "acte"),
    ("acte", "acte"),
    ("synthèse", "synthese"),
    ("synthese", "synthese"),
    ("résumé", "synthese"),
    ("resume", "synthese"),
    ("note", "note"),
    ("analyse", "note"),
    ("consultation", "note"),
)

# Labels humains pour le kind (affichage proposition).
_KIND_LABELS: Dict[str, str] = {
    "courrier": "projet de courrier",
    "acte": "projet d'acte",
    "synthese": "synthèse",
    "note": "note d'analyse",
    "document": "document",
}

# Regex question fermée générique (pour peupler suggested_replies Oui/Non).
_CLOSED_QUESTION_RE = re.compile(
    r"(Voulez-vous|Souhaitez-vous|Dois-je|Confirmez-vous|Puis-je|Faut-il)[^.?!]*\?",
    re.IGNORECASE,
)


@dataclass
class PipelineResponse:
    answer: str
    citations: List[str] = field(default_factory=list)
    verifier_score: float = 0.0
    disclaimer: Optional[str] = None
    mode: Optional[str] = None
    # Indique au HUD qu'un document peut être produit : afficher ProposalCard au lieu
    # de créer automatiquement le fichier. Peuplé par le pipeline quand la requête
    # ressemble à une demande de production (EXPLICIT_ORDER + verbe de production).
    produces_document: bool = False
    document_kind: Optional[str] = None  # "courrier", "acte", "synthese", "note"
    # Boutons à afficher sous la réponse ({"label": ..., "value": ...}).
    suggested_replies: List[Dict[str, str]] = field(default_factory=list)
    # Chemin du DOCX produit (populé uniquement après confirmation utilisateur).
    document_path: Optional[str] = None

    def __str__(self) -> str:
        return self.answer


# ─── Helpers proposition / décision ──────────────────────────────────────────

def _extract_decision(query: str) -> Tuple[Optional[str], str]:
    """Si la query commence par un marqueur de décision, renvoie (value, original).
    Sinon (None, query inchangée)."""
    if not query.startswith(_DECISION_MARKER):
        return None, query
    payload = query[len(_DECISION_MARKER):]
    if "|original=" in payload:
        value, original = payload.split("|original=", 1)
        return value.strip(), original.strip()
    return payload.strip(), ""


def _detect_production_request(query: str) -> Optional[str]:
    """Si la requête ressemble à une demande de production, renvoie le kind détecté.
    Sinon None. Appelée uniquement pour Intent.EXPLICIT_ORDER."""
    q = query.lower()
    if not any(verb in q for verb in _PRODUCTION_VERBS):
        return None
    for keyword, kind in _KIND_KEYWORDS:
        if keyword in q:
            return kind
    return "document"


def _build_proposition(query: str, kind: str) -> PipelineResponse:
    """Construit une PipelineResponse de type proposition (sans exécuter le pipeline)."""
    kind_label = _KIND_LABELS.get(kind, "document")
    article = "ce" if kind_label.startswith(("projet", "document")) else "cette"
    answer = (
        f"Je peux vous préparer {article} {kind_label}. "
        "Voulez-vous que je le produise ?"
    )
    return PipelineResponse(
        answer=answer,
        citations=[],
        verifier_score=1.0,
        disclaimer=None,
        mode="proposition",
        produces_document=True,
        document_kind=kind,
        suggested_replies=[
            {"label": "Oui, produire", "value": "yes_produce"},
            {"label": "Non, répondre directement", "value": "no_text"},
        ],
    )


def _current_index_version() -> str:
    """Version de la base Légifrance utilisée comme partie de la clé de cache.

    On prend la mtime du fichier `legi.sqlite` — change à chaque sync. Si la
    base est absente ou inaccessible, on retombe sur le nom du speed model
    (évite qu'un swap modèle invalide les caches sans changer la base).
    """
    try:
        from .retriever import get_legifrance_db_path

        db_path = get_legifrance_db_path()
        if db_path and Path(db_path).exists():
            return f"{int(Path(db_path).stat().st_mtime)}"
    except Exception:
        pass
    return os.environ.get("LUCIE_SPEED_MODEL", "_")


async def _run_pipeline_cached(
    query: str,
    document_text: Optional[str],
    force: bool,
    verbose: bool,
    memory: "Optional[MemoryStore]",
) -> str:
    """Wrapper cache autour de `_run_pipeline`.

    Bypass cache si :
      - flag LUCIE_CACHE=0
      - `document_text` fourni (cache non pertinent : doc peut varier)
      - `force=True` (mode démo — on veut le chemin complet)
      - `memory` fourni (l'observation est cachée avec le reste sinon)
    """
    if not cache_enabled() or document_text is not None or force or memory is not None:
        return await _run_pipeline(query, document_text, force, verbose, memory)

    cache = get_query_cache()
    speed_model = os.environ.get("LUCIE_SPEED_MODEL", "_")
    key = cache.make_key(
        query=query,
        index_version=f"{_current_index_version()}|{speed_model}",
    )
    dry_run = cache_dry_run_enabled()

    async def compute() -> str:
        return await _run_pipeline(query, document_text, force, verbose, memory)

    return await cache.get_or_compute(key, compute, dry_run=dry_run)


def _attach_suggested_replies(response: PipelineResponse) -> PipelineResponse:
    """Détecte une question fermée dans l'answer et ajoute des boutons Oui/Non génériques."""
    if response.suggested_replies:
        return response  # déjà peuplé (proposition)
    if _CLOSED_QUESTION_RE.search(response.answer or ""):
        response.suggested_replies = [
            {"label": "Oui", "value": "yes"},
            {"label": "Non", "value": "no"},
        ]
    return response


async def run(
    query: str,
    document_text: Optional[str] = None,
    dossier_path: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
    memory: "Optional[MemoryStore]" = None,
) -> PipelineResponse:
    """
    Exécute le pipeline au niveau approprié avec timeout global.

    Args:
        query: Requête de l'utilisateur.
        document_text: Texte du document à analyser (optionnel).
        dossier_path: Chemin vers un dossier complet (optionnel).
        force: Force le mode search sans routing (pour les démos).
        verbose: Affiche les étapes dans le terminal.
        memory: MemoryStore optionnel (injection de dépendance). Si fourni,
                chaque traitement enregistre une observation silencieuse.

    Returns:
        PipelineResponse avec answer, citations, verifier_score, disclaimer, mode.
    """
    # ── Marqueur de décision utilisateur (boutons Oui/Non du HUD) ───────────
    # Le HUD préfixe la query avec __decision__:<value>|original=<query>
    # quand l'utilisateur a cliqué sur un bouton suggéré.
    decision, original_query = _extract_decision(query)
    if decision is not None:
        # Si la décision est un "non" explicite, on répond en texte court
        # sans relancer le pipeline complet.
        if decision in ("no", "no_text"):
            return PipelineResponse(
                answer=(
                    "Entendu — je reste à votre disposition. "
                    "N'hésitez pas à reformuler ou à préciser votre demande."
                ),
                mode="action" if decision == "no_text" else "analysis",
            )
        # Décision "yes" / "yes_produce" : on reprend la query originale
        # et on court-circuite la détection de proposition (sinon boucle infinie).
        query = original_query or query

    # ── Early refus hors-scope (< 5ms, 0 LLM) ─────────────────────────────
    # Si la query évoque un domaine hors Droit Social (fiscal, immobilier,
    # pénal, consommation, famille) sans cocher l'override CT, on refuse
    # poliment avec redirection. Bypass dossier mode (analyse dédiée).
    if not dossier_path:
        oos = detect_out_of_scope(query)
        if oos is not None:
            logger.info(
                "[OutOfScope] query=%r → refus domaine=%s",
                query[:60],
                oos.domain,
            )
            return PipelineResponse(
                answer=oos.redirection,
                citations=[],
                verifier_score=1.0,
                disclaimer=None,
                mode="analysis",
            )

    # ── Intent routing (< 1ms, 0 LLM) — bypass dossier mode ─────────────────
    if not dossier_path:
        intent = classify_intent(query)
        logger.info(
            "[Routage] query=%r → intent=%s → handler=%s",
            query[:60],
            intent.value,
            "small_talk_handler" if intent == Intent.SMALL_TALK else "pipeline",
        )

        if intent == Intent.SMALL_TALK:
            return PipelineResponse(
                answer=small_talk_reply(query),
                citations=[],
                verifier_score=1.0,
                disclaimer=None,
            )

        if intent == Intent.IMPRECISE_LEGAL:
            # TODO: DialogueManager wiring v1.1 — pour l'instant fallthrough
            print("TODO: DialogueManager wiring v1.1", flush=True)

        # ── Proposition avant production ────────────────────────────────────
        # Si l'utilisateur demande une production (rédige, projet de…) ET qu'il
        # n'a pas déjà dit "oui" via le bouton, on propose au lieu d'exécuter.
        if intent == Intent.EXPLICIT_ORDER and decision is None:
            kind = _detect_production_request(query)
            if kind is not None:
                return _build_proposition(query, kind)

        mode = "action" if intent == Intent.EXPLICIT_ORDER else "analysis"
    else:
        mode = "analysis"

    # ── Mode dossier : pipeline dédié avec timeout étendu ────────────────────
    if dossier_path and is_dossier(dossier_path):
        result = await _run_dossier(query, dossier_path, force, verbose)
        return _attach_suggested_replies(PipelineResponse(answer=result, mode=mode))

    # ── Pipeline standard avec timeout global ─────────────────────────────────
    start = time.time()
    if verbose:
        print(f"⚖️  Pipeline démarré — {query[:80]}…", flush=True)
    try:
        async with profile_bucket():
            result = await asyncio.wait_for(
                _run_pipeline_cached(query, document_text, force, verbose, memory),
                timeout=PIPELINE_TIMEOUT,
            )
        elapsed = time.time() - start
        if verbose:
            print(f"⚖️  Pipeline terminé en {elapsed:.1f}s", flush=True)

        response = PipelineResponse(answer=result, mode=mode)

        # Si l'utilisateur a confirmé "yes_produce", on écrit un DOCX et on
        # expose le chemin au HUD (qui l'affichera dans une DraggableFileCard).
        if decision == "yes_produce":
            try:
                kind = _detect_production_request(original_query or query) or "document"
                docx_path = document_writer.write_docx(result, kind)
                response.document_path = str(docx_path)
                response.document_kind = kind
            except Exception as exc:
                if verbose:
                    print(f"⚠️  DOCX non produit : {exc}", flush=True)

        return _attach_suggested_replies(response)
    except asyncio.TimeoutError:
        elapsed = time.time() - start
        return PipelineResponse(
            answer=(
                f"**Erreur** : le pipeline a dépassé le timeout de "
                f"{PIPELINE_TIMEOUT:.0f}s après {elapsed:.1f}s. "
                "Réessayez ou réduisez la taille du document."
            ),
            mode=mode,
        )
    except Exception as exc:
        return PipelineResponse(answer=f"**Erreur pipeline** : {exc}", mode=mode)


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
    memory: "Optional[MemoryStore]" = None,
) -> str:

    # ── Vérification du scope (< 1ms) ─────────────────────────────────────────
    async with profile_step("router.validate"):
        if not force:
            scope = router_validate(query, document_text)
            if not scope["valid"]:
                return str(scope["refusal_reason"])

    # ── Routage (< 1ms) ───────────────────────────────────────────────────────
    async with profile_step("router.route"):
        routing = router_route(query, document_text, force=force)
    level = routing["level"]

    if verbose:
        print(f"🔀 Router → niveau {level} ({routing['intent']})", flush=True)

    # ── Niveau 1 : Réponse directe ────────────────────────────────────────────
    if level == "direct":
        async with profile_step("level.direct"):
            result = await _direct_response(query, verbose)
        if memory is not None:
            await _memory_observe(memory, query, "direct", routing["intent"])
        return result

    # ── Niveau 2 : Recherche juridique (sans document) ────────────────────────
    if level == "search":
        faits_json = json.dumps(
            {"type_document": "requete", "query": query},
            ensure_ascii=False,
        )
        async with profile_step("level.search"):
            result = await _search_and_write(query, faits_json, verbose)
        if memory is not None:
            await _memory_observe(memory, query, "search", routing["intent"])
        return result

    # ── Niveau 3 : Pipeline complet (avec document) ───────────────────────────
    # level == "document"
    doc = routing.get("document") or document_text
    async with profile_step("level.full"):
        result = await _full_pipeline(query, doc, verbose)
    if memory is not None:
        await _memory_observe(memory, query, "document", routing["intent"])
    return result


# ─── Niveau 1 ─────────────────────────────────────────────────────────────────

async def _direct_response(query: str, verbose: bool) -> str:
    """Réponse directe sans pipeline — prompt minimaliste, ~2-3s."""
    if verbose:
        print("💬 Réponse directe…", flush=True)

    system = _DIRECT_SYSTEM_PATH.read_text(encoding="utf-8")
    options = {k: v for k, v in DIRECT_PARAMS.items() if k != "model"}

    async with profile_step("llm.direct"):
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
    async with profile_step("retriever.search"), event_stage("retriever"):
        sources_json = await retriever.handle(faits_json)
    if verbose:
        print("✅ Retriever : sources récupérées", flush=True)

    # Rédacteur (mode search : prompt dédié)
    if verbose:
        print("✍️  Rédacteur : rédaction de la réponse…", flush=True)
    async with profile_step("llm.redacteur.search"), event_stage("redacteur"):
        note_markdown = await redacteur.handle(faits_json, sources_json, mode="search")

    if note_markdown.startswith("**RÉDACTION IMPOSSIBLE**"):
        # Pas de sources → réponse directe de secours
        return await _direct_response(query, verbose)

    if verbose:
        print("✅ Rédacteur : réponse rédigée", flush=True)

    # Vérificateur
    if verbose:
        print("🔎 Vérificateur : contrôle des citations…", flush=True)
    async with profile_step("verificateur.search"), event_stage("verificateur"):
        verification_json = await verificateur.handle(note_markdown, sources_json)

    return _format_final(note_markdown, verification_json, verbose)


# ─── Niveau 3 ─────────────────────────────────────────────────────────────────

async def _full_pipeline(query: str, doc: Optional[str], verbose: bool) -> str:
    """Pipeline complet avec Lecteur — ~30-45s."""

    # Lecteur
    if verbose:
        print("📄 Lecteur : extraction des faits…", flush=True)
    async with profile_step("llm.lecteur"), event_stage("lecteur"):
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
    async with profile_step("retriever.full"), event_stage("retriever"):
        sources_json = await retriever.handle(faits_json)
    if verbose:
        print("✅ Retriever : sources récupérées", flush=True)

    # Rédacteur (mode document : prompt formel complet)
    if verbose:
        print("✍️  Rédacteur : rédaction de la note…", flush=True)
    async with profile_step("llm.redacteur.full"), event_stage("redacteur"):
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
    async with profile_step("verificateur.full"), event_stage("verificateur"):
        verification_json = await verificateur.handle(note_markdown, sources_json)

    return _format_final(note_markdown, verification_json, verbose)


# ─── Streaming (P1) ──────────────────────────────────────────────────────────


def streaming_enabled() -> bool:
    """P1 : streaming activé par défaut, désactivable via `LUCIE_STREAM=0`."""
    return os.environ.get("LUCIE_STREAM", "1") == "1"


async def run_stream(
    query: str,
    document_text: Optional[str] = None,
    dossier_path: Optional[str] = None,
    force: bool = False,
    memory: "Optional[MemoryStore]" = None,
) -> AsyncIterator[Union[str, PipelineResponse]]:
    """Version streaming de `run` : yield des chunks de tokens au fil de l'eau,
    puis termine par un `PipelineResponse` final (avec `answer` complet).

    Pour N1 (direct) et N2 (search), le Rédacteur streame en direct. Pour N3
    (full pipeline avec document) ou dossier, pas de streaming intermédiaire —
    on yield la réponse complète d'un coup à la fin (compat).

    Si `LUCIE_STREAM=0`, bascule automatiquement sur `run()` et yield juste
    la réponse finale en un seul chunk.

    Usage HUD :
        buffer = []
        async for event in run_stream(query):
            if isinstance(event, str):
                append_token(event)   # affichage UI
                buffer.append(event)
            else:  # PipelineResponse final
                final = event
    """
    if not streaming_enabled():
        resp = await run(query, document_text, dossier_path, force, False, memory)
        yield resp
        return

    # ── Marqueur décision utilisateur ───────────────────────────────────────
    decision, original_query = _extract_decision(query)
    if decision is not None:
        if decision in ("no", "no_text"):
            yield PipelineResponse(
                answer=(
                    "Entendu — je reste à votre disposition. "
                    "N'hésitez pas à reformuler ou à préciser votre demande."
                ),
                mode="action" if decision == "no_text" else "analysis",
            )
            return
        query = original_query or query

    # ── Intent routing ──────────────────────────────────────────────────────
    if not dossier_path:
        intent = classify_intent(query)
        if intent == Intent.SMALL_TALK:
            yield PipelineResponse(
                answer=small_talk_reply(query),
                citations=[],
                verifier_score=1.0,
            )
            return
        if intent == Intent.EXPLICIT_ORDER and decision is None:
            kind = _detect_production_request(query)
            if kind is not None:
                yield _build_proposition(query, kind)
                return
        mode = "action" if intent == Intent.EXPLICIT_ORDER else "analysis"
    else:
        mode = "analysis"

    # ── Bind event queue pour toute la durée du run ─────────────────────────
    async with bind_event_queue() as evq:

        # ── Mode dossier : pas de streaming natif — fallback run() ──────────
        if dossier_path and is_dossier(dossier_path):
            async for ev in _run_with_event_drain(
                lambda: run(query, document_text, dossier_path, force, False, memory),
                evq,
            ):
                yield ev
            return

        # ── Scope / routage (0 LLM) ─────────────────────────────────────────
        try:
            async with profile_bucket():
                if not force:
                    scope = router_validate(query, document_text)
                    if not scope["valid"]:
                        yield PipelineResponse(answer=str(scope["refusal_reason"]), mode=mode)
                        return

                routing = router_route(query, document_text, force=force)
                level = routing["level"]

                # N3 : pas de streaming natif — lancer run() en task, drainer events
                if level == "document":
                    async for ev in _run_with_event_drain(
                        lambda: run(query, document_text, dossier_path, force, False, memory),
                        evq,
                    ):
                        yield ev
                    return

                # ── N1 direct : stream du direct_response, pas d'events (2-3s) ──
                if level == "direct":
                    system = _DIRECT_SYSTEM_PATH.read_text(encoding="utf-8")
                    options = {k: v for k, v in DIRECT_PARAMS.items() if k != "model"}
                    chunks: List[str] = []
                    async for chunk in ollama_client.generate_stream(
                        model=DIRECT_PARAMS["model"],
                        prompt=query,
                        system=system,
                        options=options,
                    ):
                        chunks.append(chunk)
                        yield chunk
                    full = "".join(chunks)
                    response = PipelineResponse(answer=full, mode=mode)
                    yield _attach_suggested_replies(response)
                    if memory is not None:
                        await _memory_observe(memory, query, "direct", routing["intent"])
                    return

                # ── N2 search : retriever → rédacteur stream → verif ────────
                # Emit events manuels (plutôt que event_stage context) pour
                # garantir que "started" sort AVANT l'await — la ligne bleue
                # pulse pendant que l'étape travaille.
                faits_json = json.dumps(
                    {"type_document": "requete", "query": query},
                    ensure_ascii=False,
                )

                # --- Retriever
                t_r = time.perf_counter()
                emit("retriever", "started", details={"level": "search"})
                for ev in drain_nowait(evq):
                    yield ev
                try:
                    sources_json = await retriever.handle(faits_json)
                except Exception as exc:  # noqa: BLE001
                    emit(
                        "retriever",
                        "error",
                        str(exc) or type(exc).__name__,
                        duration_ms=(time.perf_counter() - t_r) * 1000,
                    )
                    for ev in drain_nowait(evq):
                        yield ev
                    raise
                emit(
                    "retriever",
                    "completed",
                    duration_ms=(time.perf_counter() - t_r) * 1000,
                )
                for ev in drain_nowait(evq):
                    yield ev

                # --- Rédacteur (streaming)
                t_d = time.perf_counter()
                emit("redacteur", "started", details={"level": "search"})
                for ev in drain_nowait(evq):
                    yield ev
                chunks = []
                try:
                    async for chunk in redacteur.handle_stream(
                        faits_json, sources_json, mode="search"
                    ):
                        chunks.append(chunk)
                        yield chunk
                except Exception as exc:  # noqa: BLE001
                    emit(
                        "redacteur",
                        "error",
                        str(exc) or type(exc).__name__,
                        duration_ms=(time.perf_counter() - t_d) * 1000,
                    )
                    for ev in drain_nowait(evq):
                        yield ev
                    raise
                emit(
                    "redacteur",
                    "completed",
                    duration_ms=(time.perf_counter() - t_d) * 1000,
                )
                for ev in drain_nowait(evq):
                    yield ev
                note_markdown = "".join(chunks)

                # --- Vérificateur
                t_v = time.perf_counter()
                emit("verificateur", "started")
                for ev in drain_nowait(evq):
                    yield ev
                try:
                    verification_json = await verificateur.handle(note_markdown, sources_json)
                except Exception as exc:  # noqa: BLE001
                    emit(
                        "verificateur",
                        "error",
                        str(exc) or type(exc).__name__,
                        duration_ms=(time.perf_counter() - t_v) * 1000,
                    )
                    for ev in drain_nowait(evq):
                        yield ev
                    raise
                emit(
                    "verificateur",
                    "completed",
                    duration_ms=(time.perf_counter() - t_v) * 1000,
                )
                for ev in drain_nowait(evq):
                    yield ev

                final = _format_final(note_markdown, verification_json, False)
                response = PipelineResponse(answer=final, mode=mode)
                yield _attach_suggested_replies(response)
                if memory is not None:
                    await _memory_observe(memory, query, "search", routing["intent"])
        except Exception as exc:  # noqa: BLE001
            yield PipelineResponse(answer=f"**Erreur pipeline** : {exc}", mode=mode)


async def _run_with_event_drain(
    coro_factory,
    evq,
) -> AsyncIterator[Union[str, PipelineResponse]]:
    """Lance `coro_factory()` comme task et yield les events poussés dans `evq`
    au fur et à mesure qu'ils arrivent. Termine par yield de la réponse finale
    (PipelineResponse retournée par la coro).

    Pattern utilisé pour les chemins bloquants (Level 3 document, mode dossier)
    où on n'a pas de token streaming à yield entre les events.
    """
    task = asyncio.create_task(coro_factory())
    try:
        while not task.done():
            try:
                ev = await asyncio.wait_for(evq.get(), timeout=0.1)
                yield ev
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:  # noqa: PERF203
                raise
        # Drain ce qui reste après la fin de la task
        for ev in drain_nowait(evq):
            yield ev
        resp = await task
        yield resp
    finally:
        if not task.done():
            task.cancel()


# ─── Helpers mémoire ─────────────────────────────────────────────────────────

async def _memory_observe(
    memory: "MemoryStore",
    query: str,
    level: str,
    intent: str,
) -> None:
    """Enregistre silencieusement une observation dans MemoryStore."""
    try:
        await memory.observe({
            "query": query,
            "source": f"pipeline/{level}",
            "node_type": "pattern",
            "intent": intent,
        })
    except Exception:
        pass  # La mémoire est silencieuse — un échec ne bloque jamais le pipeline


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
