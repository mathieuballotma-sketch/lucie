"""Couche de découverte additive Manifest-Driven Engine (Sprint G-1 étape 1).

Cette couche n'est invoquée QUE par la branche `--corpus <code>` du CLI. Le
chemin droit social par défaut (mode sans flag) est inchangé. C'est un AJOUT
PUR : aucune ligne du pipeline existant n'est modifiée.

Usage :
    from lucie_v1_standalone.corpus import load_corpus, run_corpus_query
    corpus = load_corpus("fr_pharma_ansm")
    response = run_corpus_query(corpus, "puis-je faire de la pub pour un médicament listé II", use_llm=False)
    print(response.text)
"""
from .corpus_loader import (
    Article,
    Corpus,
    CorpusLoadError,
    CorpusLoader,
    CorpusNotFoundError,
    RefusalsConfig,
    ThemeInfo,
    load_corpus,
)
from .runner import CorpusResponse, run_corpus_query

__all__ = [
    "Article",
    "Corpus",
    "CorpusLoadError",
    "CorpusLoader",
    "CorpusNotFoundError",
    "CorpusResponse",
    "RefusalsConfig",
    "ThemeInfo",
    "load_corpus",
    "run_corpus_query",
]
