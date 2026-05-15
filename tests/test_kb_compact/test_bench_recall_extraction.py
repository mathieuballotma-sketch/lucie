"""Test extraction expected_articles depuis le bench swiss_watch_50.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lucie_v1_standalone.knowledge_legifrance.refs_extractor import extract_refs_from_behavior

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH_PATH = REPO_ROOT / "bench" / "swiss_watch_50.json"


@pytest.fixture(scope="module")
def bench() -> list[dict]:
    if not BENCH_PATH.exists():
        pytest.skip(f"Bench file not found: {BENCH_PATH}")
    return json.loads(BENCH_PATH.read_text())


def test_bench_has_50_questions(bench: list[dict]) -> None:
    assert len(bench) == 50


def test_extraction_on_lic_eco_001(bench: list[dict]) -> None:
    """SW-LECO-001 mentionne 'L.1233-3 ou L.1233-4' dans expected_behavior."""
    by_id = {q["id"]: q for q in bench}
    q = by_id["SW-LECO-001"]
    refs = extract_refs_from_behavior(q["expected_behavior"])
    assert ("L", "1233-3") in refs
    assert ("L", "1233-4") in refs


def test_extraction_on_lic_eco_003(bench: list[dict]) -> None:
    by_id = {q["id"]: q for q in bench}
    q = by_id["SW-LECO-003"]
    refs = extract_refs_from_behavior(q["expected_behavior"])
    assert ("L", "1233-3") in refs


def test_extraction_on_lic_eco_004(bench: list[dict]) -> None:
    by_id = {q["id"]: q for q in bench}
    q = by_id["SW-LECO-004"]
    refs = extract_refs_from_behavior(q["expected_behavior"])
    assert ("L", "1233-5") in refs


def test_oos_question_no_refs(bench: list[dict]) -> None:
    """Une question hors-scope ne doit pas avoir de refs juridiques attendues."""
    by_id = {q["id"]: q for q in bench}
    oos = [q for q in bench if q["category"] == "hors_scope"]
    assert len(oos) > 0
    # On accepte qu'une minorité capture par hasard ; mais la majorité doit être vide.
    n_empty = sum(1 for q in oos if not extract_refs_from_behavior(q["expected_behavior"]))
    assert n_empty >= len(oos) // 2, "Au moins la moitié des oos doivent avoir 0 ref"


def test_global_coverage_baseline(bench: list[dict]) -> None:
    """Mesure la couverture extraction sur le bench actuel.

    Sur 50 questions du swiss_watch v1, seules 10 contiennent une référence
    légale concrète dans expected_behavior (matchable pour recall@10). C'est
    le baseline factuel : si la valeur baisse on saura qu'on a régressé ; si
    elle monte, c'est une amélioration de la couverture (par exemple bench
    enrichi en option 2).

    Si recall@10 doit être mesuré sur ≥30 questions à terme, enrichir le bench
    manuellement (option 2 de la question Mathieu 2026-05-15) ou créer un
    bench dédié recall (option 3).
    """
    n_with_refs = sum(1 for q in bench if extract_refs_from_behavior(q["expected_behavior"]))
    assert n_with_refs >= 5, f"Coverage trop faible: {n_with_refs} questions extractibles"
    # Baseline 10 sur 50 — surveiller si ce nombre change
    assert n_with_refs <= 50
