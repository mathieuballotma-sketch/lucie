"""run_corpus_query — wrapper additif `beaume --corpus <code> "query"`.

Branche alternative au pipeline droit social. Le pipeline existant
(`lucie_v1_standalone.pipeline.run`) reste intact. Cette fonction recrée un
mini-pipeline générique consommant un `Corpus` :

  1. Détection de portée (priority_override.patterns / domains.keywords)
  2. Retrieval BM25 simple sur les articles du corpus
  3. Synthèse :
     - si Ollama dispo et `use_llm=True` → prompt minimal au modèle local
     - sinon → réponse structurée déterministe (titres + extraits)

Aucune dépendance vers `router`, `verificateur`, `redacteur` (le pipeline
droit social n'est pas touché). La logique BM25 est une réimplémentation
isolée (pas un import du `retriever.py` historique).
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .corpus_loader import Article, Corpus

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_BM25_K1 = 1.5
_BM25_B = 0.75
_TOP_K = 3
_LLM_PROMPT_NUM_PREDICT = 600
_LLM_PROMPT_TEMPERATURE = 0.2


@dataclass(frozen=True)
class CorpusResponse:
    """Sortie d'un appel `run_corpus_query`."""

    text: str
    scope: str  # 'in_scope' | 'out_of_scope' | 'refused_scope_unknown'
    matched_articles: tuple[Article, ...] = field(default_factory=tuple)
    matched_domain: Optional[str] = None
    used_llm: bool = False


def run_corpus_query(
    corpus: Corpus,
    query: str,
    *,
    use_llm: bool = True,
    llm_provider: object | None = None,
) -> CorpusResponse:
    """Exécute une requête sur un corpus chargé.

    Args:
        corpus: Corpus chargé via `load_corpus(code)`.
        query: Question utilisateur (texte libre).
        use_llm: Si True, tente Ollama pour synthèse. Si False ou indisponible,
            renvoie une réponse structurée déterministe.
        llm_provider: Provider injecté (pour tests). Si None, instancie
            `OllamaProvider` à la demande.

    Returns:
        CorpusResponse avec texte, scope, articles matchés.
    """
    if not query or not query.strip():
        return CorpusResponse(
            text="Requête vide — fournis une question textuelle.",
            scope="refused_scope_unknown",
        )

    query_norm = query.strip()
    scope_decision = _classify_scope(corpus, query_norm)

    if scope_decision.is_out_of_scope:
        return CorpusResponse(
            text=scope_decision.redirection_text or corpus.refusals.scope_refusal,
            scope="out_of_scope",
            matched_domain=scope_decision.matched_domain,
        )

    top_articles = _bm25_top_k(corpus.articles, query_norm, k=_TOP_K)
    if not top_articles:
        return CorpusResponse(
            text=(
                f"Aucun article pertinent trouvé dans le corpus "
                f"« {corpus.manifest.identity.name} » pour : « {query_norm} ».\n"
                f"Reformulez ou élargissez votre question."
            ),
            scope="in_scope",
            matched_articles=(),
        )

    if use_llm:
        llm_text = _try_llm_synthesis(corpus, query_norm, top_articles, llm_provider)
        if llm_text is not None:
            return CorpusResponse(
                text=llm_text,
                scope="in_scope",
                matched_articles=top_articles,
                used_llm=True,
            )
        logger.info("LLM indisponible — fallback structuré déterministe.")

    return CorpusResponse(
        text=_structured_response(corpus, query_norm, top_articles),
        scope="in_scope",
        matched_articles=top_articles,
        used_llm=False,
    )


# ─── Scope detection ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _ScopeDecision:
    is_out_of_scope: bool
    matched_domain: Optional[str] = None
    redirection_text: Optional[str] = None


def _classify_scope(corpus: Corpus, query: str) -> _ScopeDecision:
    """Décision de portée. Priorité : priority_override → domains.keywords → in-scope."""
    for pattern in corpus.refusals.priority_override_patterns:
        if pattern.search(query):
            return _ScopeDecision(is_out_of_scope=False)

    query_lower = query.lower()
    for domain_code, (keywords, redirection) in corpus.refusals.domains.items():
        for kw in keywords:
            if kw and kw in query_lower:
                logger.info(
                    "scope=out_of_scope domain=%s keyword=%r", domain_code, kw
                )
                return _ScopeDecision(
                    is_out_of_scope=True,
                    matched_domain=domain_code,
                    redirection_text=redirection or corpus.refusals.scope_refusal,
                )
    return _ScopeDecision(is_out_of_scope=False)


# ─── BM25 retrieval ─────────────────────────────────────────────────────────

def _bm25_top_k(articles: tuple[Article, ...], query: str, *, k: int) -> tuple[Article, ...]:
    if not articles:
        return tuple()
    query_tokens = [t for t in _TOKEN_RE.findall(query.lower()) if len(t) > 1]
    if not query_tokens:
        return tuple()

    N = len(articles)
    avg_dl = sum(len(a.tokens) for a in articles) / max(N, 1)
    df_cache: dict[str, int] = {}

    def df(token: str) -> int:
        if token not in df_cache:
            df_cache[token] = sum(1 for a in articles if token in a.tokens_set)
        return df_cache[token]

    scored: list[tuple[float, Article]] = []
    for article in articles:
        tf_map = Counter(article.tokens)
        dl = len(article.tokens)
        score = 0.0
        for qt in query_tokens:
            tf = tf_map.get(qt, 0)
            if tf == 0:
                continue
            idf = math.log((N - df(qt) + 0.5) / (df(qt) + 0.5) + 1.0)
            numerator = tf * (_BM25_K1 + 1)
            denominator = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / max(avg_dl, 1))
            score += idf * numerator / denominator
        if score > 0:
            scored.append((score, article))

    scored.sort(key=lambda pair: -pair[0])
    return tuple(a for _, a in scored[:k])


# ─── LLM synthesis (optional) ────────────────────────────────────────────────

def _try_llm_synthesis(
    corpus: Corpus,
    query: str,
    articles: tuple[Article, ...],
    provider: object | None,
) -> Optional[str]:
    """Tente une synthèse via Ollama. Retourne None si indisponible."""
    try:
        if provider is None:
            from lucie_v1_standalone.llm.ollama_provider import OllamaProvider

            provider = OllamaProvider()
        system = (
            f"Tu es un assistant juridique spécialisé sur le corpus "
            f"« {corpus.manifest.identity.name} » (autorité : "
            f"{corpus.manifest.identity.autorite}). Réponds uniquement avec les "
            f"articles fournis ; cite-les explicitement par leur identifiant. "
            f"Si la question dépasse les articles, dis-le clairement."
        )
        prompt = _format_llm_prompt(query, articles)
        output = provider.generate(  # type: ignore[attr-defined]
            prompt,
            system=system,
            options={
                "temperature": _LLM_PROMPT_TEMPERATURE,
                "num_predict": _LLM_PROMPT_NUM_PREDICT,
            },
            stream=False,
        )
        if isinstance(output, str) and output.strip():
            return output.strip()
        return None
    except Exception as exc:
        logger.info("LLM synthesis indisponible: %s", exc)
        return None


def _format_llm_prompt(query: str, articles: tuple[Article, ...]) -> str:
    blocs = []
    for art in articles:
        excerpt = art.content[:1500]
        blocs.append(f"=== Article {art.id} ({art.title}) ===\n{excerpt}\n")
    sources_text = "\n".join(blocs)
    return (
        f"Question : {query}\n\n"
        f"Articles disponibles dans le corpus :\n{sources_text}\n"
        f"Réponse synthétique avec citations explicites (ex: « cf. {articles[0].id} ») :"
    )


# ─── Structured deterministic response (fallback / CI) ───────────────────────

def _structured_response(
    corpus: Corpus,
    query: str,
    articles: tuple[Article, ...],
) -> str:
    lines: list[str] = []
    lines.append(f"=== Beaume / corpus {corpus.manifest.identity.code} ===")
    lines.append(f"Question : {query}")
    lines.append(f"Autorité : {corpus.manifest.identity.autorite}")
    lines.append(f"Articles pertinents trouvés ({len(articles)}) :")
    for art in articles:
        snippet = _first_summary_paragraph(art.content)
        lines.append(f"  - [{art.id}] {art.title}")
        if snippet:
            lines.append(f"      {snippet}")
    lines.append("")
    lines.append(
        f"NB : mode déterministe (sans LLM). Pour une synthèse rédigée, "
        f"relance avec Ollama actif et `--corpus {corpus.manifest.identity.code}`."
    )
    return "\n".join(lines)


def _first_summary_paragraph(content: str) -> str:
    """Extrait le 1er paragraphe sous la section 'Résumé opérationnel' (ou défaut)."""
    m = re.search(r"##\s*R[ée]sum[ée][^\n]*\n+(.+?)(?:\n##|\Z)", content, re.DOTALL)
    if m:
        para = m.group(1).strip()
    else:
        # 1er paragraphe non vide hors titre principal
        paras = [p.strip() for p in content.split("\n\n") if p.strip() and not p.lstrip().startswith("#")]
        para = paras[0] if paras else content.strip()[:300]
    # Compress whitespace + truncate
    para = re.sub(r"\s+", " ", para)
    return (para[:280] + "...") if len(para) > 280 else para
