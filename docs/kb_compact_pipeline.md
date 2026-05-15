# KB Compact Pipeline — Sprint K-1

**Status**: Sprint K-1 (binary signatures + reference graph + PageRank)
**Date**: 2026-05-15
**Branch**: `feat/sprint-k1-binary-signatures-graph-pagerank-2026-05-15`

## Purpose

Replace the 4.4 GB `legi.sqlite` knowledge base shipped with Beaume by a set of
compact, mathematically-grounded artifacts produced server-side at the Beaume
Team office. K-1 is the **proof-of-pipeline**: it must show that
`recall@10 ≥ 90 %` on the 50-question Swiss Watch bench, using only the
generated binary signatures.

If the recall target is met, K-2 will migrate the client retriever to consume
the artifacts; if it is not met, the report enumerates three remediation paths
(2048-bit Matryoshka, BM25 hybrid, PageRank re-rank) without hiding the truth.

## Artifacts

| File | Purpose | Approx. size for 672 k VIGUEUR articles |
|---|---|---|
| `sigs_mrl.bin` | Binary Matryoshka signatures (64 + 1024 bits per article) | ~91 MB |
| `sigs_mrl.index.cbor` | `article_id ↔ row_index` mapping | ~30-50 MB |
| `graph.cbor.zst` | DAG of inter-article references, Zstd-compressed | ~10-25 MB |
| `pagerank.f32` | PageRank score per article (float32, row-aligned) | ~2.7 MB |
| `manifest.json` | Versions, model name, seed, SHA-256 of each file | <1 KB (committed) |
| `build_report.json` | Per-pass stats, unresolved refs, perf | <100 KB (committed) |
| `recall_at_10_report.json` | Bench result + remediation proposals if fail | ~50 KB (committed) |

## Binary format — `sigs_mrl.bin`

Little-endian, 124-byte header followed by a flat body of `N × 136` bytes (one
8-byte short signature + one 128-byte long signature per article, in
row-index order):

```
[magic       :  8 bytes] = b"BEAUMEK1"
[version     :  1 byte ] = 0x01
[reserved    :  3 bytes] = 0x00
[short_bits  :  2 bytes uint16] = 64
[long_bits   :  2 bytes uint16] = 1024
[n_articles  :  4 bytes uint32]
[model_name  : 64 bytes utf-8 NUL-padded]
[seed        :  8 bytes uint64]
[corpus_sha  : 32 bytes]      # SHA-256(legi.sqlite)
[body        : N × 136 bytes] = [sig_short_i (8 B), sig_long_i (128 B)]_i
```

The signature itself is produced by passing each article through BGE-M3
(`BAAI/bge-m3`) and applying a per-dimension binary quantization:

```
sig[i] = 1 if embedding[i] > 0 else 0
```

The Matryoshka short signature uses the first 64 dimensions (fast Hamming
pre-filter); the long signature uses all 1024 dimensions (semantic re-score).

## Binary format — `pagerank.f32`

```
[magic       :  8 bytes] = b"BEAUMEK1"
[version     :  1 byte ] = 0x01
[reserved    :  3 bytes] = 0x00
[n_articles  :  4 bytes uint32]
[damping     :  4 bytes float32] = 0.85
[n_iter_used :  4 bytes uint32]
[corpus_sha  : 32 bytes]
[scores      : N × 4 bytes float32]   # row-aligned with sigs_mrl.bin
```

## Graph format — `graph.cbor.zst`

CBOR (Concise Binary Object Representation) payload then Zstd-compressed:

```python
{
    "version": 1,
    "magic": "BEAUMEK1G",
    "corpus_sha": "<hex SHA-256>",
    "n_vertices": <int>,
    "n_edges": <int>,
    "edges": [[u32_src, u32_dst], ...],   # row indices
    "unresolved_count": <int>,             # references with no resolvable target
}
```

Edges are oriented: an edge `(u, v)` means article `u` cites article `v`. Self
loops are dropped.

## Reproducing the artifacts

Pre-requisites:

- Python ≥ 3.11 (use `venv311/`)
- `legi.sqlite` present at `~/Library/Application Support/Beaume/legifrance/`
- `pip install cbor2 hnswlib zstandard` (already in `requirements.txt`)
- BGE-M3 model in HuggingFace cache (~2.2 GB), or pass `--auto-download`

Build:

```bash
venv311/bin/python scripts/build_kb_artifacts.py \
    --output kb_artifacts/ \
    --auto-download \
    --batch-size 32 \
    --seed 42
```

Smoke-test on a 5 000-article subset (~minutes):

```bash
venv311/bin/python scripts/build_kb_artifacts.py \
    --output kb_artifacts_smoke/ \
    --limit 5000 \
    --model sentence-transformers/all-MiniLM-L6-v2 \
    --auto-download
```

Bench:

```bash
venv311/bin/python scripts/bench_recall_at_10.py \
    --artifacts kb_artifacts/ \
    --bench bench/swiss_watch_50.json \
    --output kb_artifacts/recall_at_10_report.json
```

Unit tests:

```bash
venv311/bin/python -m pytest tests/test_kb_compact/ -v
```

## Determinism

All randomness is seeded (`numpy`, `torch`, `torch.mps`) with the same seed
that is written into the binary header (`seed = 42` by default). Re-running
the build on the same `legi.sqlite` produces byte-identical signatures.

## Invariants

1. The pipeline never writes to `legi.sqlite` (opened in `mode=ro`).
2. No network call other than the explicit `--auto-download` model fetch.
3. The client-facing retriever (`lucie_v1_standalone/retriever.py`) is **not**
   modified by K-1 — K-2 will wire the new artifacts in.
4. Truth rule: if `recall@10 < 0.90`, the report says so plainly and proposes
   three follow-up paths.

## Versioning

`manifest.json` is the canonical record of which build produced which
artifacts. The header `version` byte in each `.bin`/`.cbor` payload allows K-2
to refuse incompatible artifacts at load time.
