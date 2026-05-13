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
| RAM | 16 GB minimum, 24 GB recommended for `gemma2:9b` |
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

# 2. Start Ollama and pull the model
ollama serve &
ollama pull gemma2:9b

# 3. Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. (Optional) install the local Légifrance KB
# The 4.6 GB SQLite file is NOT in the repo (ignored by .gitignore).
# See lucie_v1_standalone/knowledge_legifrance/README for the
# generation procedure from public DILA archives.
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
