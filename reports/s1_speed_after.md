# Bench Lucie v1 — profilage pipeline

## Résumé par requête

| # | Label | Durée (ms) | TTFT wall (ms) | TTFT pipeline (ms) | TTFT ollama (ms) | Aperçu |
|---:|---|---:|---:|---:|---:|---|
| 1 | N1 salutation | 76 | — | — | — | Je me spécialise en droit du licenciement économique. Avez-vous une question sur |
| 2 | N1 définition | 74915 | 70888 | 70888 | 70880 | Aucune source disponible sur ce point.  Les sources fournies traitent uniquement |
| 3 | N2 factuelle ref | 26493 | 24513 | 24513 | 24461 | Aucune source disponible sur ce point.  Les sources fournies ne contiennent aucu |
| 4 | N2 thématique | 46163 | 26926 | 26926 | 26878 | ## Réponse Un licenciement pour motif économique doit impérativement être justif |
| 5 | N2 hors-scope | 0 | — | — | — | Je ne suis pas connecté à la météo — je me concentre sur le droit du licenciemen |

**p50** : 26493 ms · **moy** : 29529 ms · **max** : 74915 ms · **n** : 5
**TTFT wall** (n=3) — médiane 26926 ms · min 24513 ms · max 70888 ms
**TTFT pipeline** (n=3) — médiane 26926 ms · min 24513 ms · max 70888 ms
**TTFT ollama** (n=3) — médiane 26878 ms · min 24461 ms · max 70880 ms

## Agrégation par étape (somme sur toutes requêtes)

| Étape | n calls | Total (ms) | Moy/call (ms) | % total |
|---|---:|---:|---:|---:|
| ollama.gemma4:e4b | 3 | 147373 | 49124 | 37.6% |
| pipeline.ttft | 3 | 122328 | 40776 | 31.2% |
| ollama.gemma4:e4b.ttft | 3 | 122219 | 40740 | 31.2% |

## Détail par requête

### 1. N1 salutation — 76 ms
> (aucune étape mesurée)

### 2. N1 définition — 74915 ms
| Étape | ms | meta |
|---|---:|---|
| ollama.gemma4:e4b.ttft | 70880 |  |
| pipeline.ttft | 70888 |  |
| ollama.gemma4:e4b | 74882 | prompt_eval_ms=5161, eval_ms=20540, prompt_tokens=1179, out_tokens=489 |

### 3. N2 factuelle ref — 26493 ms
| Étape | ms | meta |
|---|---:|---|
| ollama.gemma4:e4b.ttft | 24461 |  |
| pipeline.ttft | 24513 |  |
| ollama.gemma4:e4b | 26409 | prompt_eval_ms=2931, eval_ms=23136, prompt_tokens=1194, out_tokens=430 |

### 4. N2 thématique — 46163 ms
| Étape | ms | meta |
|---|---:|---|
| ollama.gemma4:e4b.ttft | 26878 |  |
| pipeline.ttft | 26926 |  |
| ollama.gemma4:e4b | 46082 | prompt_eval_ms=3359, eval_ms=42329, prompt_tokens=1172, out_tokens=727 |

### 5. N2 hors-scope — 0 ms
> (aucune étape mesurée)
