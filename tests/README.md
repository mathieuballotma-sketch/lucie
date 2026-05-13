# Beaume tests

*[Lire en français](README.fr.md)*

Unit and integration tests for the Beaume pipeline.

## Running the tests

### All tests (fast, without Ollama)

```bash
pytest tests/ -v --ignore=tests/integration --ignore=tests/llm
```

Covers: intent router, verifier, retriever, memory sanitizer,
parsers, env legacy compat. ~5 seconds on a Mac M1.

### Full suite (with Ollama)

```bash
# Prerequisites: ollama serve + ollama pull gemma2:9b
pytest tests/ -v
```

Includes the LLM tests (`tests/llm/`) and the end-to-end
integration (`tests/integration/`). ~2-3 minutes depending on
hardware.

### Single test

```bash
pytest tests/test_truth_rule_pattern.py -v
pytest tests/security/ -v
```

## Structure

| Folder | Coverage |
|--------|----------|
| `tests/agents/` | Pipeline agents and workers |
| `tests/core/` | Deterministic core: router, classification, gates |
| `tests/dialogue/` | Dialogue, contextual refusal, intent classifier |
| `tests/integration/` | End-to-end pipeline → Ollama → answer |
| `tests/llm/` | Tests that require an active Ollama LLM |
| `tests/memory/` | Adaptive memory, PII sanitizer |
| `tests/security/` | PII detection, sandbox, exfiltration |
| `tests/services/` | Internal services (cache, profiling) |
| `tests/test_legifrance/` | Knowledge base: retriever, indexer |
| `tests/ui/` | HUD, `verifier_score` badge, memory popover |
| `tests/utils/` | Utilities (env_legacy, paths, etc.) |

Root-level tests: `test_truth_rule_pattern.py`,
`test_pipeline_a_smoke.py`, `test_env_legacy_compat.py`,
`test_warmup.py`, `test_pipeline_response_score.py`.

## Convention

- File `test_<module>.py` for a given module, unless several aspects
  justify a dedicated file.
- No mocking of the Verifier or the deterministic retriever — these
  are the truth components. Mocking a Verifier would invalidate the
  truth rule (cf. [`PRINCIPLES.md`](../PRINCIPLES.md)).
- Mock only the Ollama network calls in `*_smoke.py` tests.

## Configuration

Pytest is configured via [`conftest.py`](../conftest.py) at the
root (shared fixtures) and [`pyproject.toml`](../pyproject.toml)
(`[tool.pytest.ini_options]` section if present).

If you add a test that requires an environment variable, document
it here and in the test itself.
