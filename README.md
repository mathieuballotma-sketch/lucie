> **Languages:** [🇬🇧 English](README.md) · [🇫🇷 Français](README.fr.md)


<div align="center">

# Lucie

### Local-first AI assistant for lawyers. 100% on-device. Truth rule absolute.

[![Version](https://img.shields.io/badge/version-v0.5.0-blue)](https://github.com/mathieuballotma-sketch/lucie)
[![Tests](https://img.shields.io/badge/tests-375%20passing-brightgreen)]()
[![Lighthouse](https://img.shields.io/badge/lighthouse-100%2F100%2F100%2F100-brightgreen)](https://lucie-site.vercel.app)
[![EU AI Act](https://img.shields.io/badge/EU%20AI%20Act-compliant%20by%20design-blue)]()
[![Local-first](https://img.shields.io/badge/inference-100%25%20local-success)]()

**[lucie-site.vercel.app](https://lucie-site.vercel.app)**

</div>

---

## Overview

Lucie runs entirely on the lawyer's Mac. She consults Légifrance — the French official legal database, indexed locally — drafts procedural documents, and refuses honestly when she does not k
The defining rule is enforced at the architecture level: **Lucie never invents, never hallucinates, never lies.**

---

## Capabilities

- **Local legal reasoning** — answers grounded in a local index of 281 DILA Légifrance archives. No external API at inference.
- **Deterministic refusal** — non-citable article references are rejected in under 50 ms, before any LLM is invoked.
- **Source-backed responses** — every claim is linked to a specific article or decision from the local index.
- **Adaptive memory** — embedding-based reinforcement and decay per user interaction. Persistent, local, and personalised.
- **Procedural drafting** — letters, contestations, and structured legal documents with live citations.
- **Audit trail** — each response exposes sources, confidence score, and refusal reasons.
- **Real-time HUD** — the lawyer sees what Lucie consults, in what order, with what result.
- **macOS-native** — code-signed application, notarisation-ready.

---

## Proof of progress — v0.5.0  Measure | Value |
|---|---|
| Passing tests | 375 |
| Documented product bricks | 138 |
| Legal archives indexed locally | 281 (DILA Légifrance) |
| Refusal latency on invalid reference | <50 ms, 0 LLM call |
| Production site Lighthouse | 100 / 100 / 100 / 100 |
| Inference environment | 100% local (Ollama + Gemma 3) |
| External API calls at inference | 0 |
| Released git tags | 11 (v0.2.0-beta → v0.5.0) |

---

## Architecture — layered execution paths

Lucie routes every request through three layers, invoking deeper layers only when needed.

1. **Deterministic pre-LLM layer** — low-latency validation filters (<50 ms). Regex extraction of legal references, local index lookup, out-of-scope detection, fuzzy legal matching. Zero LLM call. Zero hallucination surface. Zero token cost.
2. **Specialised parallel processes** — autonomous workers per integrated application (Mail, Calendar, Notes, Word, etc.), communicating through an internal event bus. Each worker operates on its own context and tool s **Composition and planning orchestrator** — the only layer authorised to invoke the local LLM, and only when multi-step reasoning is strictly required. Its output is fed back into the verification layer before reaching the user.

**Memory layer** — embedding-based. Associations strengthen with use and decay with disuse, persisted locally per user. Two instances diverge by construction after sustained interaction.

**Truth enforcement** operates at three points: deterministic refusal before any LLM call, post-generation citation verification against the local index, and a full audit trail exposed to the user.

---

## How Lucie processes a requestUSER QUERY
                        │
                        ▼
        ┌───────────────────────────────┐
        │ Deterministic pre-LLM layer   │
        │   · regex extraction          │
        │   · local index lookup        │
        │   · out-of-scope detection    │
        │   · fuzzy legal matching      │
        │       (< 50 ms, 0 LLM)        │
        └───────────────┬───────────────┘
                        │
           ┌────────────┴────────────┐
           │                         │
    INVALID reference             VALID query
           │                         │
           ▼                         ▼
 ┌─────────────────┐      ┌──────────────────────┐
 │ HONEST REFUSAL                        │    (local LLM, if any)   │
                        └──────────┬───────────────┘
                                   │
                                   ▼
                        ┌──────────────────────────┐
                        │ Citation verification    │
                        │ against local index      │
                        └──────────┬───────────────┘
                                   │
                                   ▼
                        ┌──────────────────────────┐
                        │ Response + audit trail   │
                        │ (sources, confidence)    │
                        └──────────────────────────┘A simplified, runnable demonstration of this deterministic refusal pattern lives in [`examples/truth_rule_proof.py`](examples/truth_rule_proof.py) — seven assertions pass, zero external dependencies.

---

## Video demo

> **Coming soon** — a short video demo of the truth rule in action will be posted here.

---


## Lucie in action

Screenshots of the macOS HUD, running locally on the lawyer's Mac.

![Lucie workflow — consults articles, prepares response, verifies each citation](assets/lucie-hud-1.png)

![Lucie drafts a structured legal letter with live placeholders](assets/lucie-hud-2.png)

![Lucie cites official article references from the local Légifrance index](assets/lucie-hud-3.png)

Every response is source-backed. When Lucie cannot cite, Lucie refuses.

---

## Security and privacy

- **Nothing leaves the device at inference.** LLM local, legal database local, memory local.
- **No cookies, no tracking, no analytics** on the site or in the app.
- **RGPD** — no personal data processed outside the user's machine.
- **EU AI Act (August 2026)** — compliance by construction, not by retrofitting.
- andbox** — OS-level entitlements enforced.

---

## Roadmap

- **v1** — pilot with lawyers · August 2026
- **v1.1, v1.2, v1.3** — incremental improvements after launch, without breaking the v1 contract
- **v2** — opens to other domains that demand the same rigor
- **v3** — opens to everyone, personalised per user

Each version is the prerequisite of the next.

---

## Repository layout

This public repository is a showcase.

- [`README.md`](README.md) — product overview and architecture
- [`CHANGELOG.md`](CHANGELOG.md) — release history from v0.2.0-beta to current
- [`assets/`](assets/) — screenshots of the macOS HUD in production
- [`examples/truth_rule_proof.py`](examples/truth_rule_proof.py) — runnable demonstration of the deterministic refusal pattern

The core implementation remains in private repositories under a proprietary licence:

- Application code (pipeline, verification, memory, HUD, packaging)
- Légifrance local index derived from DILA under DILA licensing terms
- Adaptive - System prompts and internal evaluation harness

Selected modules can be shared under NDA with serious reviewers.

---

## Status

Tag `v0.5.0` is the current public reference. The production site at [lucie-site.vercel.app](https://lucie-site.vercel.app) reflects the current product.
