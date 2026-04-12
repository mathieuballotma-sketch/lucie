"""
RetrieverAgent — cherche dans la base curatée locale.
Modèle : E2B (speed / gemma4:e4b).

Stratégie de recherche :
  1. Matching exact sur les références légales (L1233-x)
  2. Ranking BM25 simplifié sur le contenu des fichiers .md
  3. 5 sources max retournées au Rédacteur
"""

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..base_agent import BaseAgent
from .terrain import TerrainMixin

_KNOWLEDGE_BASE = Path("knowledge/droit_social/licenciement_economique")
_MODEL = "speed"       # gemma4:e4b — léger et rapide
_MAX_SOURCES = 5
_BM25_K1 = 1.5
_BM25_B = 0.75
_LEGAL_REF_RE = re.compile(r'L\s*\d{4}(?:-\d+)?', re.IGNORECASE)


class RetrieverAgent(TerrainMixin, BaseAgent):
    """
    Retrouve les sources pertinentes dans la base curatée locale.
    N'invente aucune source — retourne explicitement les références non trouvées.
    """

    GENERATIVE_THRESHOLD = 10  # 10 entrées avec refs manquantes → proposition

    def __init__(
        self,
        llm_service: Any,
        bus: Any,
        event_bus: Any = None,
        token: Optional[str] = None,
    ):
        super().__init__(
            name="retriever",
            llm_service=llm_service,
            bus=bus,
            event_bus=event_bus,
            token=token,
        )
        self.stability = "core"
        self._knowledge_base = _KNOWLEDGE_BASE
        self._index: Optional[List[Dict[str, Any]]] = None

    def can_handle(self, query: str) -> bool:
        return False  # Utilisé uniquement via LegalPipeline

    # ─── Indexation ───────────────────────────────────────────────────────────

    def _build_index(self) -> List[Dict[str, Any]]:
        """Indexe tous les fichiers .md de la base curatée."""
        index = []
        if not self._knowledge_base.exists():
            return index
        for path in sorted(self._knowledge_base.rglob("*.md")):
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

    def _get_index(self) -> List[Dict[str, Any]]:
        if self._index is None:
            self._index = self._build_index()
        return self._index

    def invalidate_index(self) -> None:
        """Force le rechargement de l'index (utile après ajout de fichiers)."""
        self._index = None

    # ─── BM25 ─────────────────────────────────────────────────────────────────

    def _bm25_score(
        self,
        query_tokens: List[str],
        doc_tokens: List[str],
        doc_tokens_set: Set[str],
        avg_dl: float,
        N: int,
    ) -> float:
        dl = len(doc_tokens)
        tf_map: Dict[str, int] = Counter(doc_tokens)
        score = 0.0
        index = self._get_index()
        for qt in query_tokens:
            tf = tf_map.get(qt, 0)
            if tf == 0:
                continue
            df = sum(1 for d in index if qt in d["tokens_set"])
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
            numerator = tf * (_BM25_K1 + 1)
            denominator = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / max(avg_dl, 1))
            score += idf * numerator / denominator
        return score

    # ─── Utilitaires ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_legal_refs(text: str) -> List[str]:
        """Extrait les références légales type L1233-2."""
        raw = _LEGAL_REF_RE.findall(text)
        # Normaliser : supprimer espaces internes
        return [re.sub(r'\s+', '', r).upper() for r in raw]

    @staticmethod
    def _extract_title(content: str, default_id: str) -> str:
        m = re.search(r'^#\s+(.+)', content, re.MULTILINE)
        return m.group(1).strip() if m else default_id

    @staticmethod
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

    # ─── Handle ───────────────────────────────────────────────────────────────

    async def handle(self, faits_json: str) -> str:
        """
        Recherche des sources pertinentes pour les faits extraits.

        Args:
            faits_json: JSON string produit par LecteurAgent.

        Returns:
            JSON string : {"sources": [...], "jurisprudences": [...], "non_trouve": [...]}
        """
        index = self._get_index()

        # Extraire les références légales mentionnées dans les faits
        legal_refs = self._extract_legal_refs(faits_json)
        # Tokens de recherche BM25 (mots > 3 caractères)
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
            self._log_to_journal({
                "refs_demandees": legal_refs,
                "refs_trouvees": [],
                "refs_non_trouvees": legal_refs,
            })
            return json.dumps(result, ensure_ascii=False, indent=2)

        sources: List[Dict[str, Any]] = []
        refs_found: List[str] = []
        refs_not_found: List[str] = list(legal_refs)
        already_ids: Set[str] = set()

        # ── 1. Matching exact sur les références légales ──────────────────────
        for doc in index:
            content_upper = doc["content"].upper()
            for ref in legal_refs:
                if ref in content_upper and doc["id"] not in already_ids:
                    already_ids.add(doc["id"])
                    sources.append({
                        "id": doc["id"],
                        "titre": self._extract_title(doc["content"], doc["id"]),
                        "extrait": self._extract_snippet(doc["content"], ref),
                        "pertinence": 1.0,
                        "fichier_source": doc["path"],
                    })
                    if ref in refs_not_found:
                        refs_not_found.remove(ref)
                    if ref not in refs_found:
                        refs_found.append(ref)
                    break  # un seul hit par doc

        # ── 2. BM25 sur le reste ───────────────────────────────────────────────
        if len(sources) < _MAX_SOURCES and query_tokens:
            avg_dl = sum(len(d["tokens"]) for d in index) / len(index)
            N = len(index)
            scored = []
            for doc in index:
                if doc["id"] in already_ids:
                    continue
                score = self._bm25_score(
                    query_tokens, doc["tokens"], doc["tokens_set"], avg_dl, N
                )
                if score > 0:
                    scored.append((score, doc))
            scored.sort(key=lambda x: x[0], reverse=True)
            anchor = query_tokens[0] if query_tokens else ""
            for score, doc in scored[: _MAX_SOURCES - len(sources)]:
                already_ids.add(doc["id"])
                sources.append({
                    "id": doc["id"],
                    "titre": self._extract_title(doc["content"], doc["id"]),
                    "extrait": self._extract_snippet(doc["content"], anchor),
                    "pertinence": round(min(score / 10.0, 0.99), 2),
                    "fichier_source": doc["path"],
                })

        # ── Séparer loi et jurisprudence ──────────────────────────────────────
        juris_keywords = {"arret", "cass", "decision", "arret", "soc"}
        jurisprudences = [
            s for s in sources
            if any(kw in s["id"].lower() for kw in juris_keywords)
        ]
        loi_sources = [s for s in sources if s not in jurisprudences]

        result = {
            "sources": loi_sources[:_MAX_SOURCES],
            "jurisprudences": jurisprudences,
            "non_trouve": refs_not_found,
        }

        self._log_to_journal({
            "refs_demandees": legal_refs,
            "refs_trouvees": refs_found,
            "refs_non_trouvees": refs_not_found,
        })
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ─── Générative ───────────────────────────────────────────────────────────

    def _build_generative_proposal(self, lines: List[str]) -> str:
        """Propose d'enrichir la base curatée si des refs reviennent souvent non trouvées."""
        try:
            entries = [json.loads(l) for l in lines if l.strip()]
            all_not_found: List[str] = []
            for e in entries:
                all_not_found.extend(e.get("refs_non_trouvees", []))
            counts: Counter = Counter(all_not_found)
            top = [ref for ref, c in counts.most_common(5) if c >= 3]
            if not top:
                return ""
            refs_str = ", ".join(top)
            return (
                f"La base curatée manque de sources pour : {refs_str}. "
                "Veux-tu que j'ajoute ces références à "
                "knowledge/droit_social/licenciement_economique/ ?"
            )
        except Exception:
            return ""
