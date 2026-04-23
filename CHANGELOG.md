# Changelog

All notable releases of Lucie, from first prototype to current.

## v0.5.0-cerveau-oiseaux — 2026-04-22

- Deterministic Verificateur: 0 LLM call on the refusal path
- 375 passing tests (from 270 in previous release)
- Pre-LLM vaon layer with <50 ms latency on invalid article references
- Whitelist of 400 most frequent French labour code references for fallback
- ArticleResolver hook prepared for v2 Internet fallback integration

## v0.4.4 — 2026-04-22

- HUD scroll fix: respects user scroll position during agent updates
- Merged to main after v0.4.3

## v0.4.3 — 2026-04-22

- Phase 1ter: early article validation, out-of-scope detection, fuzzy legal matching
- Ollama timeout extended to 300 s, OLLAMA_KEEP_ALIVE 24 h

## v0.4.2 — 2026-04-22

- Fix IntentClassifier: routing of technical questions
- Lucie now refuses "Que dit l'article L.1234-999" correctly in <1 s

## v0.3.1 — 2026-04-20

- Legifrance CLI: SSL certificate handling, proper command-line interface
- 281 DILA archives indexed locally

## v0.2.2.1 — 2026-04-18

- py2app packaging fix: excluded PyQt5 hooks
- macOS .app builds successfully with Info.plist and Lucie.entitlements

## v0.2.0-beta — 2026-04-15

- First beta of the deterministic pipeline
- Initial in local Ollama + Gemma 3
- Brain-inspired memory module with Hebbian plasticity (LTP/LTD) integrated

---

Tag history is the source of truth. Private implementation remains in private repositories.
