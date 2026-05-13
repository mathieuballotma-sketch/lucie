# bench/results — historical Beaume battery results

*[Lire en français](README.fr.md)*

Archive of Beaume battery results in human-readable Markdown. The detailed
raw JSON (with stack traces, full prompts, LLM payloads) stays in
internal reserve ([`docs/sprints/SUMMARY.md`](../../docs/sprints/SUMMARY.md)
explains the doctrine).

## Published files

- [2026-05-12_battery_16q_post_p2a.md](2026-05-12_battery_16q_post_p2a.md) — 16q multi-angle battery, reliability **62.5%**
- [2026-05-12_battery_50q_post_p2a.md](2026-05-12_battery_50q_post_p2a.md) — 50q lic_eco core battery, **clean measurement in progress**

## Format

Each result is named `YYYY-MM-DD_battery_NNq_<context>.md` and
contains at minimum:

1. Date and context (commit, active feature flags, model used)
2. Global PASS/FAIL score and reliability in %
3. Decomposition by category or by angle
4. Exact reproduction command (cf. [`docs/REPRODUCE.md`](../../docs/REPRODUCE.md))
5. Explicit limits of the measurement (truth rule)

## What is not published

- Raw JSON (`*.json` detailed with LLM payloads)
- Private questions beyond `bench/swiss_watch_50.json`
- Internal diagnostic JSON (`bench/results/diagnostic_*`, ignored by
  `.gitignore`)
