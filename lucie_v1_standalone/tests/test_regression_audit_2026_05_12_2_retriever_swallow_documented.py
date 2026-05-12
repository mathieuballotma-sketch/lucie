"""Régression audit 2026-05-12 P0 #2 — retriever._build_index KB read swallow.

POURQUOI : avant l'audit, retriever._build_index() avalait silencieusement
les erreurs de lecture KB via `except Exception: continue`. Un .md corrompu
disparaissait sans trace — le curateur KB n'avait aucun moyen de savoir
qu'une curation manuelle était due. Ce test verrouille le log.warning.

Source : Audit qualité lucie_v1_standalone 2026-05-12 (hash d35f4a52...).
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest


def test_unreadable_kb_file_logs_warning_and_skips(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fichier .md illisible → log.warning + index continue sans cette entrée.

    Setup : on crée 2 .md dans une KB tmp, dont un avec des octets invalides
    UTF-8 (qui lèveront UnicodeDecodeError au read_text). Le fichier valide
    doit être indexé, l'invalide skippé avec un log.warning explicite.
    """
    from lucie_v1_standalone import retriever

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "ok.md").write_text("contenu ok L.1233-3", encoding="utf-8")
    bad = kb / "bad.md"
    bad.write_bytes(b"\xff\xfe invalid utf-8 \xc0\xc1 garbage")

    monkeypatch.setattr(retriever, "KNOWLEDGE_BASE_PATH", kb)
    monkeypatch.setattr(retriever, "_index", None)

    caplog.set_level(logging.WARNING, logger="lucie_v1_standalone.retriever")

    index = retriever._build_index()

    ids = {entry["id"] for entry in index}
    assert "ok" in ids, "valid file should be indexed"
    assert "bad" not in ids, "unreadable file should be skipped"
    warns = [
        r for r in caplog.records
        if r.levelname == "WARNING" and "KB file unreadable" in r.getMessage()
    ]
    assert len(warns) == 1, (
        f"Expected exactly 1 WARNING log for unreadable file, got {len(warns)}"
    )


def test_valid_kb_does_not_log_warning(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path : tous fichiers lisibles → pas de log.warning."""
    from lucie_v1_standalone import retriever

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("article L.1234-1", encoding="utf-8")
    (kb / "b.md").write_text("article L.1234-2", encoding="utf-8")

    monkeypatch.setattr(retriever, "KNOWLEDGE_BASE_PATH", kb)
    monkeypatch.setattr(retriever, "_index", None)

    caplog.set_level(logging.WARNING, logger="lucie_v1_standalone.retriever")
    index = retriever._build_index()

    assert len(index) == 2
    assert not [
        r for r in caplog.records
        if r.levelname == "WARNING" and "KB file unreadable" in r.getMessage()
    ]
