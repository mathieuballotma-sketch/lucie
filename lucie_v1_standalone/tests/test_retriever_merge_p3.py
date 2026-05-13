"""Tests unitaires merge retriever curatée+Légifrance — Sprint 6 P3.

POURQUOI : Sprint 6 P3 a transformé l'early-return Légifrance en merge
prioritisé (cf. ``retriever._merge_curated_legifrance``). Sans ces tests, une
régression du merge ferait silencieusement repasser les 3 FAILs SW-LECO-004/
007/010 en FAIL puisque les rapports humains ne sont relus que ponctuellement.

Couvre :
- ``_normalize_article_id`` : dédup cross-sources (curatée vs Légifrance)
- ``_title_match_bonus`` : boost titre quand tokens query matchent le titre
- ``_merge_curated_legifrance`` : priorité curatée si pertinence ≥ seuil,
  fallback Légifrance sinon, dédup, troncature à ``max_total``.
- Garde-fou anti-régression P2d-B : ``_extract_query_or_raw`` reste intact.
"""

from __future__ import annotations

import json

import pytest

from lucie_v1_standalone import retriever
from lucie_v1_standalone.retriever import (
    CURATED_STRONG_MATCH_THRESHOLD,
    _extract_query_or_raw,
    _merge_curated_legifrance,
    _normalize_article_id,
    _title_match_bonus,
)


# ─── _normalize_article_id ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("L1233-4", "l12334"),
        ("L.1233-4", "l12334"),
        ("l1233-4", "l12334"),
        (" L 1233 - 4 ", "l12334"),
        ("L1233-67", "l123367"),
        ("R1234-2", "r12342"),
    ],
)
def test_normalize_article_id_canonicalizes(raw: str, expected: str) -> None:
    """Différentes formes du même article produisent la même clé normalisée."""
    assert _normalize_article_id(raw) == expected


def test_normalize_distinguishes_different_articles() -> None:
    """Deux articles distincts gardent des clés distinctes après normalisation."""
    assert _normalize_article_id("L1233-4") != _normalize_article_id("L1233-5")
    assert _normalize_article_id("L1233-67") != _normalize_article_id("L1233-68")


# ─── _title_match_bonus ───────────────────────────────────────────────────────

def test_title_match_bonus_zero_when_no_overlap() -> None:
    """Pas de bonus quand aucun token query n'est dans le titre."""
    bonus = _title_match_bonus(
        ["motif", "économique"], "Convocation à l'entretien préalable"
    )
    assert bonus == 0.0


def test_title_match_bonus_scales_with_matches() -> None:
    """Bonus croît avec le nombre de tokens query distincts dans le titre."""
    title = "Mention du motif économique dans la lettre"
    # tokens query : 3 matches distincts (mention, motif, lettre)
    bonus = _title_match_bonus(
        ["mentions", "obligatoires", "lettre", "licenciement", "économique", "motif"],
        title,
    )
    # 3 matches × 0.15 = 0.45, plafonné à 0.6 par CURATED_TITLE_BONUS_MAX
    assert 0.4 <= bonus <= 0.6


def test_title_match_bonus_respects_cap() -> None:
    """Le bonus ne dépasse jamais le plafond, même avec beaucoup de matches."""
    title = "ordre licenciements critères charges famille ancienneté handicap"
    query_tokens = title.split()  # tous les tokens matchent
    bonus = _title_match_bonus(query_tokens, title)
    assert bonus <= 0.6


# ─── _merge_curated_legifrance ────────────────────────────────────────────────

def _src(article_id: str, pertinence: float) -> dict:
    return {"id": article_id, "titre": f"Article {article_id}", "pertinence": pertinence}


def test_merge_prioritizes_curated_when_strong_match() -> None:
    """Curatée pertinence ≥ seuil → curatée en tête, Légifrance en complément."""
    curated = [_src("L1233-4", 0.99), _src("L1233-11", 0.55)]
    legi = [_src("L1233-10", 0.95), _src("L1233-31", 0.94)]
    merged = _merge_curated_legifrance(curated, legi, max_total=3)
    assert merged[0]["id"] == "L1233-4"  # priorité curatée
    assert len(merged) == 3
    ids = [s["id"] for s in merged]
    assert "L1233-4" in ids and "L1233-10" in ids


def test_merge_prioritizes_legifrance_when_curated_weak() -> None:
    """Curatée premier item < seuil → Légifrance en tête."""
    curated = [_src("L1233-12", 0.43), _src("L1233-9", 0.40)]
    legi = [_src("L1233-11", 0.95), _src("L1233-15", 0.93)]
    merged = _merge_curated_legifrance(curated, legi, max_total=3)
    assert merged[0]["id"] == "L1233-11"  # Légifrance en tête car curatée < seuil
    ids = [s["id"] for s in merged]
    assert "L1233-12" in ids or "L1233-9" in ids  # curatée en complément


def test_merge_dedup_cross_sources() -> None:
    """Un même article (formes différentes) n'apparaît qu'une fois après merge."""
    curated = [_src("L1233-65", 0.99)]
    legi = [_src("L.1233-65", 0.80), _src("L1233-67", 0.75)]
    merged = _merge_curated_legifrance(curated, legi, max_total=5)
    assert len(merged) == 2  # L.1233-65 et L1233-65 = même article (dédup)


def test_merge_respects_max_total() -> None:
    """Le résultat est tronqué à ``max_total`` même si plus d'items disponibles."""
    curated = [_src(f"C{i}", 0.99) for i in range(5)]
    legi = [_src(f"L{i}", 0.90) for i in range(5)]
    merged = _merge_curated_legifrance(curated, legi, max_total=3)
    assert len(merged) == 3


def test_merge_empty_inputs_returns_empty() -> None:
    """Merge de listes vides ne lève pas et renvoie []."""
    assert _merge_curated_legifrance([], [], max_total=3) == []


def test_threshold_constant_documented() -> None:
    """Le seuil CURATED_STRONG_MATCH_THRESHOLD est exposé et raisonnable.

    Si la valeur change, ce test rappelle que le comportement merge en
    dépend — toute modification doit être justifiée par mesure empirique.
    """
    assert 0.3 <= CURATED_STRONG_MATCH_THRESHOLD <= 0.9


# ─── Garde-fou anti-régression P2d-B ──────────────────────────────────────────

def test_regression_p2d_b_extract_query_intact() -> None:
    """``_extract_query_or_raw`` doit toujours extraire ``query`` du wrapper.

    Sprint 6 P2d-B (commit 1087363) avait fixé un bug où le retriever
    tokenisait le JSON wrapper entier, polluant BM25 avec
    ``type_document``, ``requete``, ``query``. Ce test garantit qu'une
    régression P3 ne remette pas ce comportement en cause.
    """
    wrapper = json.dumps(
        {"type_document": "requete", "query": "Quel est le seuil PSE ?"}
    )
    assert _extract_query_or_raw(wrapper) == "Quel est le seuil PSE ?"


def test_regression_p2d_b_extract_fallback_on_raw_text() -> None:
    """Texte brut (pas JSON) → renvoyé inchangé (fallback gracieux P2d-B)."""
    raw = "Texte brut non JSON"
    assert _extract_query_or_raw(raw) == raw


# ─── Régression bug substring P3 ──────────────────────────────────────────────

def test_regression_p3_curated_no_substring_false_positive() -> None:
    """Régression : ``ref in content_upper`` matchait L.1233-3 comme sous-chaîne.

    Bug 2026-05-13 (SW-LECO-003) : la query « selon l'article L.1233-3 »
    ramenait CHANGELOG/L1233-1/L1233-12 comme matchs "exacts" pertinence=1.0
    parce que ces fichiers MENTIONNENT L.1233-3 en référence croisée
    (CHANGELOG: "L.1233-3 (motifs détaillés)" ; L1233-1: "L.1233-3 (détail
    des motifs)" ; L1233-12: "L.1233-30" → substring L.1233-3). L1233-3 lui-même
    n'était jamais atteint (3 slots saturés avant lui dans l'index trié).

    Fix : matching strict par ID normalisé via ``_normalize_article_id`` —
    seul l'article qui EST réellement la référence est retourné en match
    exact.
    """
    import asyncio
    import json

    from lucie_v1_standalone import retriever

    retriever.invalidate_index()

    async def _run() -> list:
        wrapped = json.dumps(
            {
                "type_document": "requete",
                "query": "Quelles sont les conditions du motif économique selon l'article L.1233-3 ?",
            }
        )
        out = await retriever.handle(wrapped)
        return json.loads(out).get("sources", [])

    sources = asyncio.run(_run())
    # L.1233-3 doit être le PREMIER résultat (pertinence=1.0 — matching strict ID)
    assert sources, "Aucune source retournée pour query référençant L.1233-3"
    assert _normalize_article_id(sources[0]["id"]) == _normalize_article_id("L.1233-3"), (
        f"Top result attendu = L1233-3, obtenu = {sources[0]['id']} "
        "— bug substring revenu ?"
    )
    # Aucun CHANGELOG/README ne doit être en match strict pertinence=1.0
    for s in sources:
        if s.get("pertinence") == 1.0:
            assert _normalize_article_id(s["id"]) == _normalize_article_id("L.1233-3"), (
                f"Faux positif pertinence=1.0 : {s['id']} (devrait être L1233-3 seul)"
            )
