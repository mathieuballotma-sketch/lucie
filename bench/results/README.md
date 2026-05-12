# bench/results — résultats batterie historiques

Archive des résultats de batterie au format Markdown lisible. Le JSON
brut détaillé (avec stack traces, prompts complets, payloads LLM) reste
en réserve interne ([`docs/sprints/SUMMARY.md`](../../docs/sprints/SUMMARY.md)
explique la doctrine).

## Fichiers publiés

- [2026-05-12_battery_16q_post_p2a.md](2026-05-12_battery_16q_post_p2a.md) — batterie 16q multi-angles, fiabilité **62,5 %**
- [2026-05-12_battery_50q_post_p2a.md](2026-05-12_battery_50q_post_p2a.md) — batterie 50q cœur lic éco, **mesure clean en cours**

## Format

Chaque résultat est nommé `YYYY-MM-DD_battery_NNq_<context>.md` et
contient au minimum :

1. Date et contexte (commit, feature flags actifs, modèle utilisé)
2. Score global PASS/FAIL et fiabilité en %
3. Décomposition par catégorie ou par angle
4. Commande exacte de reproduction (cf [`docs/REPRODUCE.md`](../../docs/REPRODUCE.md))
5. Limites explicites de la mesure (truth rule)

## Ce qui n'est pas publié

- Les JSON bruts (`*.json` détaillés avec payloads LLM)
- Les questions privées au-delà de `bench/swiss_watch_50.json`
- Les diagnostic JSON internes (`bench/results/diagnostic_*`, ignorés par
  `.gitignore`)
