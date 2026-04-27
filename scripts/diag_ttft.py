"""
Diagnostic TTFT — Speed-Optimizer-Diag (S1bis).

Bench reproductible pour root-causer le gap inexpliqué de 15-20 s mesuré par
S1 entre la fin du `prompt_eval` Ollama et le premier chunk de réponse côté
pipeline Python.

Conclusions S1bis (cf. rapport `S1bis_Speed-Diag_TTFT.md`) :
  - `gemma4:e4b` est un modèle de raisonnement (chain-of-thought) ; le
    `RENDERER gemma4` absorbe le thinking côté serveur Ollama et ne renvoie
    le `content` qu'après la phase de raisonnement (~12-17 s).
  - Le pipeline actuel utilise `/api/generate` et reçoit donc le 1er chunk
    de content seulement APRÈS le thinking → TTFT mesuré = durée du thinking.
  - Sur `/api/chat`, le `thinking` est exposé en chunks séparés du `content`
    et arrive en ~1.25 s — TTFT effectif compatible avec la cible YC <1 s.

Modes :
  --mode shell     : curl brut sur /api/generate stream=true (isole client/serveur)
  --mode generate  : httpx async sur /api/generate (réplique pipeline actuel)
  --mode chat      : httpx async sur /api/chat (mesure thinking vs content)
  --mode all       : enchaîne les trois modes et imprime un récap

Sortie : Markdown sur stdout, redirige vers `reports/s1bis_diag_<ts>.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx


OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("LUCIE_DIAG_MODEL", "gemma4:e4b")
DEFAULT_RUNS = 5
SHORT_PROMPT = "Bonjour, donne-moi une réponse simple."
# ~800 tokens, similaire en volume à un prompt RAG complet du pipeline
LONG_PROMPT = (
    "Vous êtes Lucie, un assistant juridique français spécialisé en droit du "
    "travail. Vous répondez aux questions sur le code du travail, en citant "
    "les articles pertinents avec précision. " * 22
) + "Question : Quelle est la durée légale du travail hebdomadaire en France ?"


@dataclass
class RunResult:
    label: str
    ttft_first_chunk_s: float
    ttft_first_content_s: float | None
    total_s: float
    chunks: int
    eval_count: int
    eval_duration_s: float
    prompt_eval_count: int
    prompt_eval_duration_s: float
    thinking_chars: int = 0
    content_chars: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def eval_tps(self) -> float:
        return self.eval_count / self.eval_duration_s if self.eval_duration_s else 0.0


def _hostname() -> str:
    return socket.gethostname()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _system_snapshot() -> dict[str, str]:
    """Capture rapide RAM/load — utile pour interpréter les mesures."""
    out = {"hostname": _hostname(), "timestamp": _now_iso()}
    try:
        uptime = subprocess.check_output(["uptime"], text=True, timeout=2).strip()
        out["uptime"] = uptime
    except Exception:
        pass
    try:
        ps = subprocess.check_output(
            ["ollama", "ps"], text=True, timeout=3, stderr=subprocess.STDOUT
        ).strip()
        out["ollama_ps"] = ps
    except Exception:
        out["ollama_ps"] = "(ollama ps failed)"
    return out


# ---------- Mode shell (curl) ----------------------------------------------

def run_shell_mode(model: str, prompt: str, num_predict: int, runs: int) -> list[RunResult]:
    """Mesure TTFT via `curl -N` sur /api/generate stream=true.

    `time_starttransfer` = temps avant le 1er byte HTTP. Comme Ollama n'envoie
    rien avant le 1er token utile, ce TTFT correspond au 1er chunk reçu côté
    réseau. Permet d'éliminer toute hypothèse "buffering Python".
    """
    if shutil.which("curl") is None:
        print("# (mode shell skipped: curl not found)")
        return []

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {"num_predict": num_predict},
    }

    results: list[RunResult] = []
    for i in range(1, runs + 1):
        body = json.dumps(payload)
        cmd = [
            "curl", "-sN", "-X", "POST", f"{OLLAMA_URL}/api/generate",
            "-H", "Content-Type: application/json",
            "-d", body,
            "-w", "%{time_starttransfer} %{time_total} %{size_download}\n",
            "-o", "/tmp/diag_ttft_shell.txt",
        ]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        try:
            ttft, total, size = line.split()
            ttft_s, total_s = float(ttft), float(total)
        except ValueError:
            ttft_s, total_s = 0.0, 0.0
        # Parse stats from last JSON object in the response
        try:
            with open("/tmp/diag_ttft_shell.txt", "rb") as f:
                data = f.read()
            chunks = [c for c in data.split(b"\n") if c.strip()]
            n_chunks = len(chunks)
            last = json.loads(chunks[-1]) if chunks else {}
        except Exception:
            n_chunks, last = 0, {}

        results.append(RunResult(
            label=f"shell run {i}",
            ttft_first_chunk_s=ttft_s,
            ttft_first_content_s=None,
            total_s=total_s,
            chunks=n_chunks,
            eval_count=last.get("eval_count", 0),
            eval_duration_s=(last.get("eval_duration", 0) or 0) / 1e9,
            prompt_eval_count=last.get("prompt_eval_count", 0),
            prompt_eval_duration_s=(last.get("prompt_eval_duration", 0) or 0) / 1e9,
        ))
    return results


# ---------- Mode generate (httpx /api/generate, réplique pipeline) ---------

async def _httpx_run_generate(model: str, prompt: str, num_predict: int) -> RunResult:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {"num_predict": num_predict},
    }
    start = time.perf_counter()
    ttft_first_chunk: float | None = None
    ttft_first_content: float | None = None
    chunks = 0
    content_chars = 0
    last: dict[str, Any] = {}
    timeout = httpx.Timeout(connect=10, read=300, write=10, pool=10)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", f"{OLLAMA_URL}/api/generate", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                elapsed = time.perf_counter() - start
                if ttft_first_chunk is None:
                    ttft_first_chunk = elapsed
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chunks += 1
                resp_text = obj.get("response", "") or ""
                if resp_text:
                    if ttft_first_content is None:
                        ttft_first_content = elapsed
                    content_chars += len(resp_text)
                if obj.get("done"):
                    last = obj
                    break
    total = time.perf_counter() - start
    return RunResult(
        label="httpx /api/generate",
        ttft_first_chunk_s=ttft_first_chunk or 0.0,
        ttft_first_content_s=ttft_first_content,
        total_s=total,
        chunks=chunks,
        eval_count=last.get("eval_count", 0),
        eval_duration_s=(last.get("eval_duration", 0) or 0) / 1e9,
        prompt_eval_count=last.get("prompt_eval_count", 0),
        prompt_eval_duration_s=(last.get("prompt_eval_duration", 0) or 0) / 1e9,
        content_chars=content_chars,
    )


def run_generate_mode(model: str, prompt: str, num_predict: int, runs: int) -> list[RunResult]:
    return [asyncio.run(_httpx_run_generate(model, prompt, num_predict)) for _ in range(runs)]


# ---------- Mode chat (httpx /api/chat avec thinking séparé) ----------------

async def _httpx_run_chat(model: str, prompt: str, num_predict: int) -> RunResult:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "options": {"num_predict": num_predict},
    }
    start = time.perf_counter()
    ttft_first_chunk: float | None = None
    ttft_first_content: float | None = None
    chunks = 0
    thinking_chars = 0
    content_chars = 0
    last: dict[str, Any] = {}
    timeout = httpx.Timeout(connect=10, read=300, write=10, pool=10)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                elapsed = time.perf_counter() - start
                if ttft_first_chunk is None:
                    ttft_first_chunk = elapsed
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chunks += 1
                msg = obj.get("message") or {}
                thinking = msg.get("thinking", "") or ""
                content = msg.get("content", "") or ""
                if thinking:
                    thinking_chars += len(thinking)
                if content:
                    if ttft_first_content is None:
                        ttft_first_content = elapsed
                    content_chars += len(content)
                if obj.get("done"):
                    last = obj
                    break
    total = time.perf_counter() - start
    return RunResult(
        label="httpx /api/chat",
        ttft_first_chunk_s=ttft_first_chunk or 0.0,
        ttft_first_content_s=ttft_first_content,
        total_s=total,
        chunks=chunks,
        eval_count=last.get("eval_count", 0),
        eval_duration_s=(last.get("eval_duration", 0) or 0) / 1e9,
        prompt_eval_count=last.get("prompt_eval_count", 0),
        prompt_eval_duration_s=(last.get("prompt_eval_duration", 0) or 0) / 1e9,
        thinking_chars=thinking_chars,
        content_chars=content_chars,
    )


def run_chat_mode(model: str, prompt: str, num_predict: int, runs: int) -> list[RunResult]:
    return [asyncio.run(_httpx_run_chat(model, prompt, num_predict)) for _ in range(runs)]


# ---------- Reporting -------------------------------------------------------

def _fmt_ms(s: float | None) -> str:
    if s is None:
        return "—"
    return f"{s * 1000:.0f} ms"


def _summary(label: str, results: list[RunResult]) -> None:
    if not results:
        print(f"### {label}\n(no runs)\n")
        return
    print(f"### {label}\n")
    print("| Run | TTFT 1er chunk | TTFT 1er content | Total | Chunks | Eval (t/s) | prompt_eval |")
    print("|-----|---------------:|-----------------:|------:|-------:|-----------:|------------:|")
    for r in results:
        print(
            f"| {r.label} | {_fmt_ms(r.ttft_first_chunk_s)} | "
            f"{_fmt_ms(r.ttft_first_content_s)} | {_fmt_ms(r.total_s)} | "
            f"{r.chunks} | {r.eval_count}t/{r.eval_duration_s:.2f}s ({r.eval_tps:.1f} t/s) | "
            f"{r.prompt_eval_count}t/{r.prompt_eval_duration_s:.2f}s |"
        )
    ttft_chunks = [r.ttft_first_chunk_s for r in results if r.ttft_first_chunk_s]
    ttft_contents = [r.ttft_first_content_s for r in results if r.ttft_first_content_s]
    if ttft_chunks:
        print(f"\n  - TTFT 1er chunk      : median={statistics.median(ttft_chunks)*1000:.0f}ms"
              f"  min={min(ttft_chunks)*1000:.0f}ms  max={max(ttft_chunks)*1000:.0f}ms")
    if ttft_contents:
        print(f"  - TTFT 1er content    : median={statistics.median(ttft_contents)*1000:.0f}ms"
              f"  min={min(ttft_contents)*1000:.0f}ms  max={max(ttft_contents)*1000:.0f}ms")
    print()


def main() -> int:
    p = argparse.ArgumentParser(description="Diagnostic TTFT Lucie (S1bis)")
    p.add_argument("--mode", choices=["shell", "generate", "chat", "all"], default="all")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--prompt", choices=["short", "long"], default="long")
    p.add_argument("--num-predict", type=int, default=200)
    p.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    args = p.parse_args()

    prompt = SHORT_PROMPT if args.prompt == "short" else LONG_PROMPT

    print(f"# Diagnostic TTFT — {args.mode} sur `{args.model}`")
    print()
    snap = _system_snapshot()
    print(f"- timestamp : {snap.get('timestamp')}")
    print(f"- hostname  : {snap.get('hostname')}")
    print(f"- prompt    : {args.prompt} ({len(prompt)} chars)")
    print(f"- num_predict : {args.num_predict}")
    print(f"- runs        : {args.runs}")
    if "uptime" in snap:
        print(f"- uptime    : `{snap['uptime']}`")
    if "ollama_ps" in snap:
        print(f"- ollama ps :\n```\n{snap['ollama_ps']}\n```")
    print()

    if args.mode in ("shell", "all"):
        _summary("Shell (curl /api/generate stream=true)",
                 run_shell_mode(args.model, prompt, args.num_predict, args.runs))
    if args.mode in ("generate", "all"):
        _summary("Python httpx /api/generate (réplique pipeline actuel)",
                 run_generate_mode(args.model, prompt, args.num_predict, args.runs))
    if args.mode in ("chat", "all"):
        _summary("Python httpx /api/chat (mesure thinking vs content)",
                 run_chat_mode(args.model, prompt, args.num_predict, args.runs))

    print("---")
    print("Lecture rapide :")
    print("- Si **TTFT 1er chunk** est rapide (<2 s) mais **TTFT 1er content** est lent (>10 s)")
    print("  côté `/api/chat`, alors le modèle est en mode raisonnement et le pipeline doit")
    print("  passer à `/api/chat` pour streamer le `thinking` au HUD (cible YC atteignable).")
    print("- Si tous les TTFT sont lents même en shell, le coupable est Ollama (charge/mode).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
