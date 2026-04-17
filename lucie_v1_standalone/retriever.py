"""
RetrieverAgent — cherche dans la base curatée locale.
Modèle : gemma4:e4b (speed).

Stratégie de recherche :
  1. Matching exact sur les références légales (L.1233-x)
  2. Ranking BM25 simplifié sur le contenu des fichiers .md
  3. 5 sources max retournées au Rédacteur

Aucune dépendance au reste du repo.
"""

import json
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set

from .config import BM25_B, BM25_K1, KNOWLEDGE_BASE_PATH, MAX_SOURCES

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
        except Exception:
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


async def handle(faits_json: str) -> str:
    """
    Recherche des sources pertinentes pour les faits extraits.

    Args:
        faits_json: JSON string produit par lecteur.handle().

    Returns:
        JSON string : {"sources": [...], "jurisprudences": [...], "non_trouve": [...]}
    """
    index = get_index()

    legal_refs = _extract_legal_refs(faits_json)
    query_tokens = [t for t in re.findall(r'\w+', faits_json.lower()) if len(t) > 3]

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
