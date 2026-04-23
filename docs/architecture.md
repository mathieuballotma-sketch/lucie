# Lucie — Architecture detailed notes

This document expands on the high-level architecture outlined in the main
README. It remains voluntarily implementation-agnostic: concrete modules,
thresholds, prompts, and the Légifrance local index are kept in private
repositories.

## Design principle: fail fast, fail honestly

Every request is first routed through a deterministic layer that can
refuse without ever invoking an LLM. This design eliminates the largest
class of hallucinats at the architectural level, not at the prompting
level.

## Three execution paths

### 1. Deterministic pre-LLM layer

- Regex extraction of legal reference patterns (e.g. `L.XXXX-X`)
- Local index lookup against a set of known, citable references
- Out-of-scope detection via a curated keyword set
- Fuzzy matching for common typographical variants

Latency budget: **< 50 ms on a 2024 Apple Silicon Mac**.
LLM calls: **zero**.

### 2. Specialised parallel processes

When a request is valid, it is dispatched to one or several specialised
workers, each bound to a specific application context (Mail, Calendar,
Notes, Word, etc.). They communicate through an internal event bus and
carry their own subset of tools.

### 3. Composition and planning orchestrator

Invoked only when multi-step reasoning is strictly required. This is the
only layer authorised to call the local LLM. Its output is returned to
the verification layer before reaching the user.

## Memory layer

The memory layer stores associations between user interactions using an
embedding-based representation. Associations strengthen with use and
decay with disuse, persisted locally per user. No shared cloud memory.

Two Lucie instances running on two different Macs diverge by
construction after sustained interaction.

## Truth enforcement

Three points of enforcement:

1. Deterministic refusal before any LLM call.
2. Post-generation citation verification against the local Légifrance
   index.
3. A full audit trail exposed to the user (sources, confidence score,
   refusal reasons).

## What is NOT in this public repository

- The Verificateur core logic (deterministic refusal path)
- The memory layer implementation
- The Légifrance local index derived from DILA
- The system prompts
- The internal evaluation harness

Selected private modules can be reviewed under NDA.
