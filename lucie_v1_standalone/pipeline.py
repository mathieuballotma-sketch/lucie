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
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING, AsyncIterator, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

from . import dossier_analyzer, document_writer, lecteur, ollama_client, redacteur, retriever, verificateur
from .cache import cache_dry_run_enabled, cache_enabled, get_query_cache
from .config import DIRECT_PARAMS, DOSSIER_TIMEOUT, PIPELINE_TIMEOUT, env_legacy
from .dialogue.article_validator import (
    active_resolver_names,
    extract_article_codes,
    validate_article_refs,
)
from .dialogue.intent_classifier import Intent, classify as classify_intent
from .dialogue.out_of_scope import detect_out_of_scope
from .dialogue.small_talk_handler import handle_or_default as small_talk_reply
from .perf import (
    bind_event_queue,
    current_bucket,
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


# ── Swiss watch (règle 5) — propagation du metadata vérificateur ──────────────
# `_format_final` set ce ContextVar avec {score, citations_ok, citations_invalid,
# verdict} pour que `run()` / `run_stream()` puissent peupler la PipelineResponse
# sans changer la signature des fonctions intermédiaires.
_VERIFICATION_META: "ContextVar[Optional[Dict[str, Any]]]" = ContextVar(
    "_lucie_verification_meta", default=None
)


@dataclass
class PipelineResponse:
    answer: str
    citations: List[str] = field(default_factory=list)
    verifier_score: float = 0.0
    # Counts pour affichage HUD ("X citations vérifiées / Y trouvées")
    # Peuplés uniquement quand la pipeline a appelé le Vérificateur (niveau 2/3).
    citations_ok: int = 0
    citations_invalid: int = 0
    verdict: Optional[str] = None  # "VALIDÉ" | "CORRIGÉ" | "INSUFFISANT" | None
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
    # ── Phase A Cerveau Oiseau — tracking early refusals ──
    # `refused=True` signale qu'un cerveau oiseau a court-circuité le pipeline
    # avant tout appel LLM. `early_validation_triggered` identifie la règle :
    #   - "out_of_scope"    : domaine hors Droit Social
    #   - "article_invalid" : article cité non reconnu par la chaîne de résolveurs
    # `validation_details` porte les métadonnées (domain, codes, duration_ms,
    # resolvers actifs) pour audit/rapport.
    refused: bool = False
    early_validation_triggered: Optional[str] = None
    validation_details: Dict[str, Any] = field(default_factory=dict)

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
    return env_legacy("SPEED_MODEL", "_") or "_"


async def _run_pipeline_cached(
    query: str,
    document_text: Optional[str],
    force: bool,
    verbose: bool,
    memory: "Optional[MemoryStore]",
) -> str:
    """Wrapper cache autour de `_run_pipeline`.

    Bypass cache si :
      - flag BEAUME_CACHE=0 (ou LUCIE_CACHE=0 deprecated)
      - `document_text` fourni (cache non pertinent : doc peut varier)
      - `force=True` (mode démo — on veut le chemin complet)
      - `memory` fourni (l'observation est cachée avec le reste sinon)
    """
    if not cache_enabled() or document_text is not None or force or memory is not None:
        return await _run_pipeline(query, document_text, force, verbose, memory)

    cache = get_query_cache()
    speed_model = env_legacy("SPEED_MODEL", "_") or "_"
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


def _format_exception_for_user(exc: BaseException) -> str:
    """Traduit une exception pipeline en message utilisateur.

    En particulier : un `RuntimeError("Ollama timeout …")` est reformulé en
    message non-technique explicite. Évite qu'une requête longue coupée
    par httpx donne un écran « **Erreur pipeline** : Ollama timeout après
    300s (modèle: gemma4:e4b) » incompréhensible à un avocat.
    """
    msg = str(exc)
    if "Ollama timeout" in msg:
        return (
            "**Lucie prend plus de temps que prévu sur cette question.**\n\n"
            "Réessayez dans un instant. Si le problème persiste, vérifiez "
            "qu'Ollama tourne bien (`ollama serve`) et que le modèle est "
            "chargé.\n"
        )
    return f"**Erreur pipeline** : {msg}"


# Message de demande de précision pour les questions IMPRECISE_LEGAL.
# Court-circuit avant LLM (~50ms) pour éviter les 11s d'un pipeline qui
# finirait par produire "Cette information n'est pas dans mes sources."
_IMPRECISE_LEGAL_REFUSAL = (
    "Pour répondre précisément, j'ai besoin de plus de contexte : "
    "référence d'article (ex. L.1233-3), type de procédure visé, "
    "ou éléments factuels (ancienneté, motif, effectif). "
    "Ma base couvre principalement le licenciement économique pour le moment."
)


async def _run_cerveau_oiseau_gates(
    query: str,
    dossier_path: Optional[str],
) -> Optional[PipelineResponse]:
    """Exécute les 2 gates Cerveau Oiseau (out_of_scope + article_invalid)
    avant tout appel LLM, partagé entre `run()` et `run_stream()`.

    Retourne un `PipelineResponse` de refus si une règle déclenche,
    sinon `None` (passthrough vers le pipeline standard).

    Bypass complet en mode dossier (`dossier_path` non vide) : l'analyse
    dédiée garde la main.

    `validate_article_refs` est wrappé dans `asyncio.to_thread` car il
    touche SQLite Légifrance et ne doit pas bloquer l'event loop pendant
    le streaming. `detect_out_of_scope` reste sync (pure CPU, <5ms).
    """
    if dossier_path:
        return None

    # ── Gate 1 : out-of-scope (<5ms, 0 LLM, pure CPU) ────────────────────
    t0_oos = time.perf_counter()
    oos = detect_out_of_scope(query)
    dt_oos_ms = (time.perf_counter() - t0_oos) * 1000
    if oos is not None:
        emit(
            "cerveau_oiseau",
            "completed",
            hook_name="early_out_of_scope",
            duration_ms=dt_oos_ms,
            domain=oos.domain,
        )
        logger.info(
            "[CerveauOiseau] OUT_OF_SCOPE détecté (domaine=%s) → refus poli (%.0fms)",
            oos.domain,
            dt_oos_ms,
        )
        return PipelineResponse(
            answer=oos.redirection,
            citations=[],
            verifier_score=1.0,
            disclaimer=None,
            mode="analysis",
            refused=True,
            early_validation_triggered="out_of_scope",
            validation_details={
                "domain": oos.domain,
                "duration_ms": round(dt_oos_ms, 2),
            },
        )

    # ── Gate 2 : article inexistant (<50ms, 0 LLM, SQLite via to_thread) ──
    t0_art = time.perf_counter()
    refus_article = await asyncio.to_thread(validate_article_refs, query)
    dt_art_ms = (time.perf_counter() - t0_art) * 1000
    if refus_article is not None:
        codes = extract_article_codes(query)
        displays = [c[2] for c in codes]
        resolvers = active_resolver_names()
        emit(
            "cerveau_oiseau",
            "completed",
            hook_name="early_article_invalid",
            duration_ms=dt_art_ms,
            code=displays[0] if displays else "",
            codes=displays,
            resolvers=resolvers,
        )
        logger.info(
            "[CerveauOiseau] Early validation: %s introuvable "
            "(résolveurs=%s) → refus immédiat (%.0fms)",
            displays[0] if displays else "?",
            ",".join(resolvers),
            dt_art_ms,
        )
        return PipelineResponse(
            answer=refus_article,
            citations=[],
            verifier_score=1.0,
            disclaimer=None,
            mode="analysis",
            refused=True,
            early_validation_triggered="article_invalid",
            validation_details={
                "codes": displays,
                "resolvers": resolvers,
                "duration_ms": round(dt_art_ms, 2),
            },
        )

    return None


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

    # ── Cerveau Oiseau : out-of-scope + article inexistant (0 LLM, <50ms) ──
    early_refusal = await _run_cerveau_oiseau_gates(query, dossier_path)
    if early_refusal is not None:
        return early_refusal

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
            logger.info(
                "[CerveauOiseau] IMPRECISE_LEGAL → refus poli (demande de précision)"
            )
            return PipelineResponse(
                answer=_IMPRECISE_LEGAL_REFUSAL,
                citations=[],
                verifier_score=1.0,
                disclaimer=None,
                mode="analysis",
                refused=True,
                early_validation_triggered="imprecise_legal",
            )

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
    # Reset metadata vérificateur (swiss watch — règle 5)
    _VERIFICATION_META.set(None)
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
        # Surfacer le score vérificateur dans la PipelineResponse (HUD badge)
        meta = _VERIFICATION_META.get()
        if meta is not None:
            response.verifier_score = meta["score"]
            response.citations_ok = meta["citations_ok"]
            response.citations_invalid = meta["citations_invalid"]
            response.verdict = meta["verdict"]

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
        return PipelineResponse(answer=_format_exception_for_user(exc), mode=mode)


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
            "_Note générée par Beaume V1 — à vérifier par un avocat qualifié._"
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
    """P1 : streaming activé par défaut, désactivable via `BEAUME_STREAM=0`.

    Ancien `LUCIE_STREAM` accepté en alias deprecated.
    """
    return env_legacy("STREAM", "1") == "1"


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

    Si `BEAUME_STREAM=0` (ou `LUCIE_STREAM=0` deprecated), bascule automatiquement
    sur `run()` et yield juste la réponse finale en un seul chunk.

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

    # Reset metadata vérificateur (Swiss watch — règle 5)
    _VERIFICATION_META.set(None)

    # ── R3 sprint S1 : TTFT pipeline-side ────────────────────────────────────
    # Mesure le temps entre l'entrée dans run_stream et le 1er chunk de
    # texte émis vers le HUD (incluant routing, scope, retriever pour N2).
    # Borne haute du TTFT — c'est ce que perçoit l'utilisateur.
    t_pipeline_start = time.perf_counter()
    _ttft_recorded = False

    def _mark_pipeline_ttft() -> None:
        nonlocal _ttft_recorded
        if _ttft_recorded:
            return
        _ttft_recorded = True
        bucket = current_bucket()
        if bucket is not None:
            bucket.add(
                "pipeline.ttft",
                (time.perf_counter() - t_pipeline_start) * 1000,
            )

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

    # ── Cerveau Oiseau : out-of-scope + article inexistant (0 LLM, <50ms) ──
    # Court-circuit avant tout LLM. Sans ces gates, run_stream() laissait
    # passer L.1234-999 jusqu'au pipeline complet (~26s observés v0.5.5).
    early_refusal = await _run_cerveau_oiseau_gates(query, dossier_path)
    if early_refusal is not None:
        _mark_pipeline_ttft()
        yield early_refusal
        return

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
        if intent == Intent.IMPRECISE_LEGAL:
            logger.info(
                "[CerveauOiseau] IMPRECISE_LEGAL → refus poli (demande de précision)"
            )
            _mark_pipeline_ttft()
            yield PipelineResponse(
                answer=_IMPRECISE_LEGAL_REFUSAL,
                citations=[],
                verifier_score=1.0,
                disclaimer=None,
                mode="analysis",
                refused=True,
                early_validation_triggered="imprecise_legal",
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
                        _mark_pipeline_ttft()
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
                        _mark_pipeline_ttft()
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
                # Surfacer le score vérificateur (Swiss watch — règle 5)
                meta = _VERIFICATION_META.get()
                if meta is not None:
                    response.verifier_score = meta["score"]
                    response.citations_ok = meta["citations_ok"]
                    response.citations_invalid = meta["citations_invalid"]
                    response.verdict = meta["verdict"]
                yield _attach_suggested_replies(response)
                if memory is not None:
                    await _memory_observe(memory, query, "search", routing["intent"])
        except Exception as exc:  # noqa: BLE001
            yield PipelineResponse(answer=_format_exception_for_user(exc), mode=mode)


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
    """Applique le résultat du vérificateur et ajoute le disclaimer.

    Side-effect (Swiss watch — règle 5) : peuple `_VERIFICATION_META` avec
    `{score, citations_ok, citations_invalid, verdict}` pour que `run()` /
    `run_stream()` puissent surfacer ces infos dans la PipelineResponse
    consommée par le HUD (badge couleur sous chaque réponse).
    """
    citations_ok = 0
    citations_invalid = 0
    try:
        verification = json.loads(verification_json)
        note_finale = verification.get("note_corrigee", note_markdown)
        score = verification.get("score_fiabilite", 1.0)
        verdict = verification.get("verdict", "INCONNU")
        citations_ok = len(verification.get("citations_verifiees", []) or [])
        citations_invalid = len(verification.get("citations_invalides", []) or [])
    except json.JSONDecodeError:
        note_finale = note_markdown
        score = 0.0
        verdict = "ERREUR VÉRIFICATION"

    # Propagation pour la PipelineResponse (lue par run() / run_stream()).
    _VERIFICATION_META.set({
        "score": float(score),
        "citations_ok": int(citations_ok),
        "citations_invalid": int(citations_invalid),
        "verdict": verdict,
    })

    if verbose:
        print(f"✅ Vérificateur : {verdict} (score={score:.2f})", flush=True)

    disclaimer = (
        "\n\n---\n"
        f"_Note générée par Beaume v1 — "
        f"Score de fiabilité : {score:.0%} — Verdict : {verdict}_\n"
        "_À vérifier par un avocat qualifié avant tout usage professionnel._"
    )
    return note_finale + disclaimer
