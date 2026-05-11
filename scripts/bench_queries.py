"""Harness de benchmark perf pour Lucie v1.

Joue 10 requêtes types contre le pipeline en mesurant :
  - durée end-to-end par requête
  - **TTFT** wall-clock (1er chunk reçu) — R3 sprint S1
  - **TTFT** pipeline (mesure interne `pipeline.ttft`) — R3 sprint S1
  - **TTFT** ollama (mesure interne `ollama.<model>.ttft`) — R3 sprint S1
  - durée par étape (profilage)
  - durée totale et médiane

Activation profilage via `BEAUME_PROFILE=1` (auto-activé par le script).

Usage :
    python3 scripts/bench_queries.py
    python3 scripts/bench_queries.py --output reports/baseline.md
    python3 scripts/bench_queries.py --queries reduced
    python3 scripts/bench_queries.py --model qwen2.5:3b
    python3 scripts/bench_queries.py --wait-warmup   # NEW R3 — bench post-warmup

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
    """Exécute 1 requête en streaming, retourne TTFT + métriques agrégées.

    R3 sprint S1 : on bascule sur `pipeline.run_stream` pour mesurer le
    TTFT *réel* perçu par le HUD, plus le TTFT interne (pipeline.ttft) et
    le TTFT Ollama brut (ollama.<model>.ttft) si présents dans le bucket.
    """
    from lucie_v1_standalone.pipeline import PipelineResponse, run_stream

    t0 = time.perf_counter()
    ttft_wall_ms: Optional[float] = None
    answer_chunks: list = []
    final_response = None
    error = None

    async with profile_bucket() as bucket:
        try:
            async for event in run_stream(query):
                if isinstance(event, str):
                    if ttft_wall_ms is None:
                        ttft_wall_ms = (time.perf_counter() - t0) * 1000
                    answer_chunks.append(event)
                else:
                    # PipelineResponse — réponse finale (ou seule, pour SMALL_TALK)
                    final_response = event
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

    elapsed_ms = (time.perf_counter() - t0) * 1000

    if answer_chunks:
        answer = "".join(answer_chunks)
    elif final_response is not None:
        answer = getattr(final_response, "answer", "") or ""
    else:
        answer = ""

    steps = []
    pipeline_ttft_ms: Optional[float] = None
    ollama_ttft_ms: Optional[float] = None
    if bucket is not None:
        for s in bucket.steps:
            steps.append({"name": s.name, "ms": s.duration_ms, "meta": s.meta})
            if s.name == "pipeline.ttft":
                pipeline_ttft_ms = s.duration_ms
            elif s.name.endswith(".ttft") and s.name.startswith("ollama."):
                ollama_ttft_ms = s.duration_ms

    return {
        "elapsed_ms": elapsed_ms,
        "ttft_wall_ms": ttft_wall_ms,
        "pipeline_ttft_ms": pipeline_ttft_ms,
        "ollama_ttft_ms": ollama_ttft_ms,
        "answer_preview": (answer or "")[:120].replace("\n", " "),
        "error": error,
        "steps": steps,
    }


def format_report(results: List[dict], labels: List[str]) -> str:
    """Produit le tableau Markdown du bench."""
    lines = ["# Bench Lucie v1 — profilage pipeline\n"]

    # Tableau résumé par requête (R3 sprint S1 : colonnes TTFT)
    lines.append("## Résumé par requête\n")
    lines.append(
        "| # | Label | Durée (ms) | TTFT wall (ms) | TTFT pipeline (ms) | "
        "TTFT ollama (ms) | Aperçu |"
    )
    lines.append("|---:|---|---:|---:|---:|---:|---|")
    for i, (res, label) in enumerate(zip(results, labels), start=1):
        preview = res["error"] or res["answer_preview"] or "(vide)"
        ttft_wall = res.get("ttft_wall_ms")
        ttft_pipe = res.get("pipeline_ttft_ms")
        ttft_oll = res.get("ollama_ttft_ms")
        ttft_wall_s = f"{ttft_wall:.0f}" if ttft_wall is not None else "—"
        ttft_pipe_s = f"{ttft_pipe:.0f}" if ttft_pipe is not None else "—"
        ttft_oll_s = f"{ttft_oll:.0f}" if ttft_oll is not None else "—"
        lines.append(
            f"| {i} | {label} | {res['elapsed_ms']:.0f} | {ttft_wall_s} | "
            f"{ttft_pipe_s} | {ttft_oll_s} | {preview[:80]} |"
        )

    durations = [r["elapsed_ms"] for r in results]
    if durations:
        lines.append("")
        lines.append(
            f"**p50** : {statistics.median(durations):.0f} ms · "
            f"**moy** : {statistics.mean(durations):.0f} ms · "
            f"**max** : {max(durations):.0f} ms · "
            f"**n** : {len(durations)}"
        )

    # R3 sprint S1 : ligne TTFT (médiane / min / max sur les requêtes
    # qui ont effectivement streamé — exclut SMALL_TALK).
    ttft_walls = [r["ttft_wall_ms"] for r in results if r.get("ttft_wall_ms") is not None]
    ttft_pipes = [r["pipeline_ttft_ms"] for r in results if r.get("pipeline_ttft_ms") is not None]
    ttft_olls = [r["ollama_ttft_ms"] for r in results if r.get("ollama_ttft_ms") is not None]
    if ttft_walls:
        lines.append(
            f"**TTFT wall** (n={len(ttft_walls)}) — "
            f"médiane {statistics.median(ttft_walls):.0f} ms · "
            f"min {min(ttft_walls):.0f} ms · max {max(ttft_walls):.0f} ms"
        )
    if ttft_pipes:
        lines.append(
            f"**TTFT pipeline** (n={len(ttft_pipes)}) — "
            f"médiane {statistics.median(ttft_pipes):.0f} ms · "
            f"min {min(ttft_pipes):.0f} ms · max {max(ttft_pipes):.0f} ms"
        )
    if ttft_olls:
        lines.append(
            f"**TTFT ollama** (n={len(ttft_olls)}) — "
            f"médiane {statistics.median(ttft_olls):.0f} ms · "
            f"min {min(ttft_olls):.0f} ms · max {max(ttft_olls):.0f} ms"
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
                        help="Override BEAUME_SPEED_MODEL pour cette run")
    parser.add_argument("--passes", type=int, default=1,
                        help="Rejoue le set N fois dans le même process (mesure cache hits)")
    parser.add_argument("--wait-warmup", action="store_true",
                        help="R3 sprint S1 : warm-up Ollama avant le bench "
                             "(élimine le cold-start des mesures TTFT)")
    args = parser.parse_args()

    # Profilage actif par défaut dans ce harness
    os.environ.setdefault("BEAUME_PROFILE", "1")
    if args.model:
        os.environ["BEAUME_SPEED_MODEL"] = args.model

    logging.basicConfig(level=logging.WARNING)

    if args.wait_warmup:
        from lucie_v1_standalone import ollama_client
        from lucie_v1_standalone.config import SPEED_MODEL
        print("warm-up Ollama (1 token)...", flush=True)
        t_w = time.perf_counter()
        try:
            await ollama_client.generate(
                model=SPEED_MODEL,
                prompt=" ",
                options={"num_predict": 1, "temperature": 0},
            )
            print(f"warm-up done in {(time.perf_counter() - t_w):.1f}s", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"warm-up failed (continuing): {exc}", flush=True)

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
