"""
Tests retriever : contrat JSON + matching référence exacte + non-hallucination.

Le contrat est CRITIQUE : le pipeline Lucie aval (Rédacteur, Vérificateur)
suppose `{"sources": [...], "jurisprudences": [...], "non_trouve": [...]}`.
Toute régression ici casserait le pipeline complet.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lucie_v1_standalone.knowledge_legifrance.retriever import (
    LegifranceRetriever,
    extract_legal_refs,
)


# ── Contrat JSON ──────────────────────────────────────────────────────────────

def test_handle_returns_three_keys_contract(seeded_db: Path):
    with LegifranceRetriever(seeded_db) as r:
        payload = r.handle("L.1234-1 préavis de licenciement", themes=["droit_social"])
    parsed = json.loads(payload)
    assert set(parsed.keys()) == {"sources", "jurisprudences", "non_trouve"}
    assert isinstance(parsed["sources"], list)
    assert isinstance(parsed["jurisprudences"], list)
    assert isinstance(parsed["non_trouve"], list)


def test_source_dict_has_required_fields(seeded_db: Path):
    with LegifranceRetriever(seeded_db) as r:
        payload = r.handle("L.1234-1", themes=["droit_social"])
    parsed = json.loads(payload)
    assert parsed["sources"], "au moins une source attendue"
    src = parsed["sources"][0]
    for key in ("id", "titre", "extrait", "pertinence", "fichier_source"):
        assert key in src, f"champ `{key}` manquant dans la source"
    assert 0.0 <= src["pertinence"] <= 1.0


# ── Matching référence exacte ────────────────────────────────────────────────

def test_exact_ref_returns_article(seeded_db: Path):
    with LegifranceRetriever(seeded_db) as r:
        articles = r.search("L.1234-1", themes=["droit_social"])
    assert len(articles) >= 1
    assert articles[0].num == "L1234-1"
    assert articles[0].pertinence == 1.0


def test_extract_legal_refs_parses_variants():
    refs = extract_legal_refs("article L.1234-1 et R1411-2 et L 145-8")
    canon = {f"{p}{n}" for p, n in refs}
    assert {"L1234-1", "R1411-2", "L145-8"}.issubset(canon)


# ── Non-hallucination : 6 questions canoniques → articles réels ──────────────

@pytest.mark.parametrize(
    "query,theme,expected_num",
    [
        ("L.1234-1 délai préavis", "droit_social", "L1234-1"),
        ("R1411-2 saisine prud'hommes", "prudhommes", "R1411-2"),
        ("L.145-8 bail commercial renouvellement", "baux_commerciaux", "L145-8"),
        ("L.225-1 société anonyme capital", "societes", "L225-1"),
        ("article 212 époux respect fidélité", "divorce_famille", "212"),
        ("256 TVA livraisons biens assujetti", "fiscal_comptable", "256"),
    ],
)
def test_six_canonical_questions_return_real_articles(
    seeded_db: Path, query: str, theme: str, expected_num: str
):
    with LegifranceRetriever(seeded_db) as r:
        articles = r.search(query, themes=[theme], top_k=5)
    assert articles, f"aucun résultat pour {query!r}"
    nums = {a.num for a in articles}
    assert expected_num in nums, (
        f"Article {expected_num} attendu pour '{query}' (thème {theme}), "
        f"obtenu : {nums}"
    )


def test_no_hallucination_all_results_exist_in_db(seeded_db: Path):
    """Aucun article retourné ne doit être inventé — tous doivent être en DB."""
    import sqlite3

    with LegifranceRetriever(seeded_db) as r:
        articles = r.search("licenciement préavis", themes=["droit_social"], top_k=10)

    conn = sqlite3.connect(seeded_db)
    try:
        for art in articles:
            row = conn.execute(
                "SELECT id FROM articles WHERE id = ?", (art.id,)
            ).fetchone()
            assert row is not None, f"article {art.id} retourné mais absent de la DB"
    finally:
        conn.close()


# ── Theme filtering ──────────────────────────────────────────────────────────

def test_theme_filter_restricts_scope(seeded_db: Path):
    with LegifranceRetriever(seeded_db) as r:
        # baux_commerciaux ne couvre QUE L145-8 de nos fixtures
        articles = r.search("bail", themes=["baux_commerciaux"], top_k=5)
    assert articles
    for a in articles:
        assert a.code_cid == "LEGITEXT000005634379"


def test_empty_theme_filter_returns_nothing_if_unknown(seeded_db: Path):
    with LegifranceRetriever(seeded_db) as r:
        articles = r.search("anything", themes=["theme_inexistant"], top_k=5)
    assert articles == []


# ── Fallback + erreur manquante ──────────────────────────────────────────────

def test_retriever_raises_when_db_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        LegifranceRetriever(tmp_path / "absent.sqlite")
