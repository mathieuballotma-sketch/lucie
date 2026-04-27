# Bench Lucie v1 — profilage pipeline

## Résumé par requête

| # | Label | Durée (ms) | TTFT wall (ms) | TTFT pipeline (ms) | TTFT ollama (ms) | Aperçu |
|---:|---|---:|---:|---:|---:|---|
| 1 | N1 salutation | 1 | — | — | — | Je me spécialise en droit du licenciement économique. Avez-vous une question sur |
| 2 | N1 définition | 21155 | 18167 | 18167 | 18162 | Aucune source disponible sur ce point.  Les sources fournies traitent uniquement |
| 3 | N2 factuelle ref | 15704 | 14293 | 14293 | 14225 | Aucune source disponible sur ce point.  Les sources fournies ne contiennent aucu |
| 4 | N2 thématique | 34834 | 22470 | 22470 | 22468 | ## Réponse Un licenciement pour motif économique est soumis à plusieurs conditio |
| 5 | N2 hors-scope | 0 | — | — | — | Je ne suis pas connecté à la météo — je me concentre sur le droit du licenciemen |

**p50** : 15704 ms · **moy** : 14339 ms · **max** : 34834 ms · **n** : 5
**TTFT wall** (n=3) — médiane 18167 ms · min 14293 ms · max 22470 ms
**TTFT pipeline** (n=3) — médiane 18167 ms · min 14293 ms · max 22470 ms
**TTFT ollama** (n=3) — médiane 18162 ms · min 14225 ms · max 22468 ms

## Agrégation par étape (somme sur toutes requêtes)

| Étape | n calls | Total (ms) | Moy/call (ms) | % total |
|---|---:|---:|---:|---:|
| ollama.gemma4:e4b | 3 | 71525 | 23842 | 39.4% |
| pipeline.ttft | 3 | 54930 | 18310 | 30.3% |
| ollama.gemma4:e4b.ttft | 3 | 54855 | 18285 | 30.3% |

## Détail par requête

### 1. N1 salutation — 1 ms
> (aucune étape mesurée)

### 2. N1 définition — 21155 ms
| Étape | ms | meta |
|---|---:|---|
| ollama.gemma4:e4b.ttft | 18162 |  |
| pipeline.ttft | 18167 |  |
| ollama.gemma4:e4b | 21124 | prompt_eval_ms=1994, eval_ms=18806, prompt_tokens=1179, out_tokens=525 |

### 3. N2 factuelle ref — 15704 ms
| Étape | ms | meta |
|---|---:|---|
| ollama.gemma4:e4b.ttft | 14225 |  |
| pipeline.ttft | 14293 |  |
| ollama.gemma4:e4b | 15602 | prompt_eval_ms=2073, eval_ms=13242, prompt_tokens=1194, out_tokens=373 |

### 4. N2 thématique — 34834 ms
| Étape | ms | meta |
|---|---:|---|
| ollama.gemma4:e4b.ttft | 22468 |  |
| pipeline.ttft | 22470 |  |
| ollama.gemma4:e4b | 34800 | prompt_eval_ms=2073, eval_ms=32305, prompt_tokens=1172, out_tokens=871 |

### 5. N2 hors-scope — 0 ms
> (aucune étape mesurée)
