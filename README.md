<div align="center">

# Lucie

### Local-first AI assistant for lawyers. 100% on-device. Truth rule absolute.

[![Version](https://img.shields.io/badge/version-v0.5.0--cerveau--oiseaux-blue)](https://github.com/mathieuballotma-sketch/lucie)
[![Tests](https://img.shields.io/badge/tests-375%20passing-brightgreen)]()
[![Lighthouse](https://img.shields.io/badge/lighthouse-100%2F100%2F100%2F100-brightgreen)](https://lucie-site.vercel.app)
[![EU AI Act](https://img.shields.io/badge/EU%20AI%20Act-compliant%20by%20design-blue)]()

**[lucie-site.vercel.app](https://lucie-site.vercel.app)**

</div>

---

## Overview

Lucie runs entirely on the lawyer's Mac. She consults Légifrance — the French official legal database, indexed locally — drafts procedural documents, and refuses honestly when she does not know.

The defining rule is enforced at the architecture level: **Lucie never invents, never hallucinates, never lies.**

---

## Capabilities

- al legal reasoning** — answers grounded in a local index of 281 DILA Légifrance archives. No external API at inference time.
- **Deterministic refusal** — non-citable article references are rejected in under 50 ms, before any LLM is invoked.
- **Source-backed responses** — every claim is linked to a specific article or decision from the local index.
- **Adaptive memory** — embedding-based reinforcement and decay per user interaction. Persistent, local, and personalised.
- **Procedural drafting** — letters, contestations, and structured legal documents with live citations.
- **Audit trail** — each response exposes sources, confidence score, and refusal reasons.
- **Real-time HUD** — the lawyer sees what Lucie consults, in what order, with what result.
- **macOS-native** — code-signed app, notarisation-ready.

---

## Proof of progress — v0.5.0-cerveau-oiseaux · April 22, 2026

| Measure | Value |
|---|---|
| Passing tests | 375 |
| Documented product bricks | 138 |
| Legal archives indexed Légifrance) |
| Refusal latency on invalid reference | <50 ms, 0 LLM call |
| Production site Lighthouse | 100 / 100 / 100 / 100 |
| Inference environment | 100% local (Ollama + Gemma 3) |
| External API calls at inference | 0 |

---

## Architecture — layered execution paths

Lucie routes each request through three layers, only invoking deeper layers when needed:

1. **Deterministic pre-LLM layer** — low-latency validation filters (<50 ms). Article reference validation against the local index, out-of-scope detection, fuzzy legal matching. No LLM call, no hallucination surface, no token cost.
2. **Parallel specialised agents** — autonomous processes per application (Mail, Calendar, Notes, Word…), communicating through an internal event bus. Each agent operates with its own context and tool subset.
3. **Composition and planning orchestrator** — invoked only when multi-step reasoning is required. Produces the final user-facing response by composing outputs from the previous layers.

**Memory layering-based, with reinforcement and decay per user interaction. State is persisted locally and personalised across sessions. Two Lucie instances diverge by construction after sustained use.

**Truth enforcement** — deterministic refusal before the LLM, post-generation citation verification against the local index, and full audit trail exposed to the user.

---

## Security and privacy

- **Nothing leaves the device at inference.** LLM local, legal database local, memory local.
- **No cookies, no tracking, no analytics** on the site or in the app.
- **RGPD** — no personal data processed outside the user's machine.
- **EU AI Act (August 2026)** — compliance by construction, not by retrofitting.
- **macOS sandbox** — entitlements model enforced through the OS.

---

## Roadmap

- **v1** — pilot with lawyers · August 2026
- **v1.1, v1.2, v1.3** — incremental improvements after launch, without breaking the v1 contract
- **v2** — opens to other domains that demand the same rigor
- **v3** — opens toalised per user

Each version is the prerequisite of the next.

---

## Repository layout

This public repository is a showcase.

The core implementation remains in private repositories:

- Application code (pipeline, verification, memory, HUD, packaging)
- Légifrance local index derived from DILA under DILA licensing terms
- Adaptive memory architecture
- Evaluation harness and internal benchmarks

Selected modules can be shared under NDA with serious reviewers.

---

## Status

Tag v0.5.0-cerveau-oiseaux is the current public reference. The production site at [lucie-site.vercel.app](https://lucie-site.vercel.app) reflects the current product.
