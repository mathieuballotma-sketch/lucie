"""Bench comparatif des modèles « speed » (niveaux 1/2).

Compare sur un jeu réduit de requêtes factuelles :
  - gemma4:e4b (baseline, plan)
  - qwen2.5:3b
  - llama3.2:3b

Pour chaque modèle × requête :
  - durée end-to-end pipeline (ms)
  - tokens générés (eval_count)
  - vitesse (tokens/s, depuis eval_count / eval_ms Ollama)
  - verifier_score (0.0-1.0) de la réponse
  - preview de la réponse (80 car.)

Décision : le plus rapide avec verifier_score moyen >= 0.7 devient SPEED_MODEL par défaut.

Usage :
    python3 scripts/bench_models.py
    python3 scripts/bench_models.py --output reports/bench_models.md
    python3 scripts/bench_models.py --models gemma4:e4b,qwen2.5:3b
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
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

from lucie_v1_standalone import pipeline  # noqa: E402
from lucie_v1_standalone.perf import profile_bucket  # noqa: E402


DEFAULT_MODELS = ["gemma4:e4b", "qwen2.5:3b", "llama3.2:3b"]

# Jeu réduit : 5 requêtes factuelles qui passent par le LLM (niveau 2 surtout).
BENCH_QUERIES = [
    ("N2 factuelle ref", "Délai de préavis article L1234-1"),
    ("N2 thématique", "Conditions licenciement économique"),
    ("N2 procédure", "Comment saisir le conseil de prud'hommes ?"),
    ("N2 synthèse", "Différence entre CDI et CDD"),
    ("N2 hors-scope", "Météo à Paris"),
]


async def run_one(query: str) -> dict:
    t0 = time.perf_counter()
    async with profile_bucket() as bucket:
        try:
            resp = await pipeline.run(query=query, verbose=False)
            answer = resp.answer or ""
            score = float(getattr(resp, "verifier_score", 0.0) or 0.0)
            error = None
        except Exception as exc:  # noqa: BLE001
            answer = ""
            score = 0.0
            error = str(exc)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    eval_count = 0
    eval_ms = 0.0
    prompt_tokens = 0
    ollama_ms_total = 0.0

    if bucket is not None:
        for s in bucket.steps:
            if s.name.startswith("ollama."):
                meta = s.meta or {}
                eval_count += int(meta.get("out_tokens", 0) or 0)
                eval_ms += float(meta.get("eval_ms", 0) or 0)
                prompt_tokens += int(meta.get("prompt_tokens", 0) or 0)
                ollama_ms_total += s.duration_ms

    toks_per_s = (eval_count * 1000.0 / eval_ms) if eval_ms > 0 else 0.0

    return {
        "elapsed_ms": elapsed_ms,
        "verifier_score": score,
        "preview": answer[:80].replace("\n", " "),
        "error": error,
        "eval_count": eval_count,
        "eval_ms": eval_ms,
        "prompt_tokens": prompt_tokens,
        "ollama_ms": ollama_ms_total,
        "toks_per_s": toks_per_s,
    }


async def bench_model(model: str, queries: List[tuple]) -> dict:
    os.environ["LUCIE_SPEED_MODEL"] = model
    print(f"\n=== {model} ===", flush=True)

    # Warm-up : 1 appel pour charger le modèle (évite cold start biais)
    print(f"  warm-up…", flush=True)
    await run_one("Bonjour")

    results = []
    for i, (label, q) in enumerate(queries, start=1):
        print(f"  [{i}/{len(queries)}] {label}…", flush=True, end="")
        res = await run_one(q)
        marker = "⚠" if res["error"] else "✓"
        print(
            f" {marker} {res['elapsed_ms']:.0f}ms | {res['toks_per_s']:.1f} tok/s "
            f"| score={res['verifier_score']:.2f}",
            flush=True,
        )
        results.append((label, res))

    durations = [r["elapsed_ms"] for _, r in results if r["error"] is None]
    toks = [r["toks_per_s"] for _, r in results if r["toks_per_s"] > 0]
    scores = [r["verifier_score"] for _, r in results]
    out_tokens = [r["eval_count"] for _, r in results if r["eval_count"] > 0]

    return {
        "model": model,
        "results": results,
        "summary": {
            "p50_ms": statistics.median(durations) if durations else 0.0,
            "mean_ms": statistics.mean(durations) if durations else 0.0,
            "mean_toks_per_s": statistics.mean(toks) if toks else 0.0,
            "mean_score": statistics.mean(scores) if scores else 0.0,
            "mean_out_tokens": statistics.mean(out_tokens) if out_tokens else 0.0,
            "n": len(results),
            "n_errors": sum(1 for _, r in results if r["error"]),
        },
    }


def format_report(runs: List[dict]) -> str:
    lines = ["# Bench comparatif modèles « speed » Lucie v1\n"]
    lines.append("## Comparatif global\n")
    lines.append(
        "| Modèle | p50 pipeline (ms) | moy (ms) | tok/s moy | tokens sortie moy | score moy | erreurs |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|"
    )
    for run in runs:
        s = run["summary"]
        lines.append(
            f"| `{run['model']}` | {s['p50_ms']:.0f} | {s['mean_ms']:.0f} | "
            f"{s['mean_toks_per_s']:.1f} | {s['mean_out_tokens']:.0f} | "
            f"{s['mean_score']:.2f} | {s['n_errors']}/{s['n']} |"
        )

    # Verdict : le plus rapide qui garde score moy >= 0.7
    eligible = [
        r for r in runs
        if r["summary"]["mean_score"] >= 0.7 and r["summary"]["n_errors"] == 0
    ]
    if eligible:
        best = min(eligible, key=lambda r: r["summary"]["p50_ms"])
        baseline = next((r for r in runs if r["model"] == "gemma4:e4b"), runs[0])
        base_p50 = baseline["summary"]["p50_ms"] or 1.0
        gain = (base_p50 - best["summary"]["p50_ms"]) / base_p50 * 100
        lines.append("")
        lines.append(
            f"**Décision** : `{best['model']}` (score moy {best['summary']['mean_score']:.2f} ≥ 0.7). "
            f"Gain vs `{baseline['model']}` : **{gain:.1f}%** sur p50 pipeline."
        )
    else:
        lines.append("")
        lines.append(
            "**Décision** : aucun modèle n'atteint score moy ≥ 0.7 sans erreur. "
            "Garder `gemma4:e4b` et investiguer qualité."
        )

    # Détail par modèle
    lines.append("\n## Détail par modèle\n")
    for run in runs:
        lines.append(f"### `{run['model']}`\n")
        lines.append("| Requête | ms | tok/s | out tok | prompt tok | score | aperçu |")
        lines.append("|---|---:|---:|---:|---:|---:|---|")
        for label, r in run["results"]:
            preview = r["error"] or r["preview"] or "(vide)"
            lines.append(
                f"| {label} | {r['elapsed_ms']:.0f} | {r['toks_per_s']:.1f} | "
                f"{r['eval_count']} | {r['prompt_tokens']} | "
                f"{r['verifier_score']:.2f} | {preview[:60]} |"
            )
        lines.append("")
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Bench comparatif modèles Lucie v1")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--models",
        default=",".join(DEFAULT_MODELS),
        help="Modèles séparés par virgules (défaut: gemma4:e4b,qwen2.5:3b,llama3.2:3b)",
    )
    args = parser.parse_args()

    os.environ["LUCIE_PROFILE"] = "1"
    os.environ.setdefault("LUCIE_OLLAMA_KEEP_ALIVE", "24h")
    logging.basicConfig(level=logging.WARNING)

    models = [m.strip() for m in args.models.split(",") if m.strip()]

    runs = []
    for model in models:
        try:
            runs.append(await bench_model(model, BENCH_QUERIES))
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ Échec bench {model} : {exc}", flush=True)
            runs.append({
                "model": model,
                "results": [],
                "summary": {
                    "p50_ms": 0, "mean_ms": 0, "mean_toks_per_s": 0,
                    "mean_score": 0, "mean_out_tokens": 0, "n": 0,
                    "n_errors": len(BENCH_QUERIES),
                },
            })

    report = format_report(runs)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"\nRapport écrit : {args.output}")
    else:
        print("\n" + report)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
