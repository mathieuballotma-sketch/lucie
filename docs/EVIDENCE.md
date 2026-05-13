# Evidence — claim → proof → verification mapping

*[Lire en français](EVIDENCE.fr.md)*

Every claim the README makes about Beaume must point here to
clickable evidence in the code, and to a reproducible verification
method.

If a README claim has no line in this file, it must be removed from
the README. **Truth rule.**

---

## Architecture

| README claim | Proof in code | Verification |
|---|---|---|
| 100% on-device pipeline (Ollama localhost) | [`lucie_v1_standalone/ollama_client.py`](../lucie_v1_standalone/ollama_client.py) | `grep -r "localhost\|127.0.0.1" lucie_v1_standalone/` |
| Cerveau Oiseaux — deterministic router (intent classifier + bounds) | [`lucie_v1_standalone/dialogue/intent_classifier.py`](../lucie_v1_standalone/dialogue/intent_classifier.py), [`lucie_v1_standalone/dialogue/`](../lucie_v1_standalone/dialogue/) | `pytest lucie_v1_standalone/tests/test_dialogue/test_intent_classifier.py -v` |
| Cerveau Humain — LLM phrasing | [`lucie_v1_standalone/ollama_client.py`](../lucie_v1_standalone/ollama_client.py) | `grep -i "model\|prompt" lucie_v1_standalone/ollama_client.py \| head -10` |
| Deterministic verifier (truth rule) — refuses citations outside the KB | [`lucie_v1_standalone/verificateur.py`](../lucie_v1_standalone/verificateur.py) | `pytest tests/test_truth_rule_pattern.py -v` |
| Légifrance KB retriever | [`lucie_v1_standalone/retriever.py`](../lucie_v1_standalone/retriever.py), [`lucie_v1_standalone/knowledge_legifrance/retriever.py`](../lucie_v1_standalone/knowledge_legifrance/retriever.py) | `pytest tests/test_legifrance/ -v` (requires the local index) |
| Per-user adaptive memory | [`lucie_v1_standalone/memory/`](../lucie_v1_standalone/memory/) (`personal.py`, `abstract.py`, `store.py`, `sanitizer.py`) | `pytest tests/memory/test_memory_store.py -v` |

## Reliability measurements

| README claim | Proof | Verification |
|---|---|---|
| **62.5%** on the 16q multi-angle battery (2026-05-12) | [`bench/results/2026-05-12_battery_16q_post_p2a.md`](../bench/results/2026-05-12_battery_16q_post_p2a.md) | `BEAUME_RETRIEVER_DEBRIDE=1 BEAUME_VERIFICATEUR_NORMALISE=1 python3 bench/run_legal_traps.py --prompts bench/swiss_watch_50.json --filter SW-LECO --json /tmp/run.json` |
| 50q battery — **clean measurement in progress** | [`bench/results/2026-05-12_battery_50q_post_p2a.md`](../bench/results/2026-05-12_battery_50q_post_p2a.md) | To publish once stabilized. No number cited until the clean run is delivered. |
| `verifier_score ≥ 0.70` threshold calibrated on deduplicated citations | [`bench/CHANGELOG.md`](../bench/CHANGELOG.md), [`bench/swiss_watch_50.json`](../bench/swiss_watch_50.json) (`pass_criteria.verifier_score_min`) | `grep -A2 verifier_score_min bench/swiss_watch_50.json \| head -30` |
| Tests: 23 `test_*.py` files, ~132 unit tests | [`tests/`](../tests/) | `pytest tests/ --collect-only -q \| tail -5` |
| Truth rule applied architecturally (refusal before LLM) | [`lucie_v1_standalone/verificateur.py`](../lucie_v1_standalone/verificateur.py) + [`docs/architecture.md`](architecture.md) section "Truth enforcement" | Direct read + `tests/test_truth_rule_pattern.py` |

## Runtime stack

| README claim | Proof | Verification |
|---|---|---|
| Gemma 4 e4b via Ollama | [`lucie_v1_standalone/config.py`](../lucie_v1_standalone/config.py) (`SPEED_MODEL`) | `grep -i "gemma\|model" lucie_v1_standalone/config.py` |
| Native macOS HUD via PyObjC | [`app/ui/hud_native.py`](../app/ui/hud_native.py) | `head -50 app/ui/hud_native.py` (PyObjC imports) |
| Légifrance KB indexed in SQLite (FTS5) | [`lucie_v1_standalone/knowledge_legifrance/`](../lucie_v1_standalone/knowledge_legifrance/) | `cat lucie_v1_standalone/knowledge_legifrance/schema.sql` |
| No outbound cloud calls at runtime | [`lucie_v1_standalone/ollama_client.py`](../lucie_v1_standalone/ollama_client.py) (base URL `http://127.0.0.1:11434`) | `grep -rE "https?://" lucie_v1_standalone/ --include='*.py' \| grep -v localhost \| grep -v 127.0.0.1` (expected result: empty or only docstrings) |

## Sprint history (audit trail)

| README claim | Proof | Verification |
|---|---|---|
| Sprint history (public summary) | [`docs/sprints/SUMMARY.md`](sprints/SUMMARY.md) | Read + `git log --oneline --grep="Sprint"` |
| Diagnostic detail & root causes | **Not published** (internal reserve, see [`docs/sprints/SUMMARY.md`](sprints/SUMMARY.md) for the doctrine) | NDA on request |

## How to add a claim to the README

1. Identify the claim to add to the README.
2. Identify the file / command that proves it.
3. **Add a line in this file first.**
4. Cite the claim in the README pointing to `docs/EVIDENCE.md#...` or directly to the proof.

If step 2 fails (no proof), do not write the claim. That's the
rule.
