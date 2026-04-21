# Bench Lucie v1 — profilage pipeline

## Résumé par requête

| # | Label | Durée (ms) | Aperçu |
|---:|---|---:|---|
| 1 | N1 salutation | 0 | Je me spécialise en droit du licenciement économique. Avez-vous une question sur |
| 2 | N1 définition | 81090 | Aucune source disponible sur ce point.  --- _Note générée par Lucie V1 — Score d |
| 3 | N2 factuelle ref | 24250 | Aucune source disponible sur ce point.  Les sources fournies ne contiennent aucu |
| 4 | N2 thématique | 90345 | **Erreur pipeline** : Ollama timeout après 90.0s (modèle: gemma4:e4b) |
| 5 | N2 hors-scope | 9 | Je ne suis pas connecté à la météo — je me concentre sur le droit du licenciemen |

**p50** : 24250 ms · **moy** : 39139 ms · **max** : 90345 ms · **n** : 5

## Agrégation par étape (somme sur toutes requêtes)

| Étape | n calls | Total (ms) | Moy/call (ms) | % total |
|---|---:|---:|---:|---:|
| level.search | 3 | 195581 | 65194 | 39.5% |
| llm.redacteur.search | 3 | 195531 | 65177 | 39.4% |
| ollama.gemma4:e4b | 2 | 104619 | 52309 | 21.1% |
| retriever.search | 3 | 26 | 9 | 0.0% |
| verificateur.search | 2 | 8 | 4 | 0.0% |
| router.validate | 3 | 3 | 1 | 0.0% |
| router.route | 3 | 0 | 0 | 0.0% |

## Détail par requête

### 1. N1 salutation — 0 ms
> (aucune étape mesurée)

### 2. N1 définition — 81090 ms
| Étape | ms | meta |
|---|---:|---|
| router.validate | 0 |  |
| router.route | 0 |  |
| retriever.search | 4 |  |
| ollama.gemma4:e4b | 80498 | prompt_eval_ms=62516, eval_ms=16878, prompt_tokens=1179, out_tokens=382 |
| llm.redacteur.search | 81061 |  |
| verificateur.search | 8 |  |
| level.search | 81078 |  |

### 3. N2 factuelle ref — 24250 ms
| Étape | ms | meta |
|---|---:|---|
| router.validate | 3 |  |
| router.route | 0 |  |
| retriever.search | 21 |  |
| ollama.gemma4:e4b | 24120 | prompt_eval_ms=2872, eval_ms=20151, prompt_tokens=1194, out_tokens=453 |
| llm.redacteur.search | 24222 |  |
| verificateur.search | 0 |  |
| level.search | 24243 |  |

### 4. N2 thématique — 90345 ms
| Étape | ms | meta |
|---|---:|---|
| router.validate | 0 |  |
| router.route | 0 |  |
| retriever.search | 1 |  |
| llm.redacteur.search | 90248 |  |
| level.search | 90260 |  |

### 5. N2 hors-scope — 9 ms
> (aucune étape mesurée)
