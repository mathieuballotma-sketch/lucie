"""Test : après un sync, l'AuditTrail contient une entrée `legifrance_sync`."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def test_sync_records_legifrance_sync_audit_entry(
    tmp_path: Path, sample_tarball: Path, monkeypatch
):
    # Isoler l'AuditTrail dans tmp_path
    audit_db = tmp_path / "audit.db"
    audit_salt = tmp_path / ".audit_salt"
    # Secret déterministe pour la session
    monkeypatch.setenv("AUDIT_HMAC_SECRET", "test-secret-for-ci")

    from app.services.audit_trail import AuditTrail
    from lucie_v1_standalone.knowledge_legifrance import sync

    trail = AuditTrail(db_path=str(audit_db), salt_path=str(audit_salt))
    sync_dir = tmp_path / "data"
    sync_dir.mkdir()
    sync.run_sync(
        data_dir=sync_dir,
        first_run=True,
        sample_archives=[sample_tarball],
        user="system-test",
        audit_trail=trail,
    )

    # Lire l'entrée écrite en synchrone
    conn = sqlite3.connect(audit_db)
    try:
        rows = conn.execute(
            "SELECT action, user, signature FROM audit_entries"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    action, user, signature = rows[0]
    assert action == "legifrance_sync"
    assert user == "system-test"
    assert signature  # HMAC hex non-vide
    assert len(signature) >= 32
