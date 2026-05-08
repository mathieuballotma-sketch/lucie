"""
Tests UI pour le bouton Audit PAF (brique N10).

Vérifie les helpers UI (sans dépendance NSSavePanel/NSAlert) :
- chemin DB canonique
- format du nom de fichier suggéré
- wrapper d'export : succès, échec disque, échec permission
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.ui.audit_export import (
    default_audit_db_path,
    default_export_filename,
    export_to_path,
)
from app.services.audit_trail import AuditTrail


# ─── Default paths/filenames ─────────────────────────────────────────────────

def test_default_audit_db_path_is_inside_data_audit() -> None:
    p = default_audit_db_path()
    assert p.name == "hud.db"
    assert "audit" in p.parts


def test_default_export_filename_uses_iso_date() -> None:
    fn = default_export_filename(datetime.date(2026, 4, 28))
    assert fn == "beaume_audit_2026-04-28.csv"


def test_default_export_filename_uses_today_when_none() -> None:
    fn = default_export_filename()
    assert fn.startswith("beaume_audit_")
    assert fn.endswith(".csv")
    # Format YYYY-MM-DD entre les deux
    middle = fn[len("beaume_audit_"):-len(".csv")]
    datetime.date.fromisoformat(middle)


# ─── export_to_path success ──────────────────────────────────────────────────

def test_export_to_path_success_with_real_audit_trail(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUDIT_HMAC_SECRET", "test-secret-for-determinism")
    db_path = tmp_path / "audit.db"
    salt_path = tmp_path / "salt"
    trail = AuditTrail(db_path=db_path, salt_path=salt_path)

    target = tmp_path / "export.csv"
    success, message = export_to_path(trail, target)

    assert success is True
    assert "✓" in message
    assert str(target) in message
    assert target.exists()
    content = target.read_text()
    # Header PAF présent
    assert "Date" in content
    assert "Signature" in content


def test_export_to_path_invokes_export_paf_csv() -> None:
    mock_trail = MagicMock()
    target = "/tmp/some_export.csv"
    export_to_path(mock_trail, target)
    mock_trail.export_paf_csv.assert_called_once()
    kwargs = mock_trail.export_paf_csv.call_args.kwargs
    # output passé en argument nommé
    assert "output" in kwargs
    assert Path(kwargs["output"]) == Path(target)


# ─── export_to_path failure modes ────────────────────────────────────────────

def test_export_to_path_handles_permission_error_gracefully() -> None:
    mock_trail = MagicMock()
    mock_trail.export_paf_csv.side_effect = PermissionError("Operation not permitted")
    success, message = export_to_path(mock_trail, "/root/forbidden.csv")
    assert success is False
    assert "Permission" in message
    assert "✗" in message


def test_export_to_path_handles_os_error_gracefully() -> None:
    mock_trail = MagicMock()
    mock_trail.export_paf_csv.side_effect = OSError("No space left on device")
    success, message = export_to_path(mock_trail, "/tmp/full.csv")
    assert success is False
    assert "disque" in message.lower() or "erreur" in message.lower()


def test_export_to_path_handles_unknown_error_gracefully() -> None:
    mock_trail = MagicMock()
    mock_trail.export_paf_csv.side_effect = RuntimeError("DB locked")
    success, message = export_to_path(mock_trail, "/tmp/x.csv")
    assert success is False
    assert "✗" in message
