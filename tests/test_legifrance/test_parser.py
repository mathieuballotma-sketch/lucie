"""Tests parser DILA → SQLite."""

from __future__ import annotations

from pathlib import Path

import pytest

from lucie_v1_standalone.knowledge_legifrance import parser


def test_apply_sample_creates_six_articles(tmp_path: Path, sample_tarball: Path):
    db_path = tmp_path / "legi.sqlite"
    conn = parser.init_db(db_path)
    try:
        stats = parser.apply_archive(sample_tarball, conn)
        assert stats.articles_added == 6
        assert stats.articles_updated == 0
        assert stats.parse_errors == 0
        assert stats.codes_upserted == 4

        rows = conn.execute(
            "SELECT num, num_prefix, num_numeric, etat FROM articles ORDER BY num"
        ).fetchall()
        nums = {r[0] for r in rows}
        assert nums == {"L1234-1", "R1411-2", "L145-8", "L225-1", "212", "256"}
        # Tous en VIGUEUR
        assert all(r[3] == "VIGUEUR" for r in rows)

        # Prefix et numeric extraits correctement
        prefix_map = {r[0]: (r[1], r[2]) for r in rows}
        assert prefix_map["L1234-1"] == ("L", 1234)
        assert prefix_map["R1411-2"] == ("R", 1411)
        assert prefix_map["L145-8"] == ("L", 145)
        assert prefix_map["212"] == ("", 212)
    finally:
        conn.close()


def test_apply_twice_is_idempotent(tmp_path: Path, sample_tarball: Path):
    db_path = tmp_path / "legi.sqlite"
    conn = parser.init_db(db_path)
    try:
        parser.apply_archive(sample_tarball, conn)
        stats = parser.apply_archive(sample_tarball, conn)
        # Deuxième passe → upsert : tous les articles sont "updated"
        assert stats.articles_added == 0
        assert stats.articles_updated == 6
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        assert count == 6
    finally:
        conn.close()


def test_codes_metadata_populated(tmp_path: Path, sample_tarball: Path):
    db_path = tmp_path / "legi.sqlite"
    conn = parser.init_db(db_path)
    try:
        parser.apply_archive(sample_tarball, conn)
        rows = conn.execute(
            "SELECT cid, titre FROM codes ORDER BY cid"
        ).fetchall()
        titres = {cid: titre for cid, titre in rows}
        assert titres["LEGITEXT000006072050"] == "Code du travail"
        assert titres["LEGITEXT000005634379"] == "Code de commerce"
    finally:
        conn.close()


def test_fts5_populated_via_triggers(tmp_path: Path, sample_tarball: Path):
    db_path = tmp_path / "legi.sqlite"
    conn = parser.init_db(db_path)
    try:
        parser.apply_archive(sample_tarball, conn)
        # FTS5 indexe automatiquement via trigger articles_fts_ai
        rows = conn.execute(
            "SELECT num FROM articles_fts WHERE articles_fts MATCH 'préavis'"
        ).fetchall()
        nums = {r[0] for r in rows}
        assert "L1234-1" in nums
    finally:
        conn.close()


def test_apply_suppression_list(
    tmp_path: Path, sample_tarball: Path, incremental_tarball: Path
):
    db_path = tmp_path / "legi.sqlite"
    conn = parser.init_db(db_path)
    try:
        parser.apply_archive(sample_tarball, conn)
        assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 6
        deleted = parser.apply_suppression_list(incremental_tarball, conn)
        # L'incrémental supprime R1411-2
        assert deleted == 1
        remaining = conn.execute("SELECT num FROM articles").fetchall()
        remaining_nums = {r[0] for r in remaining}
        assert "R1411-2" not in remaining_nums
    finally:
        conn.close()


def test_parse_malformed_xml_raises():
    with pytest.raises(parser.ParseError):
        parser.parse_article_xml(b"<not-closed")


def test_parse_article_without_cid_raises():
    xml = b"""<?xml version="1.0"?>
<ARTICLE><META><META_COMMUN><ID>LEGIARTI000000000001</ID></META_COMMUN>
<META_SPEC><META_ARTICLE><NUM>L1</NUM><ETAT>VIGUEUR</ETAT></META_ARTICLE></META_SPEC></META>
<BLOC_TEXTUEL><CONTENU>t</CONTENU></BLOC_TEXTUEL></ARTICLE>"""
    with pytest.raises(parser.ParseError):
        parser.parse_article_xml(xml)
