# Reproducing the README numbers

*[Lire en français](REPRODUCE.fr.md)*

This recipe explains how to run Beaume locally and reproduce the
reliability metrics shown in the README (in particular the 16-
question multi-angle battery at 62.5%, measured 2026-05-12).

---

## Hardware & software prerequisites

| Component | Version / spec |
|-----------|----------------|
| Apple Silicon Mac | M2 with 16 GB or more, all M3, all M4, all M5 |
| RAM | 16 GB minimum, 24 GB recommended for `gemma4:e4b` |
| Free disk | ~10 GB (Ollama model + compacted Légifrance KB) |
| macOS | 13 Ventura or higher |
| Python | 3.11 or higher |
| Ollama | latest stable release (`brew install ollama`) |

---

## Installation

```bash
# 1. Get the code
git clone https://github.com/mathieuballotma-sketch/lucie.git beaume
cd beaume

# 2. Start Ollama and pull the model used by Beaume
ollama serve &
ollama pull gemma4:e4b

# 3. Python environment — use Python 3.11 explicitly
#    (system python3 on macOS is 3.9 by default and will fail)
python3.11 -m venv venv
source venv/bin/activate

# 4. Install dependencies with --no-deps
#    Reason: requirements.txt pins are over-constrained
#    (transformers==5.2.0 conflicts with sentence-transformers 3.3.1
#    which requires transformers<5.0.0). Using --no-deps installs
#    each pinned version verbatim, bypassing pip's resolver. This is
#    a known temporary workaround; a clean repin is on the backlog.
pip install -r requirements.txt --no-deps

# 5. (Optional) install the local Légifrance KB
# The 4.6 GB SQLite file is NOT in the repo (ignored by .gitignore).
# See lucie_v1_standalone/knowledge_legifrance/README for the
# generation procedure from public DILA archives.
# Beaume runs without it: it falls back to the curated 80 KB local KB
# (lucie_v1_standalone/knowledge/droit_social/), and the corpus mode
# (`--corpus fr_pharma_ansm --no-llm`) is fully offline-deterministic.
```

---

## Launch the HUD

```bash
PYTHONPATH=. python3 main_hud.py
```

A native macOS window opens. Type a French employment-law question
— for example: *"What is the deadline to send the dismissal letter
after the preliminary interview in an economic dismissal?"*.

---

## Reproduce the 16q battery (62.5%)

```bash
# Sprint 6 P2a flags enabled
export BEAUME_RETRIEVER_DEBRIDE=1
export BEAUME_VERIFICATEUR_NORMALISE=1

# Targeted battery (10 lic_eco-category questions)
python3 bench/run_legal_traps.py \
  --prompts bench/swiss_watch_50.json \
  --filter SW-LECO \
  --json bench/results/_repro_16q.json
```

The script prints a PASS/FAIL summary and writes a detailed JSON
(`verifier_score`, validated citations, invalidated citations,
deterministic refusals).

Compare with [`bench/results/2026-05-12_battery_16q_post_p2a.md`](../bench/results/2026-05-12_battery_16q_post_p2a.md).
A few-percent gap per run is normal — the Gemma 4 e4b LLM is not
deterministic (temperature > 0). Across 5 successive runs,
reliability typically stays within ±5%.

---

## Reproduce the 50q battery

```bash
export BEAUME_RETRIEVER_DEBRIDE=1
export BEAUME_VERIFICATEUR_NORMALISE=1

python3 bench/run_legal_traps.py \
  --prompts bench/swiss_watch_50.json \
  --json bench/results/_repro_50q.json
```

Note: the clean 50q measurement is being stabilized at the time
this file is written. See
[`bench/results/2026-05-12_battery_50q_post_p2a.md`](../bench/results/2026-05-12_battery_50q_post_p2a.md)
for the current status.

---

## Run the unit tests

```bash
pytest tests/ -v --ignore=tests/integration --ignore=tests/llm
```

See [`tests/README.md`](../tests/README.md) for coverage by folder
and filtering options.

---

## If something does not reproduce

1. Verify that `ollama serve` is running (`curl http://127.0.0.1:11434/api/tags`).
2. Verify the model version (`ollama list`) — an older Gemma or a
   different quant gives different numbers.
3. Verify the environment flags (`env | grep BEAUME_`).
4. Open a GitHub issue with the contents of
   `bench/results/_repro_*.json`.

Radical transparency requires that an unexplained gap be
documented rather than ignored.
