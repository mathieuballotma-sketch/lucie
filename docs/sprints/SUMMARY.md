# Sprint history — public view

*[Lire en français](SUMMARY.fr.md)*

Condensed summary of shipped sprints. **Detailed reports** (root
causes, design choices, detailed before/after metrics, modified
prompts) stay in internal reserve and are not published.

What is published here: sprint name, date, measurable metrics,
files touched at folder level.

---

## Sprint 6 P2c — LLM context fidelity (PARTIAL)

- **Delivery date**: 2026-05-12
- **Commits**: `6be38b1`, `2f1166d`
- **Scope**: redacteur (conditional load of an override system prompt from a gitignored private folder) + Ollama transport (transport-level pinning of `temperature=0` + `seed` for all agents)
- **50q battery measurement**: **33/50** PASS (vs 34/50 post-P2b baseline, i.e. −1)
- **Core lic_eco sub-score**:
  - Official PASS: **1/10** (vs 2/10 baseline) — target ≥ 6/10 **not met**
  - Refusal hallucination: **0/10** (vs 8/10 baseline) — root cause resolved
  - 9/10 core questions only exceed the `wall_clock_ms_max=60 000 ms` threshold; on content, `verifier_score ≥ 0.7`, length ≥ 200 chars, `[L1233-x]` articles cited. Median 70 s.
- **Causal A/B seed on vs off** (lic_eco): without seed, median 58 s but 2/10 hallucinations reappear; with seed, median 70 s and 0/10 hallucination. Determinism improves fidelity, degrades performance by about 10 s on the median.
- **Feature flags**: `BEAUME_REDACTEUR_STRICT_CONTEXT`, `BEAUME_LLM_DETERMINISTIC` (default "1" for both)
- **Verdict**: PARTIAL. Context fidelity is technically restored. The `wall_clock_ms_max=60 000 ms` criterion is too strict for `gemma4:e4b` chain-of-thought in deterministic mode. Sprint 6 P2d follow-up: calibrate the measurement threshold to 90 000 ms (lawyer target) or benchmark a faster model.

## Sprint 6 P2a — Unbounded retriever + normalized verifier

- **Delivery date**: 2026-05-12
- **Commits**: `8dbfd95`, `a1c36c4`, `428eb94`, merge `315719b`
- **Scope**: retriever (relaxed stop-list) + verifier (deduplicated citation normalization)
- **Measurement**: 16q multi-angle battery reliability = **62.5%** ([bench/results/2026-05-12_battery_16q_post_p2a.md](../../bench/results/2026-05-12_battery_16q_post_p2a.md))
- **Feature flags**: `BEAUME_RETRIEVER_DEBRIDE`, `BEAUME_VERIFICATEUR_NORMALISE`
- **Threshold calibration**: `verifier_score_min` 0.85 → 0.70 — justification in [bench/CHANGELOG.md](../../bench/CHANGELOG.md)

## Sprint 6 P1b — Contextual `lic_perso` refusal

- **Delivery date**: 2026-05-08
- **Scope**: ambiguous-router extension for leaves/RTT/resignation/RC
- **Effect**: fewer wrong routings to the `lic_eco` branch when the question is about personal dismissal

## Sprint 6 P1 — Smart Brain + reasons + contextual refusal

- **Delivery date**: 2026-05-08
- **Scope**: relaxed intent classifier, `lic_perso` sub-category, pipeline branch with structured verdict

## Sprint 3 — Swiss-Watch fusion

- **Delivery date**: 2026-05-08
- **Scope**: `beaume/` module (public entry), user memory page, 50q battery, `verifier_score` badge in the HUD
- **Volume**: +3,793 net lines

## Sprint 1 / 1bis / 1ter — Rebrand & cleanup

- **Dates**: 2026-05-08
- **Scope**: rebrand Lucie → Beaume (env vars `LUCIE_*` → `BEAUME_*` with deprecation fallback, launchd, filesystem paths, README, CHANGELOG), DB cleanup −6.7 GB

---

## Why no more detail here

Beaume's radical transparency covers **what is shipped and what is
measured**, not **how the bugs were found and how I solved them
internally**. Deep diagnostic reports would reveal:

- The Gemma LLM's error patterns on specific questions.
- Empirically tuned thresholds after N runs.
- Rejected implementation choices and why.
- Prompts modified line by line.

All of this represents 5 months of solo R&D work and stays in
competitive reserve. The public repo gives the **effect**
(reproducible metrics), not the **recipe**.

If you are an investor, mentor, or partner lawyer and want to see
the details under NDA: mathieu.ballotma@gmail.com.
