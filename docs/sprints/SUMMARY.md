# Sprint history — public view

*[Lire en français](SUMMARY.fr.md)*

Condensed summary of shipped sprints. **Detailed reports** (root
causes, design choices, detailed before/after metrics, modified
prompts) stay in internal reserve and are not published.

What is published here: sprint name, date, measurable metrics,
files touched at folder level.

---

## Sprint K-1 — KB binary signatures + reference graph + PageRank

- **Delivery date**: 2026-05-15
- **Commits**: `946daeb` (feat), merge `64cc5e9`
- **Scope**: `lucie_v1_standalone/knowledge_legifrance/kb_compact/` (7 files: constants, embedder, graph_writer, pagerank, sig_reader, sig_writer, `__init__`), plus `refs_extractor.py` (DAG cross-reference extractor)
- **Format**: versioned binary `MAGIC_SIGS = b"BEAUMEK1"`, `MAGIC_GRAPH = b"BEAUMEK1G"` (Matryoshka signatures + zstandard compression)
- **New deps**: `cbor2==5.6.5`, `hnswlib==0.8.0`, `zstandard==0.23.0`
- **Tests**: 49 tests across 6 files in `tests/test_kb_compact/`
- **Smoke 5k articles**: ratio ~10 000× per commit message. **Full-corpus BGE-M3 recall@10 benchmark pending.**
- **Public doc**: `docs/kb_compact_pipeline.md` (+ `.fr.md`)

## Sprint 7 — Client-file ingestion (PDF/docx)

- **Delivery date**: 2026-05-15
- **Commits**: `624d997` (feat), merge `f3b395b`
- **Scope**: new module `lucie_v1_standalone/document_analyzer/` (7 files, 622 lines, additive pure — zero LLM in-module)
- **Pipeline**: `parse → oos gate → theme detect → retriever → result` (fully deterministic)
- **Tests**: 28 tests across 5 files in `lucie_v1_standalone/tests/test_document_analyzer/`. Per commit message: 28/28 + 370/370 non-LLM green.
- **Note**: requires `pypdf` and `python-docx` (already in `requirements.txt`).

## Sprint G-1 — Beaume Engine + corpus pack (étape 1)

- **Delivery date**: 2026-05-15
- **Commits**: `bd5a2d2`, `7402f0e`
- **Scope**: corpus pack manifest schema (Pydantic v2 strict, `extra="forbid"`, `frozen=True`) + pharma ANSM demo corpus (5 markdown articles, themes, refusals) + CLI `--corpus CODE` / `--no-llm` flags (additive — default `droit_social` path untouched)
- **Tests**: `tests/test_corpus/test_manifest_schema.py`, `test_corpus_loader.py`, `test_corpus_runner.py`, `test_corpus_cli.py`
- **Demo**: `scripts/demo_pharma_ansm.sh` (in-scope, fiscal out-of-scope, hardcoding probe)

## Sprint 6 P3 — KB `lic_eco` gaps filled

- **Delivery date**: 2026-05-15
- **Commits**: `317c0c5` (feat), merge `1e2c6d4`
- **Scope**: added `knowledge/droit_social/licenciement_economique/L1233-65.md`, `L1233-66.md`, `L1233-67.md`, plus bonus `L1233-68.md` (CSP follow-up). `index.json` bumped 1.0.0 → 1.1.0, total 20 articles.
- **Refactor**: `lucie_v1_standalone/retriever.py` (+280/−67 lines) — replaces early-return by curated-then-Légifrance merge, fixing the substring-match bug where `L.1233-3` matched `L.1233-30` text.
- **Tests**: `lucie_v1_standalone/tests/test_kb_curatee_csp.py`, `tests/test_retriever_merge_p3.py`
- **Internal verdict per commit message**: core 7→10/10, global 45→48/50 (not re-measured in the horloger audit — no battery run authorized)

## Sprint UA fix — neutral user-agent on DILA opendata

- **Delivery date**: 2026-05-15
- **Commits**: `40ed5acd`, `718f509`, `4bcc4d1`
- **Scope**: replaced identifying user-agent `Lucie-Legifrance-Sync` with neutral Safari UA. New constant `BEAUME_USER_AGENT` in `lucie_v1_standalone/knowledge_legifrance/downloader.py:40`, applied at both call sites.
- **Tests**: 4 tests in `tests/test_legifrance/test_user_agent_neutre.py`, including a regression guard (`test_regression_user_agent_neutre_2026_05_13`) that does a repo-wide grep for the old identifier and fails if it reappears.

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
