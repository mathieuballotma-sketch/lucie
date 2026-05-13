# Changelog

*[Lire en français](CHANGELOG.fr.md)*

All notable Beaume releases (formerly Lucie, rebranded 2026-05-02) are documented here.
Format inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.0.1-cleanup] — 2026-05-08

Major post-rebrand cleanup (Sprint 1 + 1bis + 1ter trilogy). No
breaking user-facing change: legacy `LUCIE_*` env variables stay
accepted as deprecated aliases.

### Sprint 1ter — Final rebrand consistency

- **launchd**: label `com.lucie.legifrance.sync` → `com.beaume.legifrance.sync`
  (`scripts/install_launchd.sh`, `scripts/uninstall_launchd.sh`,
  `scripts/legifrance_rollback.sh`).
- **env vars**: prefix `LUCIE_*` → `BEAUME_*` via centralized helper
  `lucie_v1_standalone.config.env_legacy()` which emits a
  `DeprecationWarning` + WARNING log (once per variable) if the old
  name is used. 14 variables migrated (`LEGIFRANCE`, `LEGIFRANCE_DIR`,
  `LOG_LEVEL`, `QUIET`, `STREAM`, `OLLAMA_KEEP_ALIVE`, `SPEED_MODEL`,
  `PROFILE`, `CACHE`, `CACHE_DRY_RUN`, `CACHE_MAXSIZE`,
  `CACHE_TTL_SECONDS`, `SKIP_WARMUP`, `DIAG_MODEL`).
- **scripts**: added `scripts/migrate_launchd_lucie_to_beaume.sh`
  (idempotent, to run once post-merge to migrate the already-
  installed job).
- **docs**: README updated (env vars table, examples, log/launchd
  paths). Historical mentions preserved.
- **tests**: `tests/test_env_legacy_compat.py` covers BEAUME_*
  priority, LUCIE_* fallback, single warning, default.

### Sprint 1bis — DB cleanup (note, already merged)

- Filesystem path migration Lucie → Beaume (Légifrance DB, logs).
- −6.7 GB freed.

### Sprint 1 — Major cleanup (note, already merged)

- Traceability banner, removal of obsolete files.

---

## [1.2.1-swiss-watch] — 2026-05-08

"Swiss watch" sprint — targeted polish to close out Beaume v1 with
the Swiss-watch quality required before lawyer outreach week
May 12-18, 2026 (30 firms targeted, 2-3 pilots signed). No
architecture refactor, no feature creep — only the 7 product rules
applied.

### ✨ Added (per Swiss-watch rule)

#### Rule 1 — Truth rule (already at 95% — KI-003 documented)
- No major change; the audit confirmed that Cerveau Oiseaux v2,
  the deterministic Verifier and the async pipeline are already
  compliant.

#### Rule 2 — Swiss watch / silent elegance
- **`verifier_score` badge under each answer** (`app/ui/hud_native.py`):
  green ≥ 90%, amber 70-89%, red < 70%. Hidden on early refusal and
  on 0 citations extracted (avoids KI-003 "vacuously true").
- Badge tooltip exposes `X verified citations out of Y` + verdict.

#### Rule 3 — 100% on-device
- Enriched badge tooltip: "You can turn off your Wi-Fi, Beaume keeps
  working" + local path of the badge propagated on the lock icon and
  label.

#### Rule 4 — Silent archetype
- Pipeline disclaimer `Lucie V1 → Beaume v1`.
- System prompts (`direct_system.txt`, `redacteur_search_system.txt`,
  `small_talk_handler.py`) consistent rebrand.

#### Rule 5 — Lawyer psychological plan
- **Welcome line** on first launch (3 promises: 100% on-device,
  verification, clickable sources) — `welcomed_v1` flag in
  `~/Library/Application Support/Beaume/prefs.json`.
- `verifier_score` badge (cf. rule 2) — the lawyer sees the
  reliability.

#### Rule 6 — Radical transparency
- **"What Beaume knows about you" page**: enriched popover with
  header, 100% on-device subtitle + path, list of 5 memory types,
  "Erase all memory" button with **double confirmation** (NSAlert
  irreversibility + "ERASE" input).
- Backend: `MemoryStore.reset()` + `PersonalMemory.reset_all()` +
  `AbstractMemory.clear()`.

#### Rule 7 — Simulated awareness
- No change (already functional — 27 existing memory tests OK,
  + 5 new reset tests).

### 🔄 Renamed

- **Lucie → Beaume** (official rebrand 2026-05-02 finalized in code):
  - All user-facing strings in the HUD (sender name, states,
    notifications).
  - Pipeline disclaimer + system prompts (small_talk, direct,
    redacteur_search).
  - `main_hud.py` (header + launch log).
  - **Preserved** (risky internal rename): `LucieState` class,
    `_lucie_state` variable, `lucie_v1_standalone.*` imports,
    `LUCIE_*` env variables (backward compatibility).
- **Python module alias** (new): `beaume/__init__.py` re-exports
  everything from `lucie_v1_standalone/` — `from beaume import
  pipeline` works. Physical package rename deferred post-pilot.
- **Auto-idempotent data dir migration**:
  `~/Library/Application Support/Lucie` → `Beaume` on first launch
  (best-effort, legacy fallback if copytree fails).

### 🛠️ Modified

- `PipelineResponse` extended: `citations_ok`, `citations_invalid`,
  `verdict` (optional fields). `verifier_score` now propagated all
  the way to the HUD via the `_VERIFICATION_META` ContextVar (set by
  `_format_final`, read by `run()` and `run_stream()`).
- `bench/run_legal_traps.py`: `--prompts` flag to point to
  `bench/swiss_watch_50.json`; `response_to_dict` widened (verdict,
  citations_ok, citations_invalid, citations_total); synthetic
  `_swiss_watch_hallucination_signal` field for the trap rule
  (refusal OR score < 0.5 OR mention "not in my sources").

### 🧪 Tests

- **New**:
  - `tests/test_pipeline_response_score.py` — 10 tests on
    `verifier_score` propagation, consistent counts, Beaume
    disclaimer.
  - `tests/memory/test_memory_reset.py` — 5 tests on reset (clears
    nodes/patterns, counts, observe post-reset, idempotence).
- **Swiss-watch 50-question battery** (`bench/swiss_watch_50.json`):
  - 10 lic_eco, 10 lic_perso, 5 conges_rtt, 5 dem_rupture_conv,
    5 article_inexistant, 5 hors_scope, 5 petites_taches, 5 pieges.
  - 3 new rules: `swiss_watch_quality`, `swiss_watch_small_talk`,
    `swiss_watch_hallucination_blocked`.

### 📚 Documentation

- `KNOWN_ISSUES.md` updated (see dedicated section).
- Sprint plan: `~/.claude/plans/qui-tu-es-jiggly-twilight.md`.
- Final report: `~/Desktop/Rapport_v1-Swiss-watch_2026-05-06.md`.

### 🏷️ Tag

- Local tag `v1.2.1-swiss-watch` (no push — Mathieu validates
  visually before push).

---

## [1.0.0] — 2026-05-02

First *production-ready* release of Beaume (formerly Lucie). Three
P0s identified by the parallel audits of April 30 have been
addressed; one more was reclassified P1 and documented.

### ✨ Added

- **Auto-detected Légifrance bootstrap** at HUD startup
  (`lucie_v1_standalone/legifrance_bootstrap.py`).
  - If `legi.sqlite` exists → `LUCIE_LEGIFRANCE=1` flag set
    in-process (the 4.6 GB DILA database becomes the primary source
    for the retriever).
  - If the database is older than 30 days → HUD WARNING banner,
    incremental sync driven by launchd.
  - If the database is missing → automatic install of the launchd
    agent (`scripts/install_launchd.sh`) then `legifrance_sync.py
    --first-run` in a daemon thread. Beaume runs on the whitelist
    (3,700 CT codes) while the sync completes.
  - The bootstrap returns within 100 ms: all long jobs (download,
    install) are offloaded to the background, never blocking.
  - Skippable via `LUCIE_SKIP_LEGIFRANCE_BOOTSTRAP=1`.
- **Pedagogical detector + domain terms** in
  `lucie_v1_standalone/dialogue/intent_classifier.py`.
  - A question like "what is a rupture conventionnelle?", "role of
    the CSE?", "how does the notice period work?", "what is a CDD
    used for?" now switches to `PRECISE_LEGAL` instead of
    `IMPRECISE_LEGAL` → goes to the LLM (with RAG context) instead
    of being short-circuited.
  - The `IMPRECISE_LEGAL` safety net stays active for genuinely
    vague questions ("I have a problem", "is it legal?", "what
    should I do?").
- **Deterministic refusal of forced fabrication** (Gate 0 of
  Cerveau Oiseau, `lucie_v1_standalone/dialogue/invention_guard.py`).
  - "Invent me a case law", "fabricate a precedent", "no one will
    check" → immediate refusal with explicit message recalling the
    truth rule. Cost < 1 ms, zero LLM.

### 🧪 Tests

- **Global suite**: 341 tests `lucie_v1_standalone/tests/` + 170
  tests `tests/` (1 E2E test `test_pipeline_smoke` requires Ollama
  active — expected).
- **New**: 6 tests `test_legifrance_bootstrap.py`, 12 tests
  `test_intent_classifier_pedagogical.py`, 17 tests
  `test_invention_guard.py` — i.e. **35 tests** added.
- **Adversarial battery** (`test_adversarial_pre_v1.py`, 101 tests):
  the B1/B5/H1 fixes are expected as net gain after Légifrance is
  active — to be re-run on Mathieu's machine with Ollama and the
  DILA DB active.

### 📚 Documentation

- `KNOWN_ISSUES.md`: added the TTFT content ~18 s on Gemma4
  chain-of-thought (the HUD displays "thinking" at TTFT 1.25 s to
  paper over the user perception — target < 5 s deferred post-v1,
  requires runtime migration).

### ⚠️ Known and accepted for v1

- **TTFT content ~18 s on Gemma4 chain-of-thought** — the cause is
  the thinking→content buffering on the Ollama server side, out of
  scope for a client fix. The HUD displays "thinking" at
  **TTFT 1.25 s**: the user immediately perceives Beaume working.
  Migration to `llama-cpp` or compression of the redacteur system
  prompt planned post-v1 (dedicated sprint, see
  `PERF_OPTIM_PROGRESS.md`).
- **JudiLibre / Cour de cassation sync** not wired. The manifesto
  promises judgment verification; no upstream source implemented to
  date (cf. `Rapport_Synchro_Lois_Lucie_2026-04-30.md` §1.2 and §5
  Action 3). Dedicated sprint post-v1.

### 🚫 Deferred post-v1

- `llama-cpp` migration (resolves TTFT content)
- JudiLibre / Cour de cassation sync
- Repeated-intent LRU cache (R5 Speed-Optimizer sprint)
- Compression of `redacteur_system.txt` (1,180 → < 400 tokens)
- Multi-segments (beyond employment law)
- Voice (audio I/O)
- P2P (`export_for_p2p()` exists without an X25519 channel)
- Hardware orchestrator

---

## [0.5.6-fix-regression] — 2026-04-30

- `pipeline.run_stream()` was not calling
  `_run_cerveau_oiseau_gates()` — the non-existent article
  `L.1234-999` traversed the entire pipeline (~26 s) instead of
  being refused under 100 ms.
- `IMPRECISE_LEGAL` handler added in `run_stream()` (parity with
  `run()`).
- `verificateur`: discriminating log on 0 citation (KB refusal vs
  hallucination).

(For earlier versions, see `git log --tags`.)
