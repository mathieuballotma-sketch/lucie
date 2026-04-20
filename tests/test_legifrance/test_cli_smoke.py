"""Smoke-test CLI : le script `scripts/legifrance_sync.py` tourne end-to-end."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "legifrance_sync.py"


def test_cli_status_when_empty(tmp_path: Path):
    """`--status` sur répertoire vide → level=missing."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--status", "--data-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    assert info["level"] == "missing"


def test_cli_sample_mode_end_to_end(
    tmp_path: Path, sample_tarball: Path
):
    """`--sample` + `--first-run` + `--no-audit` applique le tarball fixture."""
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--first-run",
            "--sample", str(sample_tarball),
            "--data-dir", str(tmp_path),
            "--no-audit",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["articles_added"] == 6
    assert (tmp_path / "legi.sqlite").exists()
    assert (tmp_path / "last_sync.json").exists()


def test_cli_dry_run_does_not_write(tmp_path: Path, sample_tarball: Path):
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--first-run",
            "--sample", str(sample_tarball),
            "--data-dir", str(tmp_path),
            "--dry-run",
            "--no-audit",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "legi.sqlite").exists()
    assert not (tmp_path / "last_sync.json").exists()
