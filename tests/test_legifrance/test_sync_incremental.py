"""Tests sync orchestrateur + diff (add / update / delete)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from lucie_v1_standalone.knowledge_legifrance import sync


def test_run_sync_first_run_with_sample_creates_db(
    tmp_path: Path, sample_tarball: Path
):
    result = sync.run_sync(
        data_dir=tmp_path,
        first_run=True,
        sample_archives=[sample_tarball],
        audit_trail=None,
    )
    assert result.articles_added == 6
    assert result.articles_updated == 0
    assert result.articles_deleted == 0
    assert result.parse_errors == 0
    assert (tmp_path / "legi.sqlite").exists()
    assert (tmp_path / "last_sync.json").exists()
    last = json.loads((tmp_path / "last_sync.json").read_text())
    assert last["articles_added"] == 6
    assert last["db_sha256"] == result.db_sha256
    # Theme counts non-vides
    assert any(v > 0 for v in result.theme_counts.values())


def test_run_sync_incremental_detects_update_and_delete(
    tmp_path: Path, sample_tarball: Path, incremental_tarball: Path
):
    # 1er sync : full
    sync.run_sync(
        data_dir=tmp_path,
        first_run=True,
        sample_archives=[sample_tarball],
        audit_trail=None,
    )
    # 2e sync : incrémental (modifie L1234-1, supprime R1411-2)
    result = sync.run_sync(
        data_dir=tmp_path,
        sample_archives=[incremental_tarball],
        audit_trail=None,
    )
    # R1411-2 supprimé via liste_suppression
    assert result.articles_deleted == 1
    # L1234-1 modifié → updated >= 1 (les autres sont réinsérés = updated aussi
    # car `apply_archive` ne compare pas le contenu, seul le mtime change)
    assert result.articles_updated >= 1

    # Vérifier que L1234-1 a bien le nouveau texte
    conn = sqlite3.connect(tmp_path / "legi.sqlite")
    try:
        row = conn.execute(
            "SELECT texte FROM articles WHERE num = 'L1234-1'"
        ).fetchone()
        assert "Texte modifié" in row[0]
        # R1411-2 est bien supprimé
        row = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE num = 'R1411-2'"
        ).fetchone()
        assert row[0] == 0
    finally:
        conn.close()


def test_run_sync_dry_run_does_not_write_db(tmp_path: Path, sample_tarball: Path):
    result = sync.run_sync(
        data_dir=tmp_path,
        first_run=True,
        dry_run=True,
        sample_archives=[sample_tarball],
        audit_trail=None,
    )
    assert result.articles_added == 0
    assert not (tmp_path / "legi.sqlite").exists()
    assert not (tmp_path / "last_sync.json").exists()


def test_legifrance_freshness_returns_missing_when_no_sync(tmp_path: Path):
    info = sync.legifrance_freshness(tmp_path)
    assert info["level"] == "missing"
    assert info["last_sync"] is None


def test_legifrance_freshness_after_sync_is_ok(
    tmp_path: Path, sample_tarball: Path
):
    sync.run_sync(
        data_dir=tmp_path,
        first_run=True,
        sample_archives=[sample_tarball],
        audit_trail=None,
    )
    info = sync.legifrance_freshness(tmp_path)
    assert info["level"] == "ok"
    assert info["last_sync"] is not None
    assert info["age_days"] == 0


def test_diff_summary_tronque_audit_lines(
    tmp_path: Path, sample_tarball: Path
):
    """Le résumé d'audit doit respecter la limite de 50 lignes."""
    result = sync.run_sync(
        data_dir=tmp_path,
        first_run=True,
        sample_archives=[sample_tarball],
        audit_trail=None,
    )
    assert len(result.audit_summary) <= 50
    # Doit contenir les compteurs
    joined = "\n".join(result.audit_summary)
    assert "articles ajoutés" in joined
