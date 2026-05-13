# Beaume Principles

*[Lire en français](PRINCIPLES.fr.md)*

Six principles drive every technical and product decision at Beaume.
When a trade-off is unclear, we come back to this list.

---

## 1. 100% on-device

A lawyer's data never leaves their machine. No outbound calls at
runtime apart from `127.0.0.1:11434` (local Ollama). No telemetry.
No account. No user-side API key.

Violation criterion: a single `requests.post()` to an external domain
in production code. Verifiable by grep.

## 2. Absolute truth rule

Beaume prefers to refuse rather than hallucinate. Any Légifrance
citation absent from the local index is rejected *before* it reaches
the user. Any metric communicated publicly (README, batteries,
sprints) must be reproducible — see
[`docs/EVIDENCE.md`](docs/EVIDENCE.md) and
[`docs/REPRODUCE.md`](docs/REPRODUCE.md).

Violation criterion: a public claim without clickable evidence in the
code or in the reports.

## 3. Silent architect

No marketing. No superlatives. No "revolutionary", "AI-powered",
"next-gen" pitch. Numbers speak; code speaks. Beaume's voice is
factual, measurable, sober. The HUD is silent except when it answers.

Violation criterion: a marketing word in a commit message, a README,
a system prompt.

## 4. Radical transparency

What is broken is documented ([`KNOWN_ISSUES.md`](KNOWN_ISSUES.md)).
What changed is dated ([`CHANGELOG.md`](CHANGELOG.md)). What shipped
in a sprint is summarized publicly
([`docs/sprints/SUMMARY.md`](docs/sprints/SUMMARY.md)).

What stays **non-public** (competitive reserve): diagnostic details,
empirical thresholds, finely tuned prompts, modules in stash. See
[`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

Violation criterion: a known bug undocumented; a public metric
without a verification method.

## 5. Per-user adaptive memory

No two Beaume instances are identical. Memory (preferences,
shortcuts, firm context) takes root locally, on the user's machine.
Two neighboring M2 Macs diverge after a few weeks of use.

Violation criterion: a shared cloud memory, or an exported
fingerprint.

## 6. Swiss-watch quality

Deterministic precision **before** LLM creativity. The intent
router, the Légifrance retriever and the Verifier are deterministic.
The LLM only steps in to phrase an answer from material that has
already been validated.

Every LLM step is traceable: `verifier_score` shown in the HUD,
clickable citations linking to the exact article, exportable PAF
audit.

Violation criterion: an LLM called without a deterministic gate
upstream, or an answer exposed without a `verifier_score`.

---

## Mapping to code

| Principle | Component that enforces it |
|-----------|----------------------------|
| 100% on-device | [`lucie_v1_standalone/ollama_client.py`](lucie_v1_standalone/ollama_client.py) — base URL = `127.0.0.1:11434` |
| Truth rule | [`lucie_v1_standalone/verificateur.py`](lucie_v1_standalone/verificateur.py) + [`tests/test_truth_rule_pattern.py`](tests/test_truth_rule_pattern.py) |
| Silent architect | Human code review, this file as the guardrail |
| Radical transparency | [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md), [`CHANGELOG.md`](CHANGELOG.md), [`docs/sprints/SUMMARY.md`](docs/sprints/SUMMARY.md), [`docs/EVIDENCE.md`](docs/EVIDENCE.md), [`docs/REPRODUCE.md`](docs/REPRODUCE.md) |
| Adaptive memory | [`lucie_v1_standalone/memory/`](lucie_v1_standalone/memory/) (`personal.py`, `abstract.py`, `store.py`, `sanitizer.py`) |
| Swiss-watch quality | [`lucie_v1_standalone/dialogue/intent_classifier.py`](lucie_v1_standalone/dialogue/intent_classifier.py), [`lucie_v1_standalone/retriever.py`](lucie_v1_standalone/retriever.py), [`lucie_v1_standalone/verificateur.py`](lucie_v1_standalone/verificateur.py) |

---

Mathieu Bellot, 2026-05-12.
