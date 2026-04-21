"""Harness de benchmark perf pour Lucie v1.

Joue 10 requêtes types contre le pipeline en mesurant :
  - durée end-to-end par requête
  - durée par étape (profilage)
  - durée totale et médiane

Activation profilage via `LUCIE_PROFILE=1` (auto-activé par le script).

Usage :
    python3 scripts/bench_queries.py
    python3 scripts/bench_queries.py --output reports/baseline.md
    python3 scripts/bench_queries.py --queries reduced
    python3 scripts/bench_queries.py --model qwen2.5:3b

Pas d'effet secondaire (lecture seule sur la base, pas d'écriture).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import statistics
import sys
import time
from pathlib import Path
from typing import List, Optional

# Permettre l'exécution hors install (depuis racine repo)
sys.path.insert(0, str(Path(__file__).parent.parent))

from lucie_v1_standalone import pipeline  # noqa: E402
from lucie_v1_standalone.perf import profile_bucket  # noqa: E402


# ─── Requêtes types (10) ───────────────────────────────────────────────────────

BENCHMARK_QUERIES = [
    ("N1 salutation", "Bonjour Lucie"),
    ("N1 définition", "C'est quoi un contrat de travail ?"),
    ("N2 factuelle ref", "Délai de préavis article L1234-1"),
    ("N2 thématique", "Conditions licenciement économique"),
    ("N2 hors-scope", "Météo à Paris"),
    ("N2 article inexistant", "Que dit l'article L1234-99 du Code du travail ?"),
    ("N2 répétée (cache)", "Délai de préavis article L1234-1"),
    ("N2 multi-thèmes", "Bail commercial et TVA applicable"),
    ("N2 procédure", "Comment saisir le conseil de prud'hommes ?"),
    ("N2 synthèse", "Différence entre CDI et CDD"),
]

REDUCED_QUERIES = BENCHMARK_QUERIES[:5]


# ─── Harness ──────────────────────────────────────────────────────────────────


async def run_one(query: str) -> dict:
    """Exécute 1 requête avec profilage actif, retourne les métriques agrégées."""
    t0 = time.perf_counter()
    async with profile_bucket() as bucket:
        try:
            resp = await pipeline.run(query=query, verbose=False)
            answer = resp.answer if hasattr(resp, "answer") else str(resp)
            error = None
        except Exception as exc:  # noqa: BLE001
            answer = ""
            error = str(exc)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    steps = []
    if bucket is not None:
        for s in bucket.steps:
            steps.append({"name": s.name, "ms": s.duration_ms, "meta": s.meta})

    return {
        "elapsed_ms": elapsed_ms,
        "answer_preview": (answer or "")[:120].replace("\n", " "),
        "error": error,
        "steps": steps,
    }


def format_report(results: List[dict], labels: List[str]) -> str:
    """Produit le tableau Markdown du bench."""
    lines = ["# Bench Lucie v1 — profilage pipeline\n"]

    # Tableau résumé par requête
    lines.append("## Résumé par requête\n")
    lines.append("| # | Label | Durée (ms) | Aperçu |")
    lines.append("|---:|---|---:|---|")
    for i, (res, label) in enumerate(zip(results, labels), start=1):
        preview = res["error"] or res["answer_preview"] or "(vide)"
        lines.append(f"| {i} | {label} | {res['elapsed_ms']:.0f} | {preview[:80]} |")

    durations = [r["elapsed_ms"] for r in results]
    if durations:
        lines.append("")
        lines.append(
            f"**p50** : {statistics.median(durations):.0f} ms · "
            f"**moy** : {statistics.mean(durations):.0f} ms · "
            f"**max** : {max(durations):.0f} ms · "
            f"**n** : {len(durations)}"
        )

    # Agrégation par étape
    lines.append("\n## Agrégation par étape (somme sur toutes requêtes)\n")
    agg: dict[str, dict] = {}
    for r in results:
        for step in r["steps"]:
            entry = agg.setdefault(step["name"], {"total_ms": 0.0, "n": 0})
            entry["total_ms"] += step["ms"]
            entry["n"] += 1

    total_all = sum(e["total_ms"] for e in agg.values()) or 1.0
    lines.append("| Étape | n calls | Total (ms) | Moy/call (ms) | % total |")
    lines.append("|---|---:|---:|---:|---:|")
    for name, entry in sorted(agg.items(), key=lambda kv: -kv[1]["total_ms"]):
        pct = 100 * entry["total_ms"] / total_all
        moy = entry["total_ms"] / max(entry["n"], 1)
        lines.append(
            f"| {name} | {entry['n']} | {entry['total_ms']:.0f} | "
            f"{moy:.0f} | {pct:.1f}% |"
        )

    # Détail par requête
    lines.append("\n## Détail par requête\n")
    for i, (res, label) in enumerate(zip(results, labels), start=1):
        lines.append(f"### {i}. {label} — {res['elapsed_ms']:.0f} ms")
        if res["error"]:
            lines.append(f"> ⚠ erreur : `{res['error']}`\n")
            continue
        if not res["steps"]:
            lines.append("> (aucune étape mesurée)\n")
            continue
        lines.append("| Étape | ms | meta |")
        lines.append("|---|---:|---|")
        for s in res["steps"]:
            meta_str = ", ".join(f"{k}={v}" for k, v in s["meta"].items())
            lines.append(f"| {s['name']} | {s['ms']:.0f} | {meta_str} |")
        lines.append("")
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Bench perf pipeline Lucie v1")
    parser.add_argument("--output", type=Path, default=None,
                        help="Écrit le rapport markdown à ce chemin")
    parser.add_argument("--queries", choices=["full", "reduced"], default="full")
    parser.add_argument("--model", default=None,
                        help="Override LUCIE_SPEED_MODEL pour cette run")
    parser.add_argument("--passes", type=int, default=1,
                        help="Rejoue le set N fois dans le même process (mesure cache hits)")
    args = parser.parse_args()

    # Profilage actif par défaut dans ce harness
    os.environ.setdefault("LUCIE_PROFILE", "1")
    if args.model:
        os.environ["LUCIE_SPEED_MODEL"] = args.model

    logging.basicConfig(level=logging.WARNING)

    queries = REDUCED_QUERIES if args.queries == "reduced" else BENCHMARK_QUERIES
    base_labels = [label for label, _ in queries]
    passes = max(1, args.passes)

    results: List[dict] = []
    labels: List[str] = []
    for p in range(1, passes + 1):
        if passes > 1:
            print(f"\n=== Pass {p}/{passes} ===", flush=True)
        for i, (label, q) in enumerate(queries, start=1):
            tag = f"{label} (p{p})" if passes > 1 else label
            print(f"[{i}/{len(queries)}] {tag}…", flush=True)
            res = await run_one(q)
            print(f"    → {res['elapsed_ms']:.0f} ms", flush=True)
            results.append(res)
            labels.append(tag)

    report = format_report(results, labels)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"\nRapport écrit : {args.output}")
    else:
        print("\n" + report)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
