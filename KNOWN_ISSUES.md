# KNOWN_ISSUES — Beaume v1 (formerly Lucie)

*[Lire en français](KNOWN_ISSUES.fr.md)*

Tracking file for known issues, classified by block and priority.
Updated by each agent during their findings.

---

## v1.2.1-swiss-watch — 2026-05-08

### KI-SW-001 — Pipeline cache does not propagate verifier_score
**Status:** OPEN (POST-PILOT)
**Priority:** MEDIUM
**Detected by:** Swiss-watch battery run #1 (cache enabled).
**Symptom:** When `LUCIE_CACHE=1` (default), an already-seen query
returns in 0 ms but `verifier_score=0.0` (PipelineResponse default)
because the cache only stores the `answer` string, not the Verifier
metadata. On the 50q battery, ~25% of lic_eco cases were impacted.
**Workaround:** Run the battery with `LUCIE_CACHE=0` (the final
report was made with cache off for honest measurement).
**Fix v1.3:** Extend the cache to store the full `PipelineResponse`
(citations + score + verdict + counts), not just the `answer`.
Touches `lucie_v1_standalone/cache.py` and the `_run_pipeline_cached`
wrapper.

### KI-SW-002 — Physical Python package rename deferred
**Status:** OPEN (explicit POST-PILOT)
**Priority:** LOW
**Symptom:** The internal code is still called
`lucie_v1_standalone/` despite the official Beaume rebrand on
2026-05-02. Legacy imports (`from lucie_v1_standalone import …`)
remain functional and a `beaume/` alias re-exports everything
(transparent client side).
**Why deferred:** The physical rename (`git mv lucie_v1_standalone
beaume_core` + sed across ~200 import sites) is judged risky just
before outreach. All user-facing names are already migrated (HUD,
disclaimer, prompts, sender name).
**Fix v1.3 (post-pilot):** physical rename + alias removal.

### KI-SW-003 — Swiss-watch battery — `lic_perso` / `conges_rtt` corpus weak
**Status:** OPEN (KNOWN LIMITATION)
**Priority:** MEDIUM
**Symptom:** Beaume v1 focuses on economic dismissal (sweet spot).
The curated corpus is deliberately minimal on lic_perso, leaves/RTT,
resignation/conventional rupture. The `verifier_score_min`
thresholds were relaxed to 0.5 on these categories (vs 0.85 on
lic_eco) to measure the gap, not to hide the weakness.
**Plan v1.3:** extend the curated base + full Légifrance retriever
on these 4 sub-domains. Cf. `bench/swiss_watch_50.json` categories.

### KI-SW-004 — `test_pipeline_response_score`: 0 citation → score=1.0
**Status:** DEFERRED (legacy of KI-003 v1.0.0)
**Priority:** LOW
**Symptom:** When the Verifier finds no citation to extract
(`nb_total=0`), it returns `score=1.0` (vacuously true).
**Swiss-watch mitigation:** The HUD now hides the badge in this
case (cf. `_update_score_badge` which requires `n_total > 0`). The
lawyer no longer sees a fake 100% on refusals.
**Fix v1.3:** `verificateur.py` must distinguish `n_total=0` ("not
applicable") from a real score. Additional `applicable: bool` field.

---

## v1.0.0 — 2026-05-02

### KI-V1-001 — TTFT content ~18 s on Gemma4 chain-of-thought
**Status:** OPEN (P1, accepted for v1)
**Priority:** MEDIUM (post-v1)
**Detected by:** Speed-Diag sprint (commit `3368682`), confirmed by
the pre-v1 architecture audit on 2026-04-30.
**Symptom:** The first *content* token of the answer arrives ~18 s
after the question (v1 target: ≤ 5 s). The first *thinking* token
arrives in 1.25 s.
**Root cause:** thinking→content buffering **on the Ollama server
side**. Gemma4 absorbs the chain-of-thought internally before
releasing content, out of scope for a client fix (httpx
`aiter_lines` is not the culprit).
**v1 mitigation:** The HUD displays "thinking" from **TTFT 1.25 s**
— the user immediately perceives Beaume working
(`ollama_client.generate_stream_chat`, commit `8d96b55`).
**Plan post-v1:** dedicated sprint — evaluate `llama-cpp`
migration, compress `redacteur_system.txt` (1,180 → < 400 tokens),
LRU cache for repeated intent. Cf. `PERF_OPTIM_PROGRESS.md` §R5/R7.

### KI-V1-002 — `test_pipeline_smoke` requires Ollama active
**Status:** EXPECTED (E2E test)
**Priority:** LOW
**Detected by:** `tests/test_legal_pipeline_v1.py::test_pipeline_smoke`
**Symptom:** The test times out after 300 s with "Beaume is taking
longer than expected" if Ollama is not active or has not loaded the
model.
**Note:** Intentional behavior. The test does a full round-trip
against `localhost:11434`. To skip in CI without Ollama. Not a
regression.

### KI-V1-003 — JudiLibre / Cour de cassation sync not wired
**Status:** OPEN (post-v1)
**Priority:** HIGH (deferred)
**Detected by:** `Rapport_Synchro_Lois_Lucie_2026-04-30.md` §1.2.
**Symptom:** The retriever exposes a cosmetic `jurisprudences`
field (filter by ID pattern) but has no upstream source. Any
judgment cited by the LLM would be hallucinated — only
anti-hallucination heuristics block it on the Verifier side.
**Plan post-v1:** `knowledge_judilibre/` module symmetrical to
`knowledge_legifrance/`, source PISTE API
(`api.piste.gouv.fr/cassation/judilibre/v1.0`) with free OAuth, or
JuriCA `data.gouv.fr` monthly exports as a *zero-auth* alternative.

---

## Block 0 — exhaustive corpus findings (2026-04-17)

### KI-001 — OOS filter insufficient for medico-social questions
**Status:** OPEN
**Priority:** MEDIUM
**Detected by:** runner_exhaustif.py, request OOS-01
**Symptom:** A question about dismissal *during* sick leave
("dismiss me during my long-term sick leave") passes the router
because the verb "dismiss" is present. The pipeline produces an
answer — honestly limited ("No source available") — but does not
politely refuse.
**Probable root cause:** `_SEARCH_TRIGGERS` (router.py) is
keyword-based. "Dismiss" is a strong trigger, but co-presence with
"sickness/leave/inability" should trigger an out-of-scope filter.
**Candidate:** Block 1 (router refactor) — add a `_OOS_OVERRIDES`
list that cancels a trigger if exclusion terms are present.

### KI-002 — Reader fails to extract JSON from a simple text document
**Status:** OPEN
**Priority:** HIGH
**Detected by:** test_pipeline_smoke (executed in Block 0)
**Symptom:** When `document_text` contains a plain-text dismissal
letter, the Reader returns "JSON extraction impossible after retry"
and the pipeline switches to an error message instead of analyzing
the document.
**Probable root cause:** The gemma4:e4b model does not always
produce valid JSON on the Reader prompt — lack of robustness in the
prompt or in the LLM-response parsing logic.
**Candidate:** Block 2 (Reader refactor) — improve the prompt and
the JSON retry/parsing logic.

### KI-003 — Verifier: vacuous score when no citation is made
**Status:** OPEN
**Priority:** LOW
**Detected by:** runner_exhaustif.py, request ADV-04
**Symptom:** When the pipeline answers "No source available"
without citing articles, the verifier returns score=1.00 (vacuously
true: 0 invalid citations / 0 total = 100%). This score can be
misleading for the user — a "VALIDATED 100%" on a refusal.
**Root cause:** `verificateur.py` computes `nb_ok / nb_total`. If
`nb_total == 0`, returns 1.0 by default.
**Candidate:** Block 2 (Verifier refactor) — distinguish "no
citation = not applicable" from "all citations valid".

### KI-004 — B2 candidate: applicability date check
**Status:** OPEN (KNOWN LIMITATION)
**Priority:** LOW (post-pilot)
**Detected by:** corpus DATE-01 / DATE-02
**Symptom:** The pipeline ignores date mentions in the request
("as of January 1, 2020?" vs "as of January 1, 2026?"). Both
questions receive the same answer based on the current curated
base, without flagging the absence of a temporal check.
**Note:** This behavior is correct for v1 (static curated base),
but it should be flagged to the user.
**Candidate:** Block 2 — add a warning if a date is detected in the
request and the base has no temporal marking.

### KI-005 — runner_exhaustif detector: false positives on ADV-01 and ADV-04
**Status:** CLOSED (false positive in the detector, pipeline correct)
**Detected by:** post-runner analysis
**Note:** The `runner_exhaustif.py` detector flags any text
containing "9999" or "2080", including when the model cites these
values to explicitly refute them. The answers to both requests are
correct: the pipeline explicitly says that L.9999-99 and Cass. soc.
2080 do not exist in the base. Fix to apply to the runner for
Block 1: use a more precise regex for citation detection.
