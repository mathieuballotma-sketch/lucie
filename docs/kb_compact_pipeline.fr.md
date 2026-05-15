# Pipeline KB compact — Sprint K-1

**Statut** : Sprint K-1 (signatures binaires + graphe de renvois + PageRank)
**Date** : 2026-05-15
**Branche** : `feat/sprint-k1-binary-signatures-graph-pagerank-2026-05-15`

## Objectif

Remplacer la base `legi.sqlite` de 4,4 Go embarquée actuellement dans Beaume
par un ensemble d'artefacts compacts générés côté serveur Beaume Team. K-1
est la **preuve mathématique du pipeline** : la chaîne doit atteindre
`recall@10 ≥ 90 %` sur le bench Swiss Watch (50 questions), en n'utilisant
que les signatures binaires produites.

Si la cible recall est atteinte → K-2 migrera le retriever client pour
consommer les artefacts. Si elle ne l'est pas → le rapport propose trois
pistes de remédiation (Matryoshka 2048 bits, hybride BM25, re-rank PageRank)
sans masquer la vérité (règle truth-rule Beaume).

## Artefacts produits

| Fichier | Rôle | Taille approx. (672 k articles VIGUEUR) |
|---|---|---|
| `sigs_mrl.bin` | Signatures Matryoshka binaires (64 + 1024 bits par article) | ~91 Mo |
| `sigs_mrl.index.cbor` | Mapping `article_id ↔ row_index` | ~30-50 Mo |
| `graph.cbor.zst` | DAG des renvois inter-articles, compressé Zstd | ~10-25 Mo |
| `pagerank.f32` | Score PageRank par article (float32, aligné row_index) | ~2,7 Mo |
| `manifest.json` | Versions, modèle, seed, SHA-256 de chaque fichier | <1 Ko (committé) |
| `build_report.json` | Stats par passe, renvois non résolus, perf | <100 Ko (committé) |
| `recall_at_10_report.json` | Résultat du bench + pistes de remédiation si échec | ~50 Ko (committé) |

## Format binaire — `sigs_mrl.bin`

Little-endian, 124 octets de header suivis d'un body plat de `N × 136`
octets (une signature courte 8 octets + une signature longue 128 octets par
article, dans l'ordre des row_index) :

```
[magic       :  8 bytes] = b"BEAUMEK1"
[version     :  1 byte ] = 0x01
[reserved    :  3 bytes] = 0x00
[short_bits  :  2 bytes uint16] = 64
[long_bits   :  2 bytes uint16] = 1024
[n_articles  :  4 bytes uint32]
[model_name  : 64 bytes utf-8 padded NUL]
[seed        :  8 bytes uint64]
[corpus_sha  : 32 bytes]      # SHA-256(legi.sqlite)
[body        : N × 136 bytes]
```

La signature est obtenue en faisant passer le texte de l'article dans BGE-M3
(`BAAI/bge-m3`) puis en quantizant par dimension :

```
sig[i] = 1 si embedding[i] > 0 sinon 0
```

La signature **courte** Matryoshka prend les 64 premières dimensions
(pré-filtre Hamming rapide) ; la **longue** prend les 1024 dimensions
complètes (re-score sémantique).

## Format binaire — `pagerank.f32`

```
[magic       :  8 bytes] = b"BEAUMEK1"
[version     :  1 byte ] = 0x01
[reserved    :  3 bytes] = 0x00
[n_articles  :  4 bytes uint32]
[damping     :  4 bytes float32] = 0,85
[n_iter_used :  4 bytes uint32]
[corpus_sha  : 32 bytes]
[scores      : N × 4 bytes float32]   # aligné row_index avec sigs_mrl.bin
```

## Format graphe — `graph.cbor.zst`

Payload CBOR (Concise Binary Object Representation) compressé Zstd :

```python
{
    "version": 1,
    "magic": "BEAUMEK1G",
    "corpus_sha": "<hex SHA-256>",
    "n_vertices": <int>,
    "n_edges": <int>,
    "edges": [[u32_src, u32_dst], ...],   # row indices
    "unresolved_count": <int>,             # renvois non résolvables
}
```

Arêtes orientées : `(u, v)` signifie « article `u` cite l'article `v` ». Les
boucles auto sont ignorées.

## Reproduire les artefacts

Pré-requis :

- Python ≥ 3.11 (utiliser `venv311/`)
- `legi.sqlite` présent dans `~/Library/Application Support/Beaume/legifrance/`
- `pip install cbor2 hnswlib zstandard` (déjà dans `requirements.txt`)
- Modèle BGE-M3 en cache HuggingFace (~2,2 Go), ou passer `--auto-download`

Build complet :

```bash
venv311/bin/python scripts/build_kb_artifacts.py \
    --output kb_artifacts/ \
    --auto-download \
    --batch-size 32 \
    --seed 42
```

Smoke test sur 5 000 articles (quelques minutes) :

```bash
venv311/bin/python scripts/build_kb_artifacts.py \
    --output kb_artifacts_smoke/ \
    --limit 5000 \
    --model sentence-transformers/all-MiniLM-L6-v2 \
    --auto-download
```

Bench recall@10 :

```bash
venv311/bin/python scripts/bench_recall_at_10.py \
    --artifacts kb_artifacts/ \
    --bench bench/swiss_watch_50.json \
    --output kb_artifacts/recall_at_10_report.json
```

Tests unitaires :

```bash
venv311/bin/python -m pytest tests/test_kb_compact/ -v
```

## Déterminisme

Toute source d'aléatoire est seedée (`numpy`, `torch`, `torch.mps`) avec la
même seed que celle inscrite dans le header binaire (`seed = 42` par
défaut). Re-générer sur le même `legi.sqlite` produit des signatures
identiques bit à bit.

## Invariants

1. Le pipeline n'écrit jamais dans `legi.sqlite` (ouvert en `mode=ro`).
2. Aucun appel réseau hors du téléchargement de modèle explicite via
   `--auto-download`.
3. Le retriever client (`lucie_v1_standalone/retriever.py`) n'est **pas**
   modifié par K-1 — K-2 fera le câblage.
4. Truth rule : si `recall@10 < 0,90`, le rapport le dit explicitement et
   propose trois suites concrètes.

## Versioning

`manifest.json` est la source canonique de vérité sur quel build a produit
quels artefacts. L'octet `version` dans chaque header `.bin`/`.cbor` permet à
K-2 de refuser des artefacts incompatibles au chargement.
