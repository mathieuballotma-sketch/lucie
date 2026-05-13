# Threat model — Beaume

*[Lire en français](THREAT_MODEL.fr.md)*

Public document. Describes what threatens Beaume's users and what
the architecture protects against.

---

## Usage model

Beaume runs on a lawyer's Mac. The lawyer types a French
employment-law question or pastes an excerpt from a client file.
Beaume returns an answer with verified Légifrance citations.

**Confidentiality scope**: anything that enters Beaume stays on the
lawyer's machine. No client data leaves it.

---

## Attack surfaces considered

### Surface 1 — Network exfiltration

**Threat**: an attacker or a design flaw causes client data to
leave the machine.

**Mitigations**:
- No outbound HTTP at runtime apart from `127.0.0.1:11434` (local
  Ollama). Verifiable: `grep -rE "https?://" lucie_v1_standalone/ --include='*.py' | grep -v localhost | grep -v 127.0.0.1`.
- LLM model (Gemma 4 e4b) downloaded once via Ollama then executed
  100% locally. No API key, no LLM user account.
- Légifrance KB generated locally from public DILA archives.

### Surface 2 — Reading user files

**Threat**: Beaume reads a user file it should not.

**Mitigations**:
- The client-file reading module (Sprint 7, in progress) only reads
  files explicitly drag-and-dropped into the HUD.
- No automatic scan of Finder or of the Documents/ folders.
- Native macOS sandbox applied via the Developer ID signature
  planned for the `.dmg` build.

### Surface 3 — Audit trail

**Threat**: a lawyer cannot prove after the fact what Beaume told
them (and with which sources).

**Mitigations**:
- Every answer explicitly exposes the Légifrance citations used +
  the `verifier_score`.
- Conversations are stored locally in
  `~/Library/Application Support/Beaume/` and can be exported as
  PAF (Preuve Audit Format).
- Cf. "Export PAF audit" button in the menubar HUD.

### Surface 4 — Adaptive memory

**Threat**: user memory accumulates sensitive client data and
re-discloses it.

**Mitigations**:
- The PII sanitizer applies detection rules (SSN-equivalent, IBAN,
  proper nouns) before memory write — see
  [`lucie_v1_standalone/memory/sanitizer.py`](../lucie_v1_standalone/memory/sanitizer.py).
- The "What Beaume knows about you" page in the HUD explicitly
  exposes the entire memory and allows a full reset in one click.

---

## Threat model on the code side

### The code is public, this is intentional

Beaume is under the Business Source License 1.1. The code can be
read and studied. Commercial copying in production is not
authorized for 4 years.

What is **not** in the public repo:
- The compacted Légifrance index (4.6 GB SQLite) — generated
  locally from public DILA archives.
- Fine-tuning prompts and detailed thresholds calibrated
  empirically — internal reserve.
- Full diagnostic reports (root causes, internal metrics) — see
  [`docs/sprints/SUMMARY.md`](sprints/SUMMARY.md) for the doctrine.

### If you find a vulnerability

**Do not open a public issue.** Contact directly by email:

> mathieu.bellot via mathieu.ballotma@gmail.com (subject:
> `[SECURITY] Beaume — your short title`)

Reply within 48 business hours. If the vulnerability concerns real
client data, attach the usage context (model, version) but
**no extract from a real client file** — since Beaume is local, you
already have the reproduction yourself.
