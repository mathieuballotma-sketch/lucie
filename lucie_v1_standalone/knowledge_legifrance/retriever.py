"""
LegifranceRetriever — API publique pour les agents Lucie.

Contrat public :
- `LegifranceRetriever(db_path)` : ouvre la DB SQLite Légifrance.
- `.search(query, themes, top_k)` : retourne `list[LegalArticle]`.
- `.handle(faits_json) -> str`    : sérialise en JSON **identique** au contrat
  de `lucie_v1_standalone/retriever.handle()` — `{"sources": [...],
  "jurisprudences": [...], "non_trouve": [...]}`. Garantit la non-régression
  du pipeline aval (Rédacteur, Vérificateur).

Stratégie de recherche (par ordre de priorité) :
  1. Matching exact sur les références légales détectées dans `query`
     (ex : "L.1234-1", "R1411-2", "212-1"). Si un thème est actif, restreint
     au périmètre du thème ; sinon cherche toute la base.
  2. Full-text BM25 via FTS5 sur `articles_fts`, restreint par thème si
     fourni. Si FTS5 indisponible, fallback LIKE.

Seuls les articles `etat = 'VIGUEUR'` sont retournés (voir indexer pour
le périmètre indexé).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
_LEGAL_REF_RE = re.compile(
    r"""(?xi)
    \b
    (?:article\s+|art\.?\s*)?             # 'article' / 'art.' optionnel
    (?P<prefix>[LRDA])?\s*\.?\s*          # préfixe L/R/D/A optionnel
    (?P<numeric>\d{1,5})                   # numéro principal
    (?:\s*-\s*(?P<suffix>\d{1,4}))?       # suffixe -N optionnel
    \b
    """
)


@dataclass(frozen=True)
class LegalArticle:
    """Un article juridique en vigueur retourné par le retriever."""

    id: str                 # ex: LEGIARTI000006901007
    code_cid: str           # ex: LEGITEXT000006072050
    code_titre: str         # ex: "Code du travail"
    num: str                # ex: "L1233-1"
    texte: str
    etat: str               # toujours "VIGUEUR" pour l'instant
    date_debut: str | None
    date_fin: str | None
    url_legifrance: str
    pertinence: float       # [0.0, 1.0] — BM25 normalisé ou 1.0 pour match exact
    theme: str | None = None  # thème matché (premier thème correspondant)

    def to_source_dict(self) -> dict[str, Any]:
        """Forme compatible avec le contrat JSON du Retriever Lucie actuel."""
        return {
            "id": self.num,                # "L1233-1" — humain-lisible
            "titre": f"{self.code_titre} — Article {self.num}",
            "extrait": _extract_snippet(self.texte),
            "pertinence": round(min(self.pertinence, 1.0), 2),
            "fichier_source": self.url_legifrance,
            "article_id": self.id,
            "code_cid": self.code_cid,
            "date_debut": self.date_debut,
            "date_fin": self.date_fin,
            "theme": self.theme,
        }


def _extract_snippet(text: str, max_len: int = 300) -> str:
    if len(text) <= max_len:
        return text.strip()
    cut = text[:max_len].rsplit(" ", 1)[0]
    return cut.strip() + "…"


def _normalize_ref(raw: str) -> tuple[str, str]:
    """
    Normalise une référence ex. "L. 1234-1" → ("L", "1234-1").
    Renvoie (prefix, num_canonique) ou ("", "") si illisible.
    """
    m = _LEGAL_REF_RE.search(raw)
    if m is None:
        return ("", "")
    prefix = (m.group("prefix") or "").upper()
    numeric = m.group("numeric") or ""
    suffix = m.group("suffix")
    num = numeric + (f"-{suffix}" if suffix else "")
    return (prefix, num)


def extract_legal_refs(text: str) -> list[tuple[str, str]]:
    """Extrait toutes les références légales de `text` sous forme (prefix, num)."""
    refs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _LEGAL_REF_RE.finditer(text):
        prefix = (match.group("prefix") or "").upper()
        numeric = match.group("numeric") or ""
        suffix = match.group("suffix")
        if not numeric:
            continue
        # Éviter les bruits type "1000" sans préfixe et sans suffixe
        # (on garde uniquement les refs qui ressemblent à des articles
        # codifiés : soit préfixe L/R/D/A, soit suffixe -N présent)
        if not prefix and not suffix:
            continue
        num = numeric + (f"-{suffix}" if suffix else "")
        key = (prefix, num)
        if key in seen:
            continue
        seen.add(key)
        refs.append(key)
    return refs


class LegifranceRetriever:
    """
    Wrapper read-only sur la base SQLite Légifrance.

    Utilisation typique :

        retriever = LegifranceRetriever(get_legifrance_db_path())
        articles = retriever.search(
            query="délai de préavis licenciement",
            themes=["droit_social"],
            top_k=5,
        )
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Base Légifrance absente : {self.db_path}. "
                "Lancer `python scripts/legifrance_sync.py --first-run` d'abord."
            )
        self._conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row
        self._fts_available = self._check_fts()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "LegifranceRetriever":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _check_fts(self) -> bool:
        try:
            self._conn.execute("SELECT 1 FROM articles_fts LIMIT 1")
            return True
        except sqlite3.DatabaseError:
            return False

    def _articles_in_themes(self, themes: Sequence[str]) -> set[str]:
        """Retourne l'ensemble des article_id appartenant à >=1 des thèmes."""
        if not themes:
            return set()
        placeholders = ",".join("?" for _ in themes)
        cur = self._conn.execute(
            f"SELECT article_id FROM articles_by_theme "
            f"WHERE theme_id IN ({placeholders})",
            tuple(themes),
        )
        return {row["article_id"] for row in cur.fetchall()}

    def _fetch_articles(
        self, ids: Iterable[str]
    ) -> list[sqlite3.Row]:
        ids_list = list(ids)
        if not ids_list:
            return []
        placeholders = ",".join("?" for _ in ids_list)
        cur = self._conn.execute(
            f"""
            SELECT a.*, c.titre AS code_titre
              FROM articles a
              LEFT JOIN codes c ON c.cid = a.code_cid
             WHERE a.id IN ({placeholders})
               AND a.etat = 'VIGUEUR'
            """,
            tuple(ids_list),
        )
        return cur.fetchall()

    def _row_to_article(
        self, row: sqlite3.Row, pertinence: float, theme: str | None
    ) -> LegalArticle:
        return LegalArticle(
            id=row["id"],
            code_cid=row["code_cid"],
            code_titre=row["code_titre"] or row["code_cid"],
            num=row["num"],
            texte=row["texte"],
            etat=row["etat"],
            date_debut=row["date_debut"],
            date_fin=row["date_fin"],
            url_legifrance=row["url_legifrance"],
            pertinence=pertinence,
            theme=theme,
        )

    def _search_by_ref(
        self,
        refs: Sequence[tuple[str, str]],
        theme_ids: set[str] | None,
        themes_arg: Sequence[str] | None,
    ) -> list[LegalArticle]:
        if not refs:
            return []
        conditions = []
        params: list[Any] = []
        for prefix, num in refs:
            # La DB stocke le num canonique complet (ex : "L1234-1"),
            # num_prefix sépare le préfixe, num reste le full. On
            # supporte les deux conventions d'écriture côté requête.
            canonical = f"{prefix}{num}" if prefix else num
            conditions.append("(num_prefix = ? AND num = ?)")
            params.extend([prefix, canonical])
        where = " OR ".join(conditions)
        sql = f"""
            SELECT a.*, c.titre AS code_titre
              FROM articles a
              LEFT JOIN codes c ON c.cid = a.code_cid
             WHERE ({where}) AND a.etat = 'VIGUEUR'
        """
        rows = self._conn.execute(sql, params).fetchall()
        if theme_ids is not None:
            rows = [r for r in rows if r["id"] in theme_ids]
        first_theme = themes_arg[0] if themes_arg else None
        return [self._row_to_article(r, 1.0, first_theme) for r in rows]

    def _search_fulltext(
        self,
        query: str,
        theme_ids: set[str] | None,
        themes_arg: Sequence[str] | None,
        top_k: int,
    ) -> list[LegalArticle]:
        if not query.strip():
            return []
        first_theme = themes_arg[0] if themes_arg else None

        if self._fts_available:
            # FTS5 : bm25() plus petit = plus pertinent → on inverse.
            sanitized = _sanitize_fts_query(query)
            if not sanitized:
                return []
            try:
                cur = self._conn.execute(
                    """
                    SELECT a.*, c.titre AS code_titre,
                           bm25(articles_fts) AS bm25_score
                      FROM articles_fts
                      JOIN articles a ON a.rowid = articles_fts.rowid
                      LEFT JOIN codes c ON c.cid = a.code_cid
                     WHERE articles_fts MATCH ? AND a.etat = 'VIGUEUR'
                     ORDER BY bm25_score ASC
                     LIMIT ?
                    """,
                    (sanitized, top_k * 4),  # pad for theme filtering
                )
                rows = cur.fetchall()
            except sqlite3.DatabaseError as exc:
                logger.warning("FTS5 query failed (%s), fallback LIKE", exc)
                rows = self._fallback_like(query, top_k * 4)
        else:
            rows = self._fallback_like(query, top_k * 4)

        results = []
        scores = [float(r["bm25_score"]) for r in rows if "bm25_score" in r.keys()]
        max_abs = max((abs(s) for s in scores), default=1.0) or 1.0
        for row in rows:
            if theme_ids is not None and row["id"] not in theme_ids:
                continue
            if "bm25_score" in row.keys():
                # bm25() retourne des valeurs négatives (plus petit = mieux).
                raw = float(row["bm25_score"])
                normalized = max(0.0, min(1.0, (abs(raw) / max_abs) * 0.95))
            else:
                normalized = 0.5
            results.append(self._row_to_article(row, normalized, first_theme))
            if len(results) >= top_k:
                break
        return results

    def _fallback_like(self, query: str, limit: int) -> list[sqlite3.Row]:
        tokens = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 3]
        if not tokens:
            return []
        conds = " AND ".join("LOWER(a.texte) LIKE ?" for _ in tokens)
        params = [f"%{t}%" for t in tokens]
        cur = self._conn.execute(
            f"""
            SELECT a.*, c.titre AS code_titre
              FROM articles a
              LEFT JOIN codes c ON c.cid = a.code_cid
             WHERE {conds} AND a.etat = 'VIGUEUR'
             LIMIT ?
            """,
            (*params, limit),
        )
        return cur.fetchall()

    def search(
        self,
        query: str,
        themes: Sequence[str] | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[LegalArticle]:
        """
        Recherche les articles pertinents pour `query`.

        - `themes` restreint au périmètre indexé (table `articles_by_theme`).
          Si `None` ou vide, cherche toute la base (plus lent, plus bruité).
        - `top_k` limite le nombre de résultats finaux.

        Ordre : matching exact de référence → FTS5 → LIKE (fallback).
        Déduplique par `article.id`.
        """
        if top_k <= 0:
            return []

        theme_ids = self._articles_in_themes(themes) if themes else None
        if theme_ids is not None and not theme_ids:
            # thème demandé mais aucun article indexé → vide
            return []

        refs = extract_legal_refs(query)
        exact = self._search_by_ref(refs, theme_ids, themes)

        results: list[LegalArticle] = []
        seen: set[str] = set()
        for art in exact:
            if art.id not in seen:
                results.append(art)
                seen.add(art.id)
            if len(results) >= top_k:
                return results

        fulltext = self._search_fulltext(
            query, theme_ids, themes, top_k - len(results)
        )
        for art in fulltext:
            if art.id not in seen:
                results.append(art)
                seen.add(art.id)
            if len(results) >= top_k:
                break

        return results

    def handle(
        self,
        faits_json: str,
        themes: Sequence[str] | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> str:
        """
        Compatible avec le contrat de `lucie_v1_standalone/retriever.handle()`.

        Retourne un JSON {"sources": [...], "jurisprudences": [...], "non_trouve": [...]}.
        Les jurisprudences ne sont jamais peuplées par LEGI (qui ne contient
        que la législation) — la clé est conservée pour le pipeline aval.
        """
        articles = self.search(faits_json, themes=themes, top_k=top_k)
        sources = [a.to_source_dict() for a in articles]
        found_nums = {a.num.upper() for a in articles}
        refs = extract_legal_refs(faits_json)
        not_found = []
        for prefix, num in refs:
            canonical = f"{prefix}{num}" if prefix else num
            if canonical.upper() not in found_nums:
                not_found.append(canonical)
        result = {
            "sources": sources,
            "jurisprudences": [],
            "non_trouve": not_found,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)


_FTS_SAFE_TOKEN_RE = re.compile(r"[a-zA-Zàâäéèêëîïôöùûüç0-9]+", re.UNICODE)


def _sanitize_fts_query(query: str) -> str:
    """
    Nettoie une query pour FTS5 : extrait les tokens > 2 chars, les joint
    avec OR pour être tolérant aux variantes.

    Évite l'injection d'opérateurs FTS5 (NEAR, *, quotes) depuis la query
    utilisateur brute.
    """
    tokens = [t for t in _FTS_SAFE_TOKEN_RE.findall(query) if len(t) > 2]
    if not tokens:
        return ""
    return " OR ".join(tokens[:12])  # cap pour éviter des queries massives
