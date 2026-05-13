"""
RetrieverAgent — cherche dans la base curatée locale, avec fallback Légifrance.

Stratégie de recherche :
  0. (optionnel) Si `LEGIFRANCE_ENABLED` et base présente : tenter
     `LegifranceRetriever.search()` restreint aux thèmes détectés.
  1. Matching exact sur les références légales (L.1233-x) dans la base curatée
  2. Ranking BM25 simplifié sur le contenu des fichiers .md
  3. 5 sources max retournées au Rédacteur

Le contrat JSON de sortie est inchangé (`sources`, `jurisprudences`,
`non_trouve`) → pas de régression du Rédacteur / Vérificateur.
"""

import json
import logging
import math
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set

from .config import (
    BM25_B,
    BM25_K1,
    KNOWLEDGE_BASE_PATH,
    LEGIFRANCE_ENABLED,
    MAX_SOURCES,
    get_legifrance_db_path,
)
from .perf.events import emit

logger = logging.getLogger(__name__)

_LEGAL_REF_RE = re.compile(r'L\.?\s*\d{4}(?:-\d+)?', re.IGNORECASE)

# Index en mémoire (lazy, invalidable)
_index: Optional[List[Dict[str, Any]]] = None


def _build_index() -> List[Dict[str, Any]]:
    """Indexe tous les fichiers .md de la base curatée."""
    index = []
    if not KNOWLEDGE_BASE_PATH.exists():
        return index
    for path in sorted(KNOWLEDGE_BASE_PATH.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
            tokens = re.findall(r'\w+', content.lower())
            index.append({
                "id": path.stem,
                "path": str(path),
                "content": content,
                "tokens": tokens,
                "tokens_set": set(tokens),
            })
        except (UnicodeDecodeError, OSError) as exc:
            # Audit 2026-05-12 P0 #2 : un .md corrompu de la KB disparaissait
            # sans trace de l'index. Skip volontaire (continue) — un fichier
            # illisible ne doit pas bloquer toute la KB. Le log warning permet
            # au curateur KB de savoir qu'une curation manuelle est due.
            logger.warning("KB file unreadable: %s (%s)", path, exc)
            continue
    return index


def get_index() -> List[Dict[str, Any]]:
    global _index
    if _index is None:
        _index = _build_index()
    return _index


def invalidate_index() -> None:
    """Force le rechargement de l'index (utile après ajout de fichiers)."""
    global _index
    _index = None


def _bm25_score(
    query_tokens: List[str],
    doc_tokens: List[str],
    avg_dl: float,
    N: int,
    index: List[Dict[str, Any]],
) -> float:
    dl = len(doc_tokens)
    tf_map: Dict[str, int] = Counter(doc_tokens)
    score = 0.0
    for qt in query_tokens:
        tf = tf_map.get(qt, 0)
        if tf == 0:
            continue
        df = sum(1 for d in index if qt in d["tokens_set"])
        idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
        numerator = tf * (BM25_K1 + 1)
        denominator = tf + BM25_K1 * (1 - BM25_B + BM25_B * dl / max(avg_dl, 1))
        score += idf * numerator / denominator
    return score


def _extract_legal_refs(text: str) -> List[str]:
    """Extrait les références légales type L1233-2 ou L.1233-2.

    Normalise vers la forme canonique L.NNNN-N (avec point)
    pour correspondre aux noms de fichiers knowledge/L.1233-X.md.
    """
    raw = _LEGAL_REF_RE.findall(text)
    normalized = []
    for r in raw:
        n = re.sub(r'\s+', '', r).upper()
        if re.match(r'^L\d', n):
            n = 'L.' + n[1:]
        normalized.append(n)
    return normalized


def _extract_title(content: str, default_id: str) -> str:
    m = re.search(r'^#\s+(.+)', content, re.MULTILINE)
    return m.group(1).strip() if m else default_id


def _extract_snippet(content: str, keyword: str, max_len: int = 300) -> str:
    if not keyword:
        return content[:max_len].strip()
    idx = content.lower().find(keyword.lower())
    if idx == -1:
        return content[:max_len].strip()
    start = max(0, idx - 100)
    end = min(len(content), start + max_len)
    snippet = content[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(content):
        snippet += "…"
    return snippet


def _extract_query_or_raw(faits_json: str) -> str:
    """Extrait le champ ``query`` du JSON wrapper produit par ``pipeline.py``.

    POURQUOI : le pipeline niveau 2 (search) emballe la query utilisateur dans
    ``{"type_document": "requete", "query": "..."}`` (cf. ``pipeline.py:692-695``)
    avant d'appeler ``retriever.handle``. Le retriever (curaté + Légifrance)
    tokenise alors sur le JSON entier — les tokens parasites ``type_document``,
    ``requete``, ``query`` polluent BM25/FTS5 et écrasent la pertinence des
    vrais termes (mesuré empiriquement Sprint 6 P2d-B : SW-LECO-006 ramène
    L.1233-24-4/R.1233-18 AVEC wrapper, mais L.1233-61/L.1233-63 SANS wrapper).

    Cette fonction est défensive : si ``faits_json`` n'est pas un dict JSON ou
    n'a pas de clé ``query`` non vide, on renvoie l'entrée inchangée → aucune
    régression sur les chemins qui passent déjà du texte brut (lecteur en mode
    document, tests unitaires, etc.).

    Args:
        faits_json: chaîne JSON ou texte brut.

    Returns:
        Le champ ``query`` si dict avec ``query`` (str non vide) ; sinon
        ``faits_json`` inchangé.
    """
    try:
        parsed = json.loads(faits_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return faits_json
    if isinstance(parsed, dict):
        q = parsed.get("query")
        if isinstance(q, str) and q.strip():
            return q
    return faits_json


def _try_legifrance(faits_json: str, top_k: int) -> Optional[Dict[str, Any]]:
    """
    Tente une recherche Légifrance. Renvoie le dict JSON parsé ou None si
    feature désactivée / base absente / erreur.

    Loggue mais n'élève jamais — l'appelant fallback sur la base curatée.
    """
    if not LEGIFRANCE_ENABLED:
        return None
    try:
        db_path = get_legifrance_db_path()
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_legifrance_db_path a échoué : %s", exc)
        return None
    if not db_path.exists():
        logger.debug("Légifrance activé mais base absente : %s", db_path)
        return None
    try:
        from .knowledge_legifrance.retriever import LegifranceRetriever
        from .dialogue.intent_classifier import detect_themes_with_scores
    except ImportError as exc:
        logger.warning("Légifrance importable mais pas installé : %s", exc)
        return None
    try:
        # Sprint 6 P2d-B — extraction de la query nue avant tokenisation BM25/FTS5.
        # Le pipeline (level 2 = search) emballe la query dans un JSON wrapper
        # ``{"type_document": "requete", "query": "..."}`` ; passer ce JSON
        # entier à `LegifranceRetriever.handle` pollue le FTS5 avec les tokens
        # parasites ``type_document/requete/query`` (mesuré : rate L.1233-61
        # sur SW-LECO-006). Fallback gracieux si le format n'est pas le wrapper.
        query = _extract_query_or_raw(faits_json)

        # Sprint 6 P2a — B-5 sol 1 : si la détection thématique est incertaine
        # (0 thème OU max ≤ 1 keyword match), on débride le FTS5 — sinon le
        # retriever rate des articles hors-thème (ex : ECO_03 « indemnité »
        # restreint au thème licenciement_eco mais cible L.1234-9 hors-scope).
        # Rollback : `BEAUME_RETRIEVER_DEBRIDE=0`.
        scored = detect_themes_with_scores(query)
        max_hits = max((h for _, h in scored), default=0)
        debride = (
            os.environ.get("BEAUME_RETRIEVER_DEBRIDE", "1") == "1"
            and (not scored or max_hits <= 1)
        )
        if debride:
            themes = None
        else:
            themes = [t for t, _ in scored] or None
        with LegifranceRetriever(db_path) as retriever:
            payload = retriever.handle(query, themes=themes, top_k=top_k)
        return json.loads(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Légifrance retriever a échoué (%s), fallback curaté", exc)
        return None


# Seuil empirique de "match fort" pour la KB curatée. Mesuré sur SW-LECO-004
# (query "Quels sont les critères d'ordre…") où L.1233-4 obtient un score BM25
# normalisé ≥ 0.6 alors que les articles Légifrance hors-cible (L.1233-10/31/24-2)
# plafonnent à 0.95 mais sur des termes génériques ("licenciement économique").
# Sous ce seuil, la curatée est traitée comme "complément" (rang après Légifrance) ;
# au-dessus, elle est "prioritaire" (passe devant Légifrance).
CURATED_STRONG_MATCH_THRESHOLD = 0.6

# Bonus de pertinence par token de la query trouvé dans le titre d'un article
# curaté. POURQUOI : BM25 pur défavorise les articles courts (ex : L.1233-9
# "La lettre de licenciement comporte l'énoncé des motifs économiques" — 1
# phrase) face à des articles longs hors-cible (ex : L.1233-12 "grands
# licenciements" qui répète "licenciement" sur 200 mots). Or pour SW-LECO-007
# (« Quelles mentions sont obligatoires dans une lettre de licenciement
# économique ? »), les tokens "mention" et "lettre" matchent exactement le
# titre "Mention du motif économique dans la lettre" — un signal très fort
# qu'on perdait sans ce bonus. Mesuré : 0.15/token rétablit L.1233-9 en tête
# (3 matches → +0.45) sans bouger les articles déjà bien classés.
CURATED_TITLE_TOKEN_BONUS = 0.15
CURATED_TITLE_BONUS_MAX = 0.6


def _title_match_bonus(query_tokens: List[str], doc_title: str) -> float:
    """Calcule un bonus de pertinence basé sur les tokens query trouvés dans le titre.

    Le titre d'un article curaté reflète son sujet central — un match titre est
    un signal de pertinence plus fort que la fréquence des tokens dans le corps.

    Args:
        query_tokens: tokens de la query déjà filtrés (len > 3, lowercase).
        doc_title: titre brut de l'article (ex : "Article L.1233-9 — Mention…").

    Returns:
        Bonus ∈ [0, CURATED_TITLE_BONUS_MAX], proportionnel au nombre de
        tokens query distincts trouvés dans les tokens du titre.
    """
    title_tokens = set(re.findall(r'\w+', doc_title.lower()))
    matches = sum(1 for qt in set(query_tokens) if qt in title_tokens)
    return min(CURATED_TITLE_BONUS_MAX, matches * CURATED_TITLE_TOKEN_BONUS)


def _normalize_article_id(article_id: str) -> str:
    """Normalise un identifiant d'article pour la dédup cross-sources.

    POURQUOI : la KB curatée utilise ``L1233-4`` (stem du .md), Légifrance peut
    renvoyer ``L1233-4``, ``L.1233-4`` ou ``L1233-04``. La dédup naïve par
    chaîne brute laisse passer des doublons et fait perdre des slots dans
    ``MAX_SOURCES``. On normalise en supprimant ponctuation et leading zeros.

    Args:
        article_id: identifiant brut (curatée ou Légifrance).

    Returns:
        Forme canonique en lowercase sans ponctuation ni zéros initiaux.
    """
    base = re.sub(r'[.\-_\s]', '', article_id.lower())
    # Supprime les leading zeros entre 'l' et le premier non-zéro (l01233 → l1233)
    return re.sub(r'^(l|r)0+', r'\1', base)


def _retrieve_curated(
    query_text: str,
    legal_refs: List[str],
    query_tokens: List[str],
) -> List[Dict[str, Any]]:
    """Recherche dans la base curatée locale (matching exact + BM25).

    POURQUOI séparé de ``handle()`` : Sprint 6 P3 a transformé l'early-return
    Légifrance en merge curatée+Légifrance. Le retrieval curatée doit être
    appelable indépendamment pour permettre cette fusion. Le code BM25 +
    matching exact extrait de l'ancien ``handle()`` reste inchangé pour ne
    pas casser le scoring déjà validé Sprint 6 P2.

    Returns:
        Liste de sources curatées triées (matching exact d'abord, puis BM25
        décroissant), avec ``pertinence`` normalisée 0..1.
    """
    index = get_index()
    if not index:
        return []

    sources: List[Dict[str, Any]] = []
    already_ids: Set[str] = set()

    # ── Matching strict par ID normalisé (Sprint 6 P3 fix bug substring) ─────
    # AVANT P3 : ``if ref in content_upper`` matchait par sous-chaîne dans le
    # contenu — un article qui MENTIONNAIT ``L.1233-3`` dans sa section
    # "Articles liés" (ex : L.1233-1) ou un changelog faisait un faux positif.
    # Pire, ``L.1233-3`` matchait ``L.1233-30`` (pas de word boundary).
    # Mesuré SW-LECO-003 (2026-05-13) : CHANGELOG/L1233-1/L1233-12 saturent
    # les 3 slots MAX_SOURCES avant que L1233-3 (le vrai article) ne soit
    # atteint dans l'index trié alphabétiquement.
    # FIX P3 : on compare l'ID normalisé du doc à l'ID normalisé de la ref —
    # seul l'article qui EST réellement la référence est ajouté.
    legal_refs_normalized = {_normalize_article_id(r) for r in legal_refs}
    for doc in index:
        doc_normalized = _normalize_article_id(doc["id"])
        if doc_normalized in legal_refs_normalized and doc["id"] not in already_ids:
            already_ids.add(doc["id"])
            sources.append({
                "id": doc["id"],
                "titre": _extract_title(doc["content"], doc["id"]),
                "extrait": _extract_snippet(doc["content"], doc["id"]),
                "pertinence": 1.0,
                "fichier_source": doc["path"],
            })
            emit(
                "retriever",
                "completed",
                hook_name="lit_article",
                article=doc["id"],
            )

    if len(sources) < MAX_SOURCES and query_tokens:
        avg_dl = sum(len(d["tokens"]) for d in index) / len(index)
        N = len(index)
        scored = []
        for doc in index:
            if doc["id"] in already_ids:
                continue
            bm25 = _bm25_score(query_tokens, doc["tokens"], avg_dl, N, index)
            if bm25 <= 0:
                continue
            # Pertinence finale = BM25 normalisé + bonus titre (cf. constantes ci-dessus)
            doc_title = _extract_title(doc["content"], doc["id"])
            base = min(bm25 / 10.0, 0.99)
            relevance = min(0.99, base + _title_match_bonus(query_tokens, doc_title))
            scored.append((relevance, doc, doc_title))
        scored.sort(key=lambda x: x[0], reverse=True)
        anchor = query_tokens[0] if query_tokens else ""
        for relevance, doc, doc_title in scored[: MAX_SOURCES - len(sources)]:
            already_ids.add(doc["id"])
            sources.append({
                "id": doc["id"],
                "titre": doc_title,
                "extrait": _extract_snippet(doc["content"], anchor),
                "pertinence": round(relevance, 2),
                "fichier_source": doc["path"],
            })
            emit(
                "retriever",
                "completed",
                hook_name="lit_article",
                article=doc["id"],
            )

    return sources


def _merge_curated_legifrance(
    curated: List[Dict[str, Any]],
    legifrance: List[Dict[str, Any]],
    max_total: int,
) -> List[Dict[str, Any]]:
    """Merge dédupliqué curatée + Légifrance avec priorité curatée si match fort.

    POURQUOI : Sprint 6 P2d-B avait identifié que l'early-return Légifrance
    court-circuitait la KB curatée même quand elle avait des articles plus
    pertinents (mesuré SW-LECO-007 : L.1233-9 curatée parfait pour
    « mentions lettre licenciement » mais Légifrance renvoyait L.1233-11/15
    et l'early-return bloquait la curatée). Cette fonction fusionne les deux
    listes :
      - Si la 1ère source curatée a une pertinence ≥ ``CURATED_STRONG_MATCH_THRESHOLD``,
        on place toute la curatée en tête (priorité curatée), puis Légifrance
        en complément.
      - Sinon on place Légifrance en tête (Légifrance est plus large) puis
        la curatée en complément.
    La dédup utilise ``_normalize_article_id`` pour éviter qu'un même article
    apparaisse en double avec des numérotations différentes.

    Args:
        curated: sources de la base curatée (triées par pertinence interne).
        legifrance: sources Légifrance (triées par FTS5).
        max_total: nombre maximum de sources retournées (MAX_SOURCES).

    Returns:
        Liste fusionnée, dédupliquée, tronquée à ``max_total``.
    """
    if curated and curated[0].get("pertinence", 0.0) >= CURATED_STRONG_MATCH_THRESHOLD:
        primary, secondary = curated, legifrance
    else:
        primary, secondary = legifrance, curated

    merged: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for s in primary + secondary:
        nid = _normalize_article_id(str(s.get("id", "")))
        if nid and nid not in seen:
            merged.append(s)
            seen.add(nid)
        if len(merged) >= max_total:
            break
    return merged


async def handle(faits_json: str) -> str:
    """
    Recherche des sources pertinentes pour les faits extraits.

    Sprint 6 P3 : la stratégie n'est plus "early-return Légifrance, fallback
    curatée" mais "retrieval parallèle curatée+Légifrance, merge prioritisé"
    (cf. ``_merge_curated_legifrance``). Cela permet à la KB curatée de
    surclasser Légifrance quand elle a un match fort (SW-LECO-007 : L.1233-9
    curatée prioritaire sur L.1233-11/15 Légifrance off-cible).

    Args:
        faits_json: JSON string produit par lecteur.handle().

    Returns:
        JSON string : {"sources": [...], "jurisprudences": [...], "non_trouve": [...]}
    """
    query_text = _extract_query_or_raw(faits_json)
    legal_refs = _extract_legal_refs(query_text)
    query_tokens = [t for t in re.findall(r'\w+', query_text.lower()) if len(t) > 3]

    legi_result = _try_legifrance(faits_json, top_k=MAX_SOURCES)
    legi_sources: List[Dict[str, Any]] = (
        legi_result.get("sources", []) if legi_result is not None else []
    )
    legi_juris: List[Dict[str, Any]] = (
        legi_result.get("jurisprudences", []) if legi_result is not None else []
    )

    curated_sources = _retrieve_curated(query_text, legal_refs, query_tokens)

    index = get_index()
    if not index and not legi_sources:
        return json.dumps(
            {
                "sources": [],
                "jurisprudences": [],
                "non_trouve": legal_refs,
                "avertissement": (
                    "Base curatée vide. "
                    "Enrichir knowledge/droit_social/licenciement_economique/ avant de relancer."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    merged = _merge_curated_legifrance(curated_sources, legi_sources, MAX_SOURCES)

    juris_keywords = {"arret", "cass", "decision", "soc"}
    curated_juris = [
        s for s in merged if any(kw in s["id"].lower() for kw in juris_keywords)
    ]
    loi_sources = [s for s in merged if s not in curated_juris]

    refs_not_found: List[str] = list(legal_refs)
    for s in merged:
        normalized = _normalize_article_id(str(s.get("id", "")))
        refs_not_found = [
            r for r in refs_not_found if _normalize_article_id(r) != normalized
        ]

    result = {
        "sources": loi_sources[:MAX_SOURCES],
        "jurisprudences": curated_juris + legi_juris,
        "non_trouve": refs_not_found,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)
