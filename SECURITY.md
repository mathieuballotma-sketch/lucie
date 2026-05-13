# Security

*[Lire en français](SECURITY.fr.md)*

## Threat model in three lines

Beaume runs on a lawyer's Mac. Client-file data never leaves it —
no outbound HTTP at runtime apart from `127.0.0.1:11434` (local
Ollama). The detailed list of attack surfaces considered is in
[`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## Reporting a vulnerability

**Do not open a public issue.** Contact directly:

> Mathieu Bellot — mathieu.ballotma@gmail.com
> Subject: `[SECURITY] Beaume — <short title>`

Reply within 48 business hours. If the vulnerability involves real
client data, attach the usage context (model, version) but
**no extract of a real client file** — since Beaume is local, you
already have the reproduction on your own machine.

## Responsible disclosure scope

| Category | Action |
|----------|--------|
| Critical (data exfiltration) | disclosure after fix, credit in `CHANGELOG.md` |
| High (privilege escalation, file read outside sandbox) | same, within 30 days |
| Moderate (local DoS) | within 90 days |
| Low (non-sensitive info disclosure) | fix in next sprint, mention in `CHANGELOG.md` |

## What is not a vulnerability

- An LLM hallucination that slipped past the Verifier: this is a
  reliability bug, not a security vulnerability. Open a normal
  GitHub issue with the triggering prompt.
- A client-file document Beaume read after the user dragged-and-
  dropped it themselves: that's the expected behavior.
- Public code being read and studied: this is intentional (BSL 1.1).
  Commercial copying is not authorized for 4 years — that's a legal
  matter, not a security one.

## Supported versions

| Version | Security support |
|---------|------------------|
| `main` (HEAD) | yes |
| Tagged releases (forthcoming, post-pilot) | yes for the latest minor |
| Pre-Sprint 6 (before 2026-04-23) | no, pre-pivot |

## References

- [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) — detailed threat
  model per attack surface
- [`LICENSE`](LICENSE) — Business Source License 1.1
- [`PRINCIPLES.md`](PRINCIPLES.md) — principle 1 (100% on-device) and
  principle 4 (radical transparency)
