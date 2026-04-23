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

## What Lucie does

Lucie runs entirely on the lawyer's Mac. She consults Légifrance (the French official legal database, indexed locally), drafts procedural documents, and refuses honestly when she doesn't know.

The defining rule is enforced at the architecture level: **Lucie never invents, never hallucinates, never lies**.

---

## Capabilities

- **Local legal reasoning** — answebased on a local index of 281 DILA Légifrance archives, no external API at inference
- **Deterministic refusal** — a non-citable article reference is rejected in under 50 ms, before any LLM is invoked
- **Source-backed responses** — every claim is linked to a specific article or decision from the local index
- **Adaptive memory** — Hebbian plasticity (LTP/LTD), persistent and unique per user
- **Procedural drafting** — letters, contestations, and structured documents with live citations
- **Audit trail** — each response exposes sources, confidence score, and refusal reasons
- **Real-time HUD** — the lawyer sees what Lucie consults, in what order, with what result
- **macOS-native** — code-signed \`.app\`, notarisation-ready

---

## Proof of progress (v0.5.0-cerveau-oiseaux, April 22, 2026)

| Measure | Value |
|---|---|
| Passing tests | 375 |
| Documented product bricks | 138 |
| Legal archives indexed locally | 281 (DILA Légifrance) |
| Refusal latency on invalid article | <50 ms, 0 LLM con site Lighthouse | 100 / 100 / 100 / 100 |
| Inference environment | 100% local (Ollama + Gemma 3) |

---

## Architecture (high level)

Lucie is built on a **tri-brain** model inspired by biology:

- **Bird brain** — fast deterministic filters (<50 ms). Early article validation, out-of-scope detection, fuzzy legal matching. No LLM, no hallucination surface.
- **Octopus brain** — specialised autonomous agents per application (Mail, Calendar, Notes, Word…), communicating through an event bus.
- **Human brain** — a planner and composer that orchestrates the two others when reasoning is required.

**Memory is Hebbian** — associations strengthen with use, weaken with disuse, persist locally per user. No two Lucies are the same after sustained interaction.

**The truth rule is enforced at multiple layers** — deterministic refusal before the LLM, post-generation citation verification against the local index, audit trail exposed to the user.

---

## Security and privacy

- Nothing leaves the device . LLM local, legal database local, memory local.
- No cookies, no tracking, no analytics on the site or in the app.
- RGPD: no personal data processed outside the user's machine.
- EU AI Act (August 2026): compliance by construction, not by retrofitting.
- macOS entitlements model enforced through the sandbox.

---

## Roadmap

- **v1** — pilot with lawyers (August 2026)
- **v1.1, v1.2, v1.3** — incremental improvements after launch, without breaking the v1 contract
- **v2** — opens to other domains that demand the same rigor
- **v3** — opens to everyone, personalised per user

Each version is the prerequisite of the next.

---

## Private repositories

The core implementation is kept in private repositories:

- Application code (Vérificateur, memory, pipeline, HUD, packaging)
- Légifrance local index derived from DILA under DILA licensing terms
- Brain-inspired memory architecture
- Evaluation harness and internal benchmarks

Specific modules may be shared privately with serious reviewers under N## Status

Tag \`v0.5.0-cerveau-oiseaux\` is the current public reference. The production site at [lucie-site.vercel.app](https://lucie-site.vercel.app) reflects the current product.
