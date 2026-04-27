"""Harness F9 — joue prompts_lucie_extended.json contre pipeline.run et applique
pass_criteria.

Lecture seule : aucune modification du pipeline, du Vérificateur, du Cerveau
Oiseaux. Le harness se contente de mesurer le comportement observable via
PipelineResponse + une mesure wall-clock.

Usage :
    python3 bench/run_legal_traps.py --output reports/baseline_f9.md
    python3 bench/run_legal_traps.py --filter LEG-ART
    python3 bench/run_legal_traps.py --model gemma4:e4b
    python3 bench/run_legal_traps.py --json reports/baseline_f9.json

Exit code : 0 si tous PASS, 1 sinon (utilisable en CI plus tard — F12 S5).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# Permettre l'exécution depuis la racine repo
sys.path.insert(0, str(Path(__file__).parent.parent))

from lucie_v1_standalone import pipeline  # noqa: E402


REPO_ROOT = Path(__file__).parent.parent
PROMPTS_PATH = Path(__file__).parent / "prompts_lucie_extended.json"
BEHAVIORS_PATH = Path(__file__).parent / "expected_behaviors.json"


# ─── Modèle de données ────────────────────────────────────────────────────────


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


@dataclass
class Case:
    id: str
    category: str
    prompt: str
    expected_behavior: str
    rule_name: str
    params: dict[str, Any]


@dataclass
class CaseResult:
    case: Case
    verdict: Verdict
    wall_clock_ms: float
    response_dict: dict[str, Any] = field(default_factory=dict)
    failed_assertions: list[str] = field(default_factory=list)
    error: Optional[str] = None


# ─── Chargement & validation ──────────────────────────────────────────────────


def load_cases(prompts_path: Path, behaviors_path: Path) -> tuple[list[Case], dict]:
    with prompts_path.open(encoding="utf-8") as f:
        prompts = json.load(f)
    with behaviors_path.open(encoding="utf-8") as f:
        behaviors = json.load(f)

    rule_names = {k for k in behaviors if not k.startswith("_")}

    cases: list[Case] = []
    for entry in prompts:
        rule = entry["pass_criteria"]["rule"]
        if rule not in rule_names:
            raise ValueError(f"{entry['id']}: rule '{rule}' inconnue dans {behaviors_path.name}")
        params = {k: v for k, v in entry["pass_criteria"].items() if k != "rule"}
        cases.append(
            Case(
                id=entry["id"],
                category=entry["category"],
                prompt=entry["prompt"],
                expected_behavior=entry["expected_behavior"],
                rule_name=rule,
                params=params,
            )
        )
    return cases, behaviors


# ─── Exécution d'un cas ───────────────────────────────────────────────────────


async def run_case(case: Case) -> tuple[Optional[Any], float, Optional[str]]:
    """Exécute pipeline.run sur le prompt du cas. Retourne (response, wall_ms, error)."""
    t0 = time.perf_counter()
    try:
        response = await pipeline.run(query=case.prompt, verbose=False)
        wall_ms = (time.perf_counter() - t0) * 1000
        return response, wall_ms, None
    except Exception as exc:  # noqa: BLE001
        wall_ms = (time.perf_counter() - t0) * 1000
        return None, wall_ms, f"{type(exc).__name__}: {exc}"


def response_to_dict(response: Any, wall_ms: float) -> dict[str, Any]:
    """Snapshot de PipelineResponse + wall-clock dans un dict pour évaluation/rapport."""
    return {
        "answer": getattr(response, "answer", "") or "",
        "citations": list(getattr(response, "citations", []) or []),
        "verifier_score": float(getattr(response, "verifier_score", 0.0)),
        "refused": bool(getattr(response, "refused", False)),
        "early_validation_triggered": getattr(response, "early_validation_triggered", None),
        "validation_details": dict(getattr(response, "validation_details", {}) or {}),
        "_wall_clock_ms": wall_ms,
    }


# ─── Évaluation des assertions ────────────────────────────────────────────────


_CITATION_NORMALIZER = re.compile(r"[\s\.\-]+")


def _normalize_article(s: str) -> str:
    return _CITATION_NORMALIZER.sub("", s).upper()


def _get_field(snapshot: dict, field_path: str) -> Any:
    """Résout un chemin pointé : 'validation_details.domain' → snapshot['validation_details']['domain']."""
    if field_path == "answer_or_citations_normalized":
        # Champ synthétique pour citation_required : concat answer + citations, normalisé.
        ans = snapshot.get("answer") or ""
        cits = snapshot.get("citations") or []
        return _normalize_article(ans + " " + " ".join(cits))
    parts = field_path.split(".")
    cur: Any = snapshot
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            cur = getattr(cur, p, None)
        if cur is None and p != parts[-1]:
            return None
    return cur


def _resolve_value(assertion: dict, params: dict) -> Any:
    """Retourne la valeur attendue : `value` direct, ou `value_from` (clé params)."""
    if "value" in assertion:
        return assertion["value"]
    if "value_from" in assertion:
        return params.get(assertion["value_from"])
    return None


def _apply_op(op: str, actual: Any, expected: Any) -> bool:
    if op == "eq":
        return actual == expected
    if op == "neq":
        return actual != expected
    if op == "lte":
        if actual is None or expected is None:
            return False
        return actual <= expected
    if op == "gte":
        if actual is None or expected is None:
            return False
        return actual >= expected
    if op == "in":
        return actual in (expected or [])
    if op == "is_none":
        return actual is None
    if op == "min_len":
        if actual is None:
            return False
        return len(actual) >= (expected or 0)
    if op == "superset_of":
        if actual is None or expected is None:
            return False
        return set(expected).issubset(set(actual))
    if op == "intersects":
        if actual is None or expected is None:
            return False
        return bool(set(actual) & set(expected))
    if op == "any_match":
        # Pour citation_required : `actual` est answer+citations normalisé, expected est list[str]
        # de codes article. PASS si au moins un code (normalisé) apparaît dans actual.
        if actual is None or not expected:
            return False
        return any(_normalize_article(code) in actual for code in expected)
    raise ValueError(f"Opérateur inconnu : {op}")


def evaluate(case: Case, snapshot: dict, registry: dict) -> tuple[Verdict, list[str]]:
    """Applique les assertions de la rule et collecte les fails. Retourne (verdict, failures)."""
    rule_spec = registry[case.rule_name]
    failures: list[str] = []
    for assertion in rule_spec["assertions"]:
        field_path = assertion["field"]
        op = assertion["op"]
        expected = _resolve_value(assertion, case.params)
        actual = _get_field(snapshot, field_path)
        ok = _apply_op(op, actual, expected)
        if not ok:
            failures.append(
                f"{field_path} {op} {expected!r} → actual={actual!r}"
            )
    verdict = Verdict.PASS if not failures else Verdict.FAIL
    return verdict, failures


# ─── Format rapport ───────────────────────────────────────────────────────────


def _summary_by_category(results: list[CaseResult]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for r in results:
        s = summary.setdefault(
            r.case.category, {"n": 0, "PASS": 0, "FAIL": 0, "ERROR": 0}
        )
        s["n"] += 1
        s[r.verdict.value] += 1
    return summary


def format_report_md(results: list[CaseResult], model_name: str) -> str:
    lines: list[str] = []
    lines.append(f"# Lucie F9 — Baseline legal traps ({model_name})")
    lines.append("")
    lines.append(f"Date : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Total cas : **{len(results)}**")
    lines.append("")

    # Résumé global
    n = len(results)
    n_pass = sum(1 for r in results if r.verdict == Verdict.PASS)
    n_fail = sum(1 for r in results if r.verdict == Verdict.FAIL)
    n_err = sum(1 for r in results if r.verdict == Verdict.ERROR)
    pct = (n_pass / n * 100) if n else 0
    lines.append(f"**Global** : {n_pass}/{n} PASS ({pct:.1f}%) · {n_fail} FAIL · {n_err} ERROR")
    lines.append("")

    # Tableau par catégorie
    lines.append("## Résumé par catégorie")
    lines.append("")
    lines.append("| Catégorie | n | PASS | FAIL | ERROR |")
    lines.append("|---|---:|---:|---:|---:|")
    for cat, s in sorted(_summary_by_category(results).items()):
        lines.append(f"| {cat} | {s['n']} | {s['PASS']} | {s['FAIL']} | {s['ERROR']} |")
    lines.append("")

    # Détail par cas
    lines.append("## Détail par cas")
    lines.append("")
    for r in results:
        c = r.case
        lines.append(f"### {c.id} — **{r.verdict.value}** ({r.wall_clock_ms:.0f} ms)")
        lines.append(f"- Catégorie : `{c.category}`")
        lines.append(f"- Règle : `{c.rule_name}`")
        lines.append(f"- Prompt : « {c.prompt} »")
        lines.append(f"- Comportement attendu : {c.expected_behavior}")
        if r.error:
            lines.append(f"- Erreur : `{r.error}`")
        else:
            ans = (r.response_dict.get("answer") or "")[:200].replace("\n", " ")
            lines.append(f"- Réponse (preview 200c) : « {ans} »")
            lines.append(f"- `refused`={r.response_dict.get('refused')}, "
                         f"`early_validation_triggered`="
                         f"{r.response_dict.get('early_validation_triggered')!r}")
            cits = r.response_dict.get("citations") or []
            lines.append(f"- citations : {cits}")
            vd = r.response_dict.get("validation_details") or {}
            lines.append(f"- validation_details : `{json.dumps(vd, ensure_ascii=False)}`")
        if r.failed_assertions:
            lines.append("- Assertions échouées :")
            for fa in r.failed_assertions:
                lines.append(f"  - `{fa}`")
        lines.append("")
    return "\n".join(lines)


def format_report_json(results: list[CaseResult]) -> str:
    out = []
    for r in results:
        out.append(
            {
                "id": r.case.id,
                "category": r.case.category,
                "rule": r.case.rule_name,
                "prompt": r.case.prompt,
                "verdict": r.verdict.value,
                "wall_clock_ms": r.wall_clock_ms,
                "response": r.response_dict,
                "failed_assertions": r.failed_assertions,
                "error": r.error,
            }
        )
    return json.dumps(out, ensure_ascii=False, indent=2)


# ─── Main ─────────────────────────────────────────────────────────────────────


async def main() -> int:
    parser = argparse.ArgumentParser(description="Harness F9 — cas piège juridiques Lucie")
    parser.add_argument("--output", type=Path, default=None,
                        help="Chemin du rapport markdown")
    parser.add_argument("--json", type=Path, default=None,
                        help="Chemin du rapport JSON (pour comparaison cross-runs)")
    parser.add_argument("--filter", default=None,
                        help="Préfixe d'ID ou de catégorie (ex: LEG-ART, mixed_trap)")
    parser.add_argument("--model", default=None,
                        help="Override LUCIE_SPEED_MODEL pour cette run")
    args = parser.parse_args()

    if args.model:
        os.environ["LUCIE_SPEED_MODEL"] = args.model

    logging.basicConfig(level=logging.WARNING)

    cases, registry = load_cases(PROMPTS_PATH, BEHAVIORS_PATH)
    if args.filter:
        flt = args.filter
        cases = [c for c in cases if c.id.startswith(flt) or c.category.startswith(flt)]
        if not cases:
            print(f"Aucun cas ne matche le filtre '{flt}'", file=sys.stderr)
            return 1

    model = os.environ.get("LUCIE_SPEED_MODEL", "default")
    print(f"Run F9 — modèle={model} — {len(cases)} cas\n")

    results: list[CaseResult] = []
    for i, case in enumerate(cases, start=1):
        print(f"[{i}/{len(cases)}] {case.id} ({case.category})…", flush=True)
        response, wall_ms, error = await run_case(case)
        if error is not None or response is None:
            results.append(CaseResult(case=case, verdict=Verdict.ERROR,
                                       wall_clock_ms=wall_ms, error=error))
            print(f"    → ERROR ({wall_ms:.0f} ms) : {error}")
            continue

        snapshot = response_to_dict(response, wall_ms)
        verdict, failures = evaluate(case, snapshot, registry)
        results.append(CaseResult(case=case, verdict=verdict,
                                   wall_clock_ms=wall_ms,
                                   response_dict=snapshot,
                                   failed_assertions=failures))
        print(f"    → {verdict.value} ({wall_ms:.0f} ms)")

    # Rapports
    md = format_report_md(results, model)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(md, encoding="utf-8")
        print(f"\nRapport markdown : {args.output}")
    else:
        print("\n" + md)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(format_report_json(results), encoding="utf-8")
        print(f"Rapport JSON : {args.json}")

    n_pass = sum(1 for r in results if r.verdict == Verdict.PASS)
    print(f"\nRésumé : {n_pass}/{len(results)} PASS")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
