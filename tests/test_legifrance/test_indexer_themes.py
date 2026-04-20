"""Tests indexer thème → articles."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from lucie_v1_standalone.knowledge_legifrance import indexer


def _themes_for(conn: sqlite3.Connection, article_id: str) -> set[str]:
    cur = conn.execute(
        "SELECT theme_id FROM articles_by_theme WHERE article_id = ?",
        (article_id,),
    )
    return {r[0] for r in cur.fetchall()}


def test_load_theme_mapping_v1_has_six_themes():
    mapping = indexer.load_theme_mapping()
    assert mapping["version"] in ("1.0", 1, 1.0)
    themes = set(mapping["themes"].keys())
    assert themes == {
        "droit_social",
        "baux_commerciaux",
        "divorce_famille",
        "societes",
        "prudhommes",
        "fiscal_comptable",
    }


def test_reindex_assigns_articles_to_correct_themes(seeded_db: Path):
    conn = sqlite3.connect(seeded_db)
    try:
        total_indexed = conn.execute(
            "SELECT COUNT(*) FROM articles_by_theme"
        ).fetchone()[0]
        assert total_indexed >= 6  # au moins un mapping par article

        # L1234-1 (Code du travail, range L1000-1999) → droit_social
        themes = _themes_for(conn, "LEGIARTI000090001234")
        assert "droit_social" in themes

        # R1411-2 → droit_social ET prudhommes (range R1411-1499 dans
        # prudhommes + prefix R dans droit_social L1000-1999 mais prefix
        # R range 1000-1999 *oui* car 1411 ∈ [1000,1999])
        themes = _themes_for(conn, "LEGIARTI000090001411")
        assert "prudhommes" in themes
        assert "droit_social" in themes

        # L145-8 (Code de commerce, L145-145) → baux_commerciaux
        themes = _themes_for(conn, "LEGIARTI000090145008")
        assert "baux_commerciaux" in themes

        # L225-1 (Code de commerce, L210-260) → societes
        themes = _themes_for(conn, "LEGIARTI000090225001")
        assert "societes" in themes

        # Art. 212 (Code civil, range 212-515) → divorce_famille
        themes = _themes_for(conn, "LEGIARTI000090000212")
        assert "divorce_famille" in themes

        # Art. 256 (CGI, range large 1-99999) → fiscal_comptable
        themes = _themes_for(conn, "LEGIARTI000090000256")
        assert "fiscal_comptable" in themes
    finally:
        conn.close()


def test_reindex_is_idempotent(seeded_db: Path):
    """Relancer reindex_themes doit donner exactement le même nombre de rows."""
    conn = sqlite3.connect(seeded_db)
    try:
        counts_1 = indexer.reindex_themes(conn)
        total_1 = conn.execute(
            "SELECT COUNT(*) FROM articles_by_theme"
        ).fetchone()[0]
        counts_2 = indexer.reindex_themes(conn)
        total_2 = conn.execute(
            "SELECT COUNT(*) FROM articles_by_theme"
        ).fetchone()[0]
        assert counts_1 == counts_2
        assert total_1 == total_2
    finally:
        conn.close()
