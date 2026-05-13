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


async def handle(faits_json: str) -> str:
    """
    Recherche des sources pertinentes pour les faits extraits.

    Args:
        faits_json: JSON string produit par lecteur.handle().

    Returns:
        JSON string : {"sources": [...], "jurisprudences": [...], "non_trouve": [...]}
    """
    # 0. Tenter Légifrance en premier si activé et base présente
    legi_result = _try_legifrance(faits_json, top_k=MAX_SOURCES)
    if legi_result is not None and legi_result.get("sources"):
        return json.dumps(legi_result, ensure_ascii=False, indent=2)

    index = get_index()

    # Sprint 6 P2d-B — même rationale que `_try_legifrance` : si on a un JSON
    # wrapper avec une clé `query`, on tokenise/extrait les refs depuis la
    # query nue plutôt que depuis le JSON entier (sinon tokens parasites).
    query_text = _extract_query_or_raw(faits_json)
    legal_refs = _extract_legal_refs(query_text)
    query_tokens = [t for t in re.findall(r'\w+', query_text.lower()) if len(t) > 3]

    if not index:
        result = {
            "sources": [],
            "jurisprudences": [],
            "non_trouve": legal_refs,
            "avertissement": (
                "Base curatée vide. "
                "Enrichir knowledge/droit_social/licenciement_economique/ avant de relancer."
            ),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    sources: List[Dict[str, Any]] = []
    refs_not_found: List[str] = list(legal_refs)
    already_ids: Set[str] = set()

    # ── 1. Matching exact sur les références légales ──────────────────────────
    for doc in index:
        content_upper = doc["content"].upper()
        for ref in legal_refs:
            if ref in content_upper and doc["id"] not in already_ids:
                already_ids.add(doc["id"])
                sources.append({
                    "id": doc["id"],
                    "titre": _extract_title(doc["content"], doc["id"]),
                    "extrait": _extract_snippet(doc["content"], ref),
                    "pertinence": 1.0,
                    "fichier_source": doc["path"],
                })
                emit(
                    "retriever",
                    "completed",
                    hook_name="lit_article",
                    article=ref,
                )
                if ref in refs_not_found:
                    refs_not_found.remove(ref)
                break  # un seul hit par doc

    # ── 2. BM25 sur le reste ──────────────────────────────────────────────────
    if len(sources) < MAX_SOURCES and query_tokens:
        avg_dl = sum(len(d["tokens"]) for d in index) / len(index)
        N = len(index)
        scored = []
        for doc in index:
            if doc["id"] in already_ids:
                continue
            score = _bm25_score(
                query_tokens, doc["tokens"], avg_dl, N, index
            )
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        anchor = query_tokens[0] if query_tokens else ""
        for score, doc in scored[: MAX_SOURCES - len(sources)]:
            already_ids.add(doc["id"])
            sources.append({
                "id": doc["id"],
                "titre": _extract_title(doc["content"], doc["id"]),
                "extrait": _extract_snippet(doc["content"], anchor),
                "pertinence": round(min(score / 10.0, 0.99), 2),
                "fichier_source": doc["path"],
            })
            emit(
                "retriever",
                "completed",
                hook_name="lit_article",
                article=doc["id"],
            )

    # ── Séparer loi et jurisprudence ──────────────────────────────────────────
    juris_keywords = {"arret", "cass", "decision", "soc"}
    jurisprudences = [
        s for s in sources
        if any(kw in s["id"].lower() for kw in juris_keywords)
    ]
    loi_sources = [s for s in sources if s not in jurisprudences]

    result = {
        "sources": loi_sources[:MAX_SOURCES],
        "jurisprudences": jurisprudences,
        "non_trouve": refs_not_found,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)
