# Historique des sprints — vue publique

Résumé condensé des sprints livrés. Les **rapports détaillés** (causes
racines, choix de design, métriques avant/après détaillées, prompts
modifiés) restent en réserve interne et ne sont pas publiés.

Ce qui est publié ici : nom du sprint, date, métriques mesurables,
fichiers touchés au niveau dossier.

---

## Sprint 6 P2a — Retriever débridé + Vérificateur normalisé

- **Date livraison** : 2026-05-12
- **Commits** : `8dbfd95`, `a1c36c4`, `428eb94`, merge `315719b`
- **Périmètre** : retriever (stop-list relâchée) + vérificateur (normalisation citations dédupliquées)
- **Mesure** : fiabilité batterie 16q multi-angles = **62,5 %** ([bench/results/2026-05-12_battery_16q_post_p2a.md](../../bench/results/2026-05-12_battery_16q_post_p2a.md))
- **Feature flags** : `BEAUME_RETRIEVER_DEBRIDE`, `BEAUME_VERIFICATEUR_NORMALISE`
- **Calibration seuil** : `verifier_score_min` 0.85 → 0.70 — justification dans [bench/CHANGELOG.md](../../bench/CHANGELOG.md)

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

Si vous êtes investisseur, mentor, ou avocat partenaire et que vous
voulez voir les détails sous NDA : mathieu.ballotma@gmail.com.
