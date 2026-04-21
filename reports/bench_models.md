# Bench comparatif modèles « speed » Lucie v1

## Comparatif global

| Modèle | p50 pipeline (ms) | moy (ms) | tok/s moy | tokens sortie moy | score moy | erreurs |
|---|---:|---:|---:|---:|---:|---:|
| `gemma4:e4b` | 43743 | 36933 | 17.6 | 545 | 0.40 | 0/5 |
| `qwen2.5:3b` | 35063 | 29838 | 11.9 | 526 | 0.40 | 0/5 |
| `llama3.2:3b` | 31640 | 28456 | 11.9 | 504 | 0.40 | 0/5 |

**Décision** : aucun modèle n'atteint score moy ≥ 0.7 sans erreur. Garder `gemma4:e4b` et investiguer qualité.

## Détail par modèle

### `gemma4:e4b`

| Requête | ms | tok/s | out tok | prompt tok | score | aperçu |
|---|---:|---:|---:|---:|---:|---|
| N2 factuelle ref | 75809 | 25.8 | 434 | 1194 | 0.00 | Aucune source disponible sur ce point.  L'article L.1234-1 n |
| N2 thématique | 43743 | 19.8 | 785 | 1172 | 0.00 | ## Réponse Un licenciement pour motif économique doit impéra |
| N2 procédure | 65107 | 7.3 | 415 | 827 | 0.00 | Aucune source disponible sur ce point.  Les sources fournies |
| N2 synthèse | 5 | 0.0 | 0 | 0 | 1.00 | Je me spécialise en droit du licenciement économique. Avez-v |
| N2 hors-scope | 0 | 0.0 | 0 | 0 | 1.00 | Je ne suis pas connecté à la météo — je me concentre sur le  |

### `qwen2.5:3b`

| Requête | ms | tok/s | out tok | prompt tok | score | aperçu |
|---|---:|---:|---:|---:|---:|---|
| N2 factuelle ref | 37232 | 11.2 | 322 | 1194 | 0.00 | Aucune source disponible sur ce point.  --- _Note générée pa |
| N2 thématique | 76893 | 12.7 | 887 | 1172 | 0.00 | ## Réponse Un licenciement pour motif économique doit impéra |
| N2 procédure | 35063 | 11.8 | 369 | 827 | 0.00 | Aucune source disponible sur ce point.  --- _Note générée pa |
| N2 synthèse | 1 | 0.0 | 0 | 0 | 1.00 | Je me spécialise en droit du licenciement économique. Avez-v |
| N2 hors-scope | 0 | 0.0 | 0 | 0 | 1.00 | Je ne suis pas connecté à la météo — je me concentre sur le  |

### `llama3.2:3b`

| Requête | ms | tok/s | out tok | prompt tok | score | aperçu |
|---|---:|---:|---:|---:|---:|---|
| N2 factuelle ref | 40354 | 11.4 | 371 | 1194 | 0.00 | Aucune source disponible sur ce point.  Les sources fournies |
| N2 thématique | 70286 | 12.5 | 807 | 1172 | 0.00 | ## Réponse Un licenciement pour motif économique est subordo |
| N2 procédure | 31640 | 11.9 | 335 | 827 | 0.00 | Aucune source disponible sur ce point.  --- _Note générée pa |
| N2 synthèse | 2 | 0.0 | 0 | 0 | 1.00 | Je me spécialise en droit du licenciement économique. Avez-v |
| N2 hors-scope | 0 | 0.0 | 0 | 0 | 1.00 | Je ne suis pas connecté à la météo — je me concentre sur le  |
