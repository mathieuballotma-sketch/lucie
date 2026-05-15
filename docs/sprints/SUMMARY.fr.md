# Historique des sprints — vue publique

*[Read in English](SUMMARY.md)*

Résumé condensé des sprints livrés. Les **rapports détaillés** (causes
racines, choix de design, métriques avant/après détaillées, prompts
modifiés) restent en réserve interne et ne sont pas publiés.

Ce qui est publié ici : nom du sprint, date, métriques mesurables,
fichiers touchés au niveau dossier.

---

## Sprint 6 P2c — Fidélité contexte LLM (PARTIAL)

- **Date livraison** : 2026-05-12
- **Commits** : `6be38b1`, `2f1166d`
- **Périmètre** : rédacteur (chargement conditionnel d'un prompt système override depuis dossier privé gitignored) + transport Ollama (pinning `temperature=0` + `seed` au niveau du transport pour tous les agents)
- **Mesure batterie 50q** : **33/50** PASS (vs 34/50 baseline post-P2b, soit −1)
- **Sous-score cœur lic_eco** :
  - PASS officiel : **1/10** (vs 2/10 baseline) — critère cible ≥6/10 **non atteint**
  - Hallucination du refus : **0/10** (vs 8/10 baseline) — cause racine résolue
  - 9/10 questions cœur dépassent uniquement le seuil `wall_clock_ms_max=60 000 ms` ; sur le contenu, `verifier_score ≥ 0,7`, longueur ≥ 200 chars, articles `[L1233-x]` cités. Médiane 70 s.
- **A/B causal seed on vs off** (lic_eco) : sans seed médiane 58 s mais 2/10 hallucinations réapparaissent ; avec seed médiane 70 s et 0/10 hallucination. Le déterminisme améliore la fidélité, dégrade la perf d'environ 10 s sur la médiane.
- **Feature flags** : `BEAUME_REDACTEUR_STRICT_CONTEXT`, `BEAUME_LLM_DETERMINISTIC` (défaut "1" pour les deux)
- **Verdict** : PARTIAL. La fidélité au contexte est techniquement restaurée. Le critère `wall_clock_ms_max=60 000 ms` est trop strict pour `gemma4:e4b` chain-of-thought en mode déterministe. Suite Sprint 6 P2d : calibrer le seuil de mesure à 90 000 ms (cible avocat) ou benchmarker un modèle plus rapide.

## Sprint 6 P2a — Retriever débridé + Vérificateur normalisé

- **Date livraison** : 2026-05-12
- **Commits** : `8dbfd95`, `a1c36c4`, `428eb94`, merge `315719b`
- **Périmètre** : retriever (stop-list relâchée) + vérificateur (normalisation citations dédupliquées)
- **Mesure** : fiabilité batterie 16q multi-angles = **62,5 %** ([bench/results/2026-05-12_battery_16q_post_p2a.md](../../bench/results/2026-05-12_battery_16q_post_p2a.md))
- **Feature flags** : `BEAUME_RETRIEVER_DEBRIDE`, `BEAUME_VERIFICATEUR_NORMALISE`
- **Calibration seuil** : `verifier_score_min` 0.85 → 0.70 — justification dans [bench/CHANGELOG.fr.md](../../bench/CHANGELOG.fr.md)

## Sprint 6 P1b — Refus contextuel `lic_perso`

- **Date livraison** : 2026-05-08
- **Périmètre** : extension du routeur ambigu pour congés/RTT/démission/RC
- **Effet** : moins de routages erronés vers le branche `lic_eco` quand la question relève de licenciement personnel

## Sprint 6 P1 — Cerveau intelligent + raisons + refus contextuel

- **Date livraison** : 2026-05-08
- **Périmètre** : intent classifier assoupli, sous-catégorie `lic_perso`, branche pipeline avec verdict structuré

## Sprint 3 — Fusion Swiss Watch

- **Date livraison** : 2026-05-08
- **Périmètre** : module `beaume/` (entrée publique), page mémoire utilisateur, batterie 50q, badge `verifier_score` dans le HUD
- **Volume** : +3 793 lignes nettes

## Sprint 1 / 1bis / 1ter — Rebrand & nettoyage

- **Dates** : 2026-05-08
- **Périmètre** : rebrand Lucie → Beaume (env vars `LUCIE_*` → `BEAUME_*` avec fallback deprecation, launchd, paths filesystem, README, CHANGELOG), DB cleanup −6,7 Go

---

## Pourquoi pas plus de détail ici

La transparence radicale de Beaume couvre **ce qui est livré et ce
qui est mesuré**, pas **comment les bugs ont été trouvés et comment
les ai-je résolus en interne**. Les rapports diagnostic profonds
révèleraient :

- Les patterns d'erreur du LLM Gemma sur des questions spécifiques.
- Les seuils tunés empiriquement après N runs.
- Les choix d'implémentation rejetés et pourquoi.
- Les prompts modifiés ligne par ligne.

Tout cela représente le travail de R&D solo des 5 derniers mois et
reste en réserve compétitive. Le repo public donne l'**effet**
(métriques reproductibles), pas la **recette**.

Si vous êtes un collaborateur sérieux ou avocat partenaire et que vous
voulez voir les détails sous NDA : mathieu.ballotma@gmail.com.
