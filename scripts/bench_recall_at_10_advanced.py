#!/usr/bin/env python3
"""bench_recall_at_10_advanced — Sprint K-1, teste 4 variantes de retrieval.

Variantes mesurées en parallèle (même embed, même top-100 binaire/bm25) :
    V1 baseline_binary      : top-10 binaire (=baseline K-1 actuel)
    V2 binary_pr_rerank     : top-100 binaire → re-rank PageRank → top-10
    V3 hybrid_rrf           : RRF(binary_top_100, bm25_top_100) → top-10
    V4 hybrid_rrf_pr_filter : V3 → PR re-rank → filter annexes → top-10

Toutes les variantes utilisent les MÊMES embeddings et les MÊMES top-100
underlying. La seule différence est l'étape de post-traitement. Coût marginal
trivial vs un seul run, et permet une comparaison sans aléa de seed.

Output : kb_artifacts/recall_at_10_variants.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Bypass lucie_v1_standalone/__init__.py which transitively imports docx, ollama,
# etc. — irrelevant to the bench. We register the parent packages as empty
# namespaces so Python won't re-execute their real __init__ files.
import types as _types  # noqa: E402
for _pkg, _path_parts in [
    ("lucie_v1_standalone", ["lucie_v1_standalone"]),
    ("lucie_v1_standalone.knowledge_legifrance", ["lucie_v1_standalone", "knowledge_legifrance"]),
]:
    if _pkg not in sys.modules:
        _m = _types.ModuleType(_pkg)
        _m.__path__ = [str(_REPO_ROOT.joinpath(*_path_parts))]  # type: ignore[attr-defined]
        sys.modules[_pkg] = _m

import numpy as np  # noqa: E402

from lucie_v1_standalone.knowledge_legifrance.kb_compact.constants import (  # noqa: E402
    DEFAULT_TOP_K,
    LONG_BITS,
    RECALL_THRESHOLD,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.embedder import (  # noqa: E402
    Embedder,
    EmbedderConfig,
    binary_quantize,
)
from lucie_v1_standalone.knowledge_legifrance.kb_compact.pagerank import read_pagerank_f32  # noqa: E402
from lucie_v1_standalone.knowledge_legifrance.kb_compact.sig_reader import (  # noqa: E402
    load_index,
    load_sigs,
    read_header,
)
from lucie_v1_standalone.knowledge_legifrance.refs_extractor import extract_refs_from_behavior  # noqa: E402

logger = logging.getLogger(__name__)


# Stopwords français pour la requête FTS5 (mêmes que bench_recall_at_10_bm25.py)
_STOPWORDS = {
    "le", "la", "les", "un", "une", "des", "de", "du", "au", "aux",
    "et", "ou", "ni", "que", "qui", "quoi", "dont", "où", "ce", "ces",
    "est", "sont", "etre", "être", "ete", "été", "sera", "serait",
    "pour", "par", "sur", "sous", "dans", "avec", "sans", "vers", "chez",
    "en", "se", "sa", "son", "ses", "leur", "leurs", "il", "elle", "on",
    "ne", "pas", "ni", "non", "plus", "moins", "mais", "donc", "car",
    "comment", "pourquoi", "quel", "quelle", "quels", "quelles",
    "selon", "ainsi", "encore", "aussi", "egalement", "également",
    "the", "of", "and", "or", "to", "in", "is", "are",
}
_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)

# Heuristique annexe/modèle : tout num qui ne ressemble PAS à un article codifié
# L.NNNN-N / R.NNNN-N / D.NNNN-N / A.NNNN-N est filtré. Couvre les annexes
# d'arrêté ("Annexe IV"), les "Articles 5 à 7" des conventions, "MODÈLE DE
# LETTRE", "3" pur numérique d'un arrêté, etc.
_CODE_NUM_RE = re.compile(r"^[LRDA]\.?\s*\d{1,5}(-\d{1,4})?\s*$")


def sanitize_for_fts5(text: str) -> str:
    """Construit une query FTS5 OR-jointe en phrase-quoting les tokens."""
    text = unicodedata.normalize("NFC", text)
    tokens = _WORD_RE.findall(text.lower())
    keep: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        if len(t) < 3 or t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        keep.append(f'"{t}"')
    if not keep:
        keep.append('"droit"')
    return " OR ".join(keep)


def resolve_refs_to_article_ids(refs, db_path: Path) -> list[str]:
    if not refs:
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        ids: list[str] = []
        for prefix, num in refs:
            canon = "".join(c for c in f"{prefix}{num}".upper() if not c.isspace() and c != ".")
            cur.execute(
                "SELECT id FROM articles WHERE etat='VIGUEUR' AND "
                "REPLACE(REPLACE(UPPER(num),' ',''),'.','') = ?",
                (canon,),
            )
            for row in cur.fetchall():
                ids.append(row[0])
        return ids
    finally:
        conn.close()


def hamming_top_k_with_scores(
    query_sig: np.ndarray, sigs_long: np.ndarray, k: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Retourne (top-k rows, popcount_scores) — plus bas popcount = mieux."""
    xor = np.bitwise_xor(sigs_long, query_sig[np.newaxis, :])
    popcount = np.unpackbits(xor, axis=1).sum(axis=1)
    if k >= sigs_long.shape[0]:
        order = np.argsort(popcount)
    else:
        top = np.argpartition(popcount, k)[:k]
        order = top[np.argsort(popcount[top])]
    return order, popcount[order]


def bm25_top_k_articles(
    conn: sqlite3.Connection, fts_query: str, k: int,
) -> list[str]:
    """Top-k article_ids par BM25 FTS5 (VIGUEUR uniquement)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT a.id
        FROM articles_fts f
        JOIN articles a ON a.rowid = f.rowid
        WHERE articles_fts MATCH ?
          AND a.etat = 'VIGUEUR'
        ORDER BY bm25(articles_fts)
        LIMIT ?
        """,
        (fts_query, k),
    )
    return [row[0] for row in cur.fetchall()]


def reciprocal_rank_fusion(
    ranked_lists: list[list[int]], k_rrf: int = 60,
) -> list[int]:
    """RRF — sum(1 / (k + rank)) sur chaque liste, tri descendant.

    Standard RRF: k_rrf=60 (cf. Cormack et al. 2009).
    """
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k_rrf + rank)
    return sorted(scores.keys(), key=lambda x: -scores[x])


def pagerank_rerank(
    rows: np.ndarray,
    popcount: np.ndarray,
    pagerank: np.ndarray,
    *,
    w_pop: float = 0.7,
    w_pr: float = 0.3,
) -> list[int]:
    """Combine score Hamming (normalisé inversé) + score PageRank (log normalisé)."""
    if len(rows) == 0:
        return []
    # Hamming : plus petit = mieux → on inverse via 1 - normalised
    pop_max = float(popcount.max()) if popcount.max() > 0 else 1.0
    pop_norm = 1.0 - (popcount.astype(np.float32) / pop_max)

    pr_scores = pagerank[rows].astype(np.float32)
    # Log-scale PR pour réduire l'étendue dynamique (PR très concentrés sur top)
    pr_log = np.log1p(pr_scores * 1e6)  # 1e6 pour amplifier petites valeurs
    pr_max = float(pr_log.max()) if pr_log.max() > 0 else 1.0
    pr_norm = pr_log / pr_max

    combined = w_pop * pop_norm + w_pr * pr_norm
    order = np.argsort(combined)[::-1]
    return [int(rows[i]) for i in order]


def is_codified_article(num: str | None) -> bool:
    """True si num matche le pattern d'article codifié L./R./D./A. (codes officiels)."""
    if not num:
        return False
    return bool(_CODE_NUM_RE.match(num.strip()))


@dataclass
class VariantResult:
    name: str
    top10_rows: list[int]
    hit: bool


@dataclass
class QuestionEval:
    qid: str
    category: str
    expected_refs: list[list[str]]
    expected_rows: list[int]
    n_expected_resolvable: int
    skipped_reason: str | None
    variants: list[VariantResult] = field(default_factory=list)
    fts_query: str = ""
    latency_ms_total: float = 0.0


def run_bench(
    *,
    artifacts_dir: Path,
    bench_path: Path,
    db_path: Path,
    output_path: Path,
    model_name: str | None,
    seed: int,
    auto_download: bool,
    top_k_underlying: int = 100,
    top_k_final: int = DEFAULT_TOP_K,
) -> int:
    bench = json.loads(bench_path.read_text())

    logger.info("Loading signatures from %s ...", artifacts_dir / "sigs_mrl.bin")
    header, _sigs_short, sigs_long = load_sigs(artifacts_dir / "sigs_mrl.bin")
    index = load_index(artifacts_dir / "sigs_mrl.index.cbor")
    article_to_row: dict[str, int] = index["article_to_row"]
    row_to_article: dict[int, str] = {v: k for k, v in article_to_row.items()}
    logger.info("Loaded %d signatures", header.n_articles)

    pr_header, pagerank = read_pagerank_f32(artifacts_dir / "pagerank.f32")
    logger.info("Loaded pagerank: n=%d damping=%.3f iter=%d",
                pr_header.n_articles, pr_header.damping, pr_header.n_iter_used)
    if pr_header.n_articles != header.n_articles:
        raise ValueError(
            f"pagerank n_articles ({pr_header.n_articles}) != sigs n_articles ({header.n_articles})")

    # SQLite : articles VIGUEUR + articles_fts. Connexion partagée pour la durée du bench.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    # Cache num par article_id pour le filtre annexes (évite 1 SELECT par article filtré)
    num_cache: dict[str, str] = {}

    def get_num(aid: str) -> str | None:
        if aid in num_cache:
            return num_cache[aid]
        cur = conn.cursor()
        cur.execute("SELECT num FROM articles WHERE id=?", (aid,))
        row = cur.fetchone()
        num = row[0] if row else None
        num_cache[aid] = num or ""
        return num

    if model_name is None:
        hdr = read_header(artifacts_dir / "sigs_mrl.bin")
        model_name = hdr.model_name
        logger.info("Using model from sigs header: %s", model_name)
    embedder = Embedder(EmbedderConfig(
        model_name=model_name, seed=seed, auto_download=auto_download,
    ))

    results: list[QuestionEval] = []
    variant_counters: dict[str, dict[str, int]] = {
        "V1_binary_only": {"hit": 0},
        "V2_binary_pr_rerank": {"hit": 0},
        "V3_hybrid_rrf": {"hit": 0},
        "V4_hybrid_rrf_pr_filter": {"hit": 0},
    }
    n_matchable = 0
    t_start = time.monotonic()

    for i, q in enumerate(bench, 1):
        qid = q.get("id", f"Q-{i}")
        category = q.get("category", "?")
        expected_behavior = q.get("expected_behavior", "")
        prompt = q.get("prompt", "")

        refs = extract_refs_from_behavior(expected_behavior)
        if not refs:
            results.append(QuestionEval(
                qid=qid, category=category, expected_refs=[],
                expected_rows=[], n_expected_resolvable=0,
                skipped_reason="no_expected_refs_in_behavior",
            ))
            continue
        expected_aids = resolve_refs_to_article_ids(refs, db_path)
        expected_rows = [article_to_row[aid] for aid in expected_aids if aid in article_to_row]
        if not expected_rows:
            results.append(QuestionEval(
                qid=qid, category=category,
                expected_refs=[list(r) for r in refs],
                expected_rows=[], n_expected_resolvable=0,
                skipped_reason="refs_not_resolvable_in_kb",
            ))
            continue
        expected_set = set(expected_rows)

        t_q0 = time.perf_counter()

        # --- Underlying retrievals (calcul une fois) ---
        query_vec = embedder.embed_one(prompt)
        query_sig = binary_quantize(query_vec[np.newaxis, :], LONG_BITS)[0]
        binary_rows, binary_pop = hamming_top_k_with_scores(query_sig, sigs_long, top_k_underlying)

        fts_query = sanitize_for_fts5(prompt)
        bm25_aids = bm25_top_k_articles(conn, fts_query, top_k_underlying)
        bm25_rows = [article_to_row[aid] for aid in bm25_aids if aid in article_to_row]

        # --- V1 baseline_binary : top-10 binaire ---
        v1_top10 = [int(r) for r in binary_rows[:top_k_final]]
        v1_hit = bool(set(v1_top10) & expected_set)

        # --- V2 binary + pr_rerank : top-100 binaire → rerank PR → top-10 ---
        v2_reranked = pagerank_rerank(binary_rows, binary_pop, pagerank, w_pop=0.7, w_pr=0.3)
        v2_top10 = v2_reranked[:top_k_final]
        v2_hit = bool(set(v2_top10) & expected_set)

        # --- V3 hybrid_rrf : RRF(binary, bm25) → top-10 ---
        binary_rows_list = [int(r) for r in binary_rows]
        v3_fused = reciprocal_rank_fusion([binary_rows_list, bm25_rows])
        v3_top10 = v3_fused[:top_k_final]
        v3_hit = bool(set(v3_top10) & expected_set)

        # --- V4 hybrid + pr_rerank + filter_annexes ---
        # Étape 1: RRF binary + bm25 → top-100 fusionné
        v4_pool = v3_fused[:top_k_underlying]
        # Étape 2: PR rerank sur ce pool. On reconstruit popcount pour chaque row (depuis binary_pop)
        binary_pop_map = {int(binary_rows[j]): float(binary_pop[j]) for j in range(len(binary_rows))}
        v4_pool_pop = np.array([
            binary_pop_map.get(r, float(binary_pop.max()))  # row hors top-100 binaire = pénalisé
            for r in v4_pool
        ], dtype=np.float32)
        v4_reranked = pagerank_rerank(
            np.array(v4_pool), v4_pool_pop, pagerank, w_pop=0.6, w_pr=0.4,
        )
        # Étape 3: filtre annexes — garde uniquement les num codifiés L./R./D./A.
        v4_filtered: list[int] = []
        for r in v4_reranked:
            aid = row_to_article.get(int(r))
            if aid is None:
                continue
            num = get_num(aid)
            if is_codified_article(num):
                v4_filtered.append(int(r))
            if len(v4_filtered) >= top_k_final:
                break
        v4_hit = bool(set(v4_filtered) & expected_set)

        n_matchable += 1
        for variant_name, hit in [
            ("V1_binary_only", v1_hit),
            ("V2_binary_pr_rerank", v2_hit),
            ("V3_hybrid_rrf", v3_hit),
            ("V4_hybrid_rrf_pr_filter", v4_hit),
        ]:
            if hit:
                variant_counters[variant_name]["hit"] += 1

        latency_ms = (time.perf_counter() - t_q0) * 1000
        results.append(QuestionEval(
            qid=qid, category=category,
            expected_refs=[list(r) for r in refs],
            expected_rows=expected_rows,
            n_expected_resolvable=len(expected_rows),
            skipped_reason=None,
            variants=[
                VariantResult("V1_binary_only", v1_top10, v1_hit),
                VariantResult("V2_binary_pr_rerank", v2_top10, v2_hit),
                VariantResult("V3_hybrid_rrf", v3_top10, v3_hit),
                VariantResult("V4_hybrid_rrf_pr_filter", v4_filtered, v4_hit),
            ],
            fts_query=fts_query,
            latency_ms_total=latency_ms,
        ))

    elapsed = time.monotonic() - t_start
    conn.close()

    recalls = {
        name: cnt["hit"] / n_matchable if n_matchable else 0.0
        for name, cnt in variant_counters.items()
    }

    report = {
        "schema_version": 2,
        "sprint": "K-1",
        "model": model_name,
        "n_questions_total": len(bench),
        "n_questions_matchable": n_matchable,
        "top_k_underlying": top_k_underlying,
        "top_k_final": top_k_final,
        "variants": {
            name: {
                "hits": cnt["hit"],
                "recall": recalls[name],
                "pct": recalls[name] * 100,
            }
            for name, cnt in variant_counters.items()
        },
        "threshold": RECALL_THRESHOLD,
        "wall_clock_seconds": elapsed,
        "questions": [asdict(r) for r in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    logger.info("===== VARIANTS BENCH COMPLETE =====")
    for name, rc in recalls.items():
        bar = "█" * int(rc * 20)
        logger.info("  %s  %5.2f%%  %s", name.ljust(28), rc * 100, bar)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--artifacts", type=Path, default=Path("kb_artifacts"))
    p.add_argument("--bench", type=Path, default=Path("bench/swiss_watch_50.json"))
    p.add_argument(
        "--db", type=Path,
        default=Path.home() / "Library" / "Application Support" / "Beaume" / "legifrance" / "legi.sqlite",
    )
    p.add_argument("--output", type=Path, default=Path("kb_artifacts/recall_at_10_variants.json"))
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--auto-download", action="store_true")
    p.add_argument("--top-k-underlying", type=int, default=100)
    p.add_argument("--top-k-final", type=int, default=DEFAULT_TOP_K)
    p.add_argument("--log-level", type=str, default="INFO")
    args = p.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    return run_bench(
        artifacts_dir=args.artifacts,
        bench_path=args.bench,
        db_path=args.db,
        output_path=args.output,
        model_name=args.model,
        seed=args.seed,
        auto_download=args.auto_download,
        top_k_underlying=args.top_k_underlying,
        top_k_final=args.top_k_final,
    )


if __name__ == "__main__":
    sys.exit(main())
