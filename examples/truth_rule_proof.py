"""
truth_rule_proof.py — Lucie deterministic refusal pattern demo.

Shows how Lucie's core validation layer operates WITHOUT any LLM call:
- Citation matching is pure regex + exact string comparison
- Scope enforcement is keyword-based, <1ms
- All verdicts are reproducible and testable offline

No Légifrance fixtures, no external dependencies beyond the standard library.
Run: python truth_rule_proof.py
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    VALIDE = "VALIDÉ"              # All citations matched known sources
    CORRIGE = "CORRIGÉ"            # Partial match — fixable by removing invalid refs
    INSUFFISANT = "INSUFFISANT"    # Too few citations found valid
    NON_VERIFIABLE = "NON VÉRIFIABLE"  # No citation markers found at all


@dataclass
class VerificationResult:
    verdict: Verdict
    score: float          # 0.0–1.0 fraction of valid citations
    valid: list[str]
    invalid: list[str]
    note: str


def verify_citations(note: str, sources: list[str]) -> VerificationResult:
    """
    Deterministic citation verifier.

    Extracts [CIT_ID] patterns from the note and checks each against the
    provided source list. Pure regex + string comparison — zero LLM calls.
    Runs in <50ms regardless of note length.
    """
    found = re.findall(r'\[([A-Za-z0-9_\-]+)\]', note)
    if not found:
        return VerificationResult(
            verdict=Verdict.NON_VERIFIABLE,
            score=0.0,
            valid=[],
            invalid=[],
            note="No citation markers [REF] found in note.",
        )

    source_set = {s.upper() for s in sources}
    valid = [c for c in found if c.upper() in source_set]
    invalid = [c for c in found if c.upper() not in source_set]
    score = len(valid) / len(found)

    if score == 1.0:
        verdict = Verdict.VALIDE
    elif score >= 0.5:
        verdict = Verdict.CORRIGE
    else:
        verdict = Verdict.INSUFFISANT

    return VerificationResult(
        verdict=verdict,
        score=score,
        valid=valid,
        invalid=invalid,
        note=f"{len(valid)}/{len(found)} citations valid.",
    )


# ---------------------------------------------------------------------------
# Scope enforcement — no LLM, no ML model
# In production, SCOPE_KEYWORDS is loaded from private configuration.
# This demo uses a small illustrative subset.
# ---------------------------------------------------------------------------

SCOPE_KEYWORDS_DEMO = frozenset({
    "licenciement",
    "rupture conventionnelle",
    "préavis",
    "indemnité",
    "contrat de travail",
    "clause de non-concurrence",
})


def is_in_scope(query: str) -> bool:
    """
    Returns True if the query falls within the supported legal domain.
    Deterministic keyword match, executes in <1ms.
    """
    q = query.lower()
    return any(kw in q for kw in SCOPE_KEYWORDS_DEMO)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Lucie — Deterministic Refusal Pattern Demo ===\n")

    # Case 1: All citations valid → VALIDÉ
    note1 = "Selon [L1233-1] et [L1233-3], la procédure de licenciement économique exige..."
    sources1 = ["L1233-1", "L1233-3", "L1233-4"]
    r1 = verify_citations(note1, sources1)
    print(f"[Case 1] {r1.verdict.value} (score={r1.score:.2f}) | {r1.note}")
    assert r1.verdict == Verdict.VALIDE, f"Expected VALIDÉ, got {r1.verdict}"

    # Case 2: One invalid citation → CORRIGÉ
    note2 = "D'après [L1233-1] et [LEGIARTI_INEXISTANT], le délai de préavis est de..."
    r2 = verify_citations(note2, sources1)
    print(f"[Case 2] {r2.verdict.value} (score={r2.score:.2f}) | invalid refs: {r2.invalid}")
    assert r2.verdict == Verdict.CORRIGE, f"Expected CORRIGÉ, got {r2.verdict}"

    # Case 3: Mostly invalid → INSUFFISANT
    note3 = "Selon [FAUX_1], [FAUX_2] et [L1233-1], la jurisprudence indique que..."
    r3 = verify_citations(note3, sources1)
    print(f"[Case 3] {r3.verdict.value} (score={r3.score:.2f}) | {r3.note}")
    assert r3.verdict == Verdict.INSUFFISANT, f"Expected INSUFFISANT, got {r3.verdict}"

    # Case 4: No citation markers at all → NON VÉRIFIABLE
    note4 = "Le licenciement économique est encadré par le Code du travail français."
    r4 = verify_citations(note4, sources1)
    print(f"[Case 4] {r4.verdict.value} | {r4.note}")
    assert r4.verdict == Verdict.NON_VERIFIABLE, f"Expected NON VÉRIFIABLE, got {r4.verdict}"

    print()

    # Case 5: Scope enforcement (deterministic, <1ms)
    q_in = "Quelle est la procédure pour un licenciement économique collectif ?"
    q_out = "Rédigez-moi un email de marketing pour un SaaS B2B."
    q_partial = "Mon contrat de travail mentionne une clause de non-concurrence, est-ce légal ?"

    print(f"[Case 5a] in_scope: {is_in_scope(q_in)!s:5}  | \"{q_in[:60]}\"")
    print(f"[Case 5b] in_scope: {is_in_scope(q_out)!s:5}  | \"{q_out[:60]}\"")
    print(f"[Case 5c] in_scope: {is_in_scope(q_partial)!s:5}  | \"{q_partial[:60]}...\"")

    assert is_in_scope(q_in) is True
    assert is_in_scope(q_out) is False
    assert is_in_scope(q_partial) is True

    print()
    print("✓ All 7 assertions passed.")
    print("  Deterministic refusal pattern verified — zero LLM calls, zero external dependencies.")
