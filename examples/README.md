# Examples

Runnable demonstrations of patterns used in Lucie, simplified for public
consumption.

## Available examples

- [`truth_rule_proof.py`](trh_rule_proof.py) — the deterministic refusal
  pattern in under 100 lines of Python. Seven assertions pass, zero
  external dependencies. Demonstrates that a legal reference that is
  not in the local index is refused in under 1 ms, with zero LLM call.

## How to run

From the repository root:

```bash
python examples/truth_rule_proof.py
# or
make demo
```

Requires Python 3.11 or later. No pip install needed.

## What these examples do NOT show

These examples illustrate the **pattern**, not the production
implementation. The real Verificateur:

- Operates on 281 DILA Légifrance archives indexed locally
- Uses several additional heuristics kept in private modules
- Is integrated with the composition orchestrator and memory layer
- Is covered by 375 tests in the private test suite

For access to the full implementation under NDA, contact the author.
