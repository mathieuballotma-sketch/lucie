"""Tests du runner additif `run_corpus_query` (BM25 + scope detection)."""
from __future__ import annotations

import pytest

from lucie_v1_standalone.corpus import load_corpus, run_corpus_query


@pytest.fixture(scope="module")
def pharma_corpus():
    return load_corpus("fr_pharma_ansm")


def test_in_scope_query_returns_articles(pharma_corpus):
    response = run_corpus_query(
        pharma_corpus,
        "puis-je faire de la publicité pour un médicament listé II ?",
        use_llm=False,
    )
    assert response.scope == "in_scope"
    assert len(response.matched_articles) >= 1
    assert response.used_llm is False
    matched_ids = {a.id for a in response.matched_articles}
    # Le top doit inclure au moins un article publicité (L5122-x)
    assert any(aid.startswith("L5122") for aid in matched_ids), (
        f"attendu un article L.5122-x dans le top, eu {matched_ids}"
    )
    assert "ANSM" in response.text


def test_out_of_scope_fiscal_returns_redirection(pharma_corpus):
    response = run_corpus_query(
        pharma_corpus,
        "comment optimiser la TVA sur les ventes pharmaceutiques ?",
        use_llm=False,
    )
    assert response.scope == "out_of_scope"
    assert response.matched_domain == "fiscal"
    assert "fiscal" in response.text.lower()


def test_out_of_scope_brevet_returns_redirection(pharma_corpus):
    response = run_corpus_query(
        pharma_corpus,
        "comment déposer un brevet sur ma molécule innovante ?",
        use_llm=False,
    )
    assert response.scope == "out_of_scope"
    assert response.matched_domain == "ip_brevets"


def test_priority_override_csp_keeps_in_scope(pharma_corpus):
    """Une query qui cite L.5122 doit rester in-scope même si elle contient
    un keyword 'fiscal' ou 'brevet' (priority_override.patterns)."""
    response = run_corpus_query(
        pharma_corpus,
        "L.5122-1 publicité médicament avec aspect fiscal",
        use_llm=False,
    )
    assert response.scope == "in_scope"


def test_empty_query_returns_explicit_refusal(pharma_corpus):
    response = run_corpus_query(pharma_corpus, "", use_llm=False)
    assert response.scope == "refused_scope_unknown"


def test_structured_response_contains_corpus_metadata(pharma_corpus):
    response = run_corpus_query(
        pharma_corpus,
        "définition du médicament selon CSP",
        use_llm=False,
    )
    assert "fr_pharma_ansm" in response.text
    assert "ANSM" in response.text


def test_runner_with_fake_llm_provider(pharma_corpus):
    """Le runner doit accepter un provider injecté (utile pour tests)."""

    class FakeProvider:
        def generate(self, prompt: str, **kwargs) -> str:  # noqa: ARG002
            return "RÉPONSE FAKE LLM citant L5122-1"

    response = run_corpus_query(
        pharma_corpus,
        "définition publicité médicament",
        use_llm=True,
        llm_provider=FakeProvider(),
    )
    assert response.used_llm is True
    assert "FAKE LLM" in response.text


def test_runner_fallback_when_llm_raises(pharma_corpus):
    """Si le provider LLM lève une exception, on tombe sur la réponse structurée."""

    class BoomProvider:
        def generate(self, prompt: str, **kwargs):  # noqa: ARG002
            raise RuntimeError("ollama down")

    response = run_corpus_query(
        pharma_corpus,
        "définition publicité médicament",
        use_llm=True,
        llm_provider=BoomProvider(),
    )
    assert response.used_llm is False
    assert "fr_pharma_ansm" in response.text  # mode structuré
