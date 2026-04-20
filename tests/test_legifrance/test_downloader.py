"""Tests downloader (parsing HTML, checksum, sync plan)."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pytest

from lucie_v1_standalone.knowledge_legifrance import downloader


SAMPLE_INDEX_HTML = """
<!DOCTYPE html>
<html><head><title>Index of /OPENDATA/LEGI/</title></head>
<body><h1>Index of /OPENDATA/LEGI/</h1>
<a href="Freemium_legi_global_20260101-000000.tar.gz">Freemium_legi_global_20260101-000000.tar.gz</a>
<a href="LEGI_20260115-210000.tar.gz">LEGI_20260115-210000.tar.gz</a>
<a href="LEGI_20260118-210500.tar.gz">LEGI_20260118-210500.tar.gz</a>
<a href="README.txt">README.txt</a>
<a href="not-an-archive.gz">not-an-archive.gz</a>
</body></html>
"""


def test_parse_index_extracts_known_archives():
    archives = downloader.parse_index_html(SAMPLE_INDEX_HTML)
    assert len(archives) == 3
    assert [a.name for a in archives] == [
        "Freemium_legi_global_20260101-000000.tar.gz",
        "LEGI_20260115-210000.tar.gz",
        "LEGI_20260118-210500.tar.gz",
    ]


def test_parse_index_classifies_full_vs_incremental():
    archives = downloader.parse_index_html(SAMPLE_INDEX_HTML)
    assert archives[0].kind == "full"
    assert archives[0].is_full is True
    assert archives[1].kind == "incremental"
    assert archives[2].kind == "incremental"


def test_parse_index_parses_timestamps():
    archives = downloader.parse_index_html(SAMPLE_INDEX_HTML)
    assert archives[0].timestamp == datetime(2026, 1, 1, 0, 0, 0)
    assert archives[1].timestamp == datetime(2026, 1, 15, 21, 0, 0)
    assert archives[2].timestamp == datetime(2026, 1, 18, 21, 5, 0)


def test_parse_index_ignores_non_conforming():
    archives = downloader.parse_index_html(
        '<a href="Weird_file_name.tar.gz">w</a><a href="LEGI_20260118-21.tar.gz">l</a>'
    )
    assert archives == []


def test_compute_sha256_matches_stdlib(tmp_path: Path):
    file_path = tmp_path / "data.bin"
    file_path.write_bytes("hello Légifrance".encode("utf-8"))
    expected = hashlib.sha256("hello Légifrance".encode("utf-8")).hexdigest()
    assert downloader.compute_sha256(file_path) == expected


def test_select_sync_plan_first_run_takes_last_full_plus_incrementals():
    archives = downloader.parse_index_html(SAMPLE_INDEX_HTML)
    plan = downloader.select_sync_plan(archives, last_sync=None)
    assert len(plan) == 3
    assert plan[0].is_full is True
    # Les incrémentaux postérieurs au full sont inclus dans l'ordre chronologique
    assert [a.name for a in plan[1:]] == [
        "LEGI_20260115-210000.tar.gz",
        "LEGI_20260118-210500.tar.gz",
    ]


def test_select_sync_plan_incremental_filters_since():
    archives = downloader.parse_index_html(SAMPLE_INDEX_HTML)
    since = datetime(2026, 1, 15, 21, 0, 0)
    plan = downloader.select_sync_plan(archives, last_sync=since)
    # Uniquement l'archive strictement > since
    assert [a.name for a in plan] == ["LEGI_20260118-210500.tar.gz"]


def test_select_sync_plan_returns_empty_when_no_full_at_first_run():
    incrementals_only = [
        a
        for a in downloader.parse_index_html(SAMPLE_INDEX_HTML)
        if not a.is_full
    ]
    plan = downloader.select_sync_plan(incrementals_only, last_sync=None)
    assert plan == []


def test_download_verifies_checksum_and_raises_on_mismatch(
    tmp_path: Path, monkeypatch
):
    """Download stubbé : on vérifie la branche checksum-mismatch."""
    payload = b"corrupted"
    correct_sha = hashlib.sha256(payload).hexdigest()
    wrong_sha = "0" * 64

    class _FakeResponse:
        status = 200

        def __init__(self, data: bytes):
            self._data = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n: int = 0) -> bytes:
            if not self._data:
                return b""
            if n and len(self._data) > n:
                out, self._data = self._data[:n], self._data[n:]
                return out
            out, self._data = self._data, b""
            return out

    def _fake_urlopen(req, timeout: int = 0):
        return _FakeResponse(payload)

    monkeypatch.setattr(
        downloader.urllib.request, "urlopen", _fake_urlopen
    )

    archive = downloader.RemoteArchive(
        name="LEGI_20260101-000000.tar.gz",
        kind="incremental",
        timestamp=datetime(2026, 1, 1),
        url="https://example.test/fake.tar.gz",
    )
    with pytest.raises(downloader.CorruptedArchiveError):
        downloader.download(
            archive, tmp_path, expected_sha256=wrong_sha
        )

    # Avec le bon hash : pas d'exception
    dest = downloader.download(archive, tmp_path, expected_sha256=correct_sha)
    assert dest.read_bytes() == payload
