"""Smoke test CLI : `python -m lucie_v1_standalone --corpus <code> "query"`.

Vérifie que la branche additive `--corpus` :
  - tourne sans crash en mode --no-llm
  - produit une sortie qui mentionne le corpus chargé et au moins un article
  - retourne exit code 0 sur cas in-scope et out-of-scope

PAS de test du chemin par défaut (le pipeline droit social nécessite Ollama
et déclenche `ensure_ready` — couverture déjà assurée par les suites existantes).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "lucie_v1_standalone", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_help_mentions_corpus_flag():
    cp = _run_cli(["--help"])
    assert cp.returncode == 0
    assert "--corpus" in cp.stdout
    assert "BRANCHE ADDITIVE" in cp.stdout


def test_cli_corpus_pharma_in_scope_query():
    cp = _run_cli([
        "--corpus", "fr_pharma_ansm",
        "--no-llm",
        "puis-je faire de la publicité pour un médicament listé II ?",
    ])
    assert cp.returncode == 0, f"stderr: {cp.stderr}"
    assert "fr_pharma_ansm" in cp.stdout
    assert "L5122" in cp.stdout  # au moins un article L.5122-x dans le top
    assert "ANSM" in cp.stdout


def test_cli_corpus_pharma_out_of_scope_brevet():
    cp = _run_cli([
        "--corpus", "fr_pharma_ansm",
        "--no-llm",
        "comment déposer un brevet sur ma molécule innovante ?",
    ])
    assert cp.returncode == 0, f"stderr: {cp.stderr}"
    # La redirection brevet doit apparaître
    assert "brevet" in cp.stdout.lower() or "propriété" in cp.stdout.lower()


def test_cli_unknown_corpus_returns_error_code():
    cp = _run_cli([
        "--corpus", "zz_inexistant",
        "--no-llm",
        "test",
    ])
    assert cp.returncode == 2
    assert "introuvable" in cp.stderr.lower()
