# Bench Lucie v1 — profilage pipeline

## Résumé par requête

| # | Label | Durée (ms) | Aperçu |
|---:|---|---:|---|
| 1 | N1 salutation (p1) | 0 | Je me spécialise en droit du licenciement économique. Avez-vous une question sur |
| 2 | N1 définition (p1) | 51912 | Aucune source disponible sur ce point.  Les sources fournies traitent uniquement |
| 3 | N2 factuelle ref (p1) | 47891 | Aucune source disponible sur ce point.  Les sources fournies ne contiennent aucu |
| 4 | N2 thématique (p1) | 81378 | ## Réponse Un licenciement pour motif économique est conditionné par plusieurs o |
| 5 | N2 hors-scope (p1) | 1 | Je ne suis pas connecté à la météo — je me concentre sur le droit du licenciemen |
| 6 | N1 salutation (p2) | 0 | Je me spécialise en droit du licenciement économique. Avez-vous une question sur |
| 7 | N1 définition (p2) | 4 | Aucune source disponible sur ce point.  Les sources fournies traitent uniquement |
| 8 | N2 factuelle ref (p2) | 0 | Aucune source disponible sur ce point.  Les sources fournies ne contiennent aucu |
| 9 | N2 thématique (p2) | 1 | ## Réponse Un licenciement pour motif économique est conditionné par plusieurs o |
| 10 | N2 hors-scope (p2) | 0 | Je ne suis pas connecté à la météo — je me concentre sur le droit du licenciemen |

**p50** : 1 ms · **moy** : 18119 ms · **max** : 81378 ms · **n** : 10

## Agrégation par étape (somme sur toutes requêtes)

| Étape | n calls | Total (ms) | Moy/call (ms) | % total |
|---|---:|---:|---:|---:|
| level.search | 3 | 181162 | 60387 | 33.4% |
| llm.redacteur.search | 3 | 181139 | 60380 | 33.4% |
| ollama.gemma4:e4b | 3 | 179871 | 59957 | 33.2% |
| retriever.search | 3 | 12 | 4 | 0.0% |
| verificateur.search | 3 | 9 | 3 | 0.0% |
| router.validate | 3 | 0 | 0 | 0.0% |
| router.route | 3 | 0 | 0 | 0.0% |

## Détail par requête

### 1. N1 salutation (p1) — 0 ms
> (aucune étape mesurée)

### 2. N1 définition (p1) — 51912 ms
| Étape | ms | meta |
|---|---:|---|
| router.validate | 0 |  |
| router.route | 0 |  |
| retriever.search | 3 |  |
| ollama.gemma4:e4b | 51522 | prompt_eval_ms=63, eval_ms=49705, prompt_tokens=1179, out_tokens=434 |
| llm.redacteur.search | 51904 |  |
| verificateur.search | 1 |  |
| level.search | 51909 |  |

### 3. N2 factuelle ref (p1) — 47891 ms
| Étape | ms | meta |
|---|---:|---|
| router.validate | 0 |  |
| router.route | 0 |  |
| retriever.search | 6 |  |
| ollama.gemma4:e4b | 47664 | prompt_eval_ms=6437, eval_ms=39468, prompt_tokens=1194, out_tokens=382 |
| llm.redacteur.search | 47872 |  |
| verificateur.search | 1 |  |
| level.search | 47880 |  |

### 4. N2 thématique (p1) — 81378 ms
| Étape | ms | meta |
|---|---:|---|
| router.validate | 0 |  |
| router.route | 0 |  |
| retriever.search | 3 |  |
| ollama.gemma4:e4b | 80685 | prompt_eval_ms=5209, eval_ms=71727, prompt_tokens=1172, out_tokens=797 |
| llm.redacteur.search | 81363 |  |
| verificateur.search | 7 |  |
| level.search | 81373 |  |

### 5. N2 hors-scope (p1) — 1 ms
> (aucune étape mesurée)

### 6. N1 salutation (p2) — 0 ms
> (aucune étape mesurée)

### 7. N1 définition (p2) — 4 ms
> (aucune étape mesurée)

### 8. N2 factuelle ref (p2) — 0 ms
> (aucune étape mesurée)

### 9. N2 thématique (p2) — 1 ms
> (aucune étape mesurée)

### 10. N2 hors-scope (p2) — 0 ms
> (aucune étape mesurée)
