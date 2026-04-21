# Bench Lucie v1 — profilage pipeline

## Résumé par requête

| # | Label | Durée (ms) | Aperçu |
|---:|---|---:|---|
| 1 | N1 salutation | 0 | Je me spécialise en droit du licenciement économique. Avez-vous une question sur |
| 2 | N1 définition | 90304 | **Erreur pipeline** : Ollama timeout après 90.0s (modèle: gemma4:e4b) |
| 3 | N2 factuelle ref | 49812 | Aucune source disponible sur ce point.  --- _Note générée par Lucie V1 — Score d |
| 4 | N2 thématique | 90169 | **Erreur pipeline** : Ollama timeout après 90.0s (modèle: gemma4:e4b) |
| 5 | N2 hors-scope | 2 | Je ne suis pas connecté à la météo — je me concentre sur le droit du licenciemen |

**p50** : 49812 ms · **moy** : 46057 ms · **max** : 90304 ms · **n** : 5

## Agrégation par étape (somme sur toutes requêtes)

| Étape | n calls | Total (ms) | Moy/call (ms) | % total |
|---|---:|---:|---:|---:|
| level.search | 3 | 230206 | 76735 | 45.2% |
| llm.redacteur.search | 3 | 230180 | 76727 | 45.2% |
| ollama.gemma4:e4b | 1 | 49246 | 49246 | 9.7% |
| retriever.search | 3 | 19 | 6 | 0.0% |
| verificateur.search | 1 | 1 | 1 | 0.0% |
| router.validate | 3 | 0 | 0 | 0.0% |
| router.route | 3 | 0 | 0 | 0.0% |

## Détail par requête

### 1. N1 salutation — 0 ms
> (aucune étape mesurée)

### 2. N1 définition — 90304 ms
| Étape | ms | meta |
|---|---:|---|
| router.validate | 0 |  |
| router.route | 0 |  |
| retriever.search | 4 |  |
| llm.redacteur.search | 90274 |  |
| level.search | 90282 |  |

### 3. N2 factuelle ref — 49812 ms
| Étape | ms | meta |
|---|---:|---|
| router.validate | 0 |  |
| router.route | 0 |  |
| retriever.search | 11 |  |
| ollama.gemma4:e4b | 49246 | prompt_eval_ms=8122, eval_ms=38783, prompt_tokens=1194, out_tokens=315 |
| llm.redacteur.search | 49766 |  |
| verificateur.search | 1 |  |
| level.search | 49778 |  |

### 4. N2 thématique — 90169 ms
| Étape | ms | meta |
|---|---:|---|
| router.validate | 0 |  |
| router.route | 0 |  |
| retriever.search | 5 |  |
| llm.redacteur.search | 90141 |  |
| level.search | 90147 |  |

### 5. N2 hors-scope — 2 ms
> (aucune étape mesurée)
