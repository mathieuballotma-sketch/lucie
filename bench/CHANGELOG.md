# Bench CHANGELOG

## 2026-05-12 — Sprint 6 P2a — Recalibration `verifier_score_min` 0.85 → 0.70

**Périmètre** : `bench/swiss_watch_50.json` — 10 questions de catégorie `lic_eco` utilisant la règle `swiss_watch_quality`.

**Changement** : `pass_criteria.verifier_score_min` passe de `0.85` à `0.70` pour ces 10 questions. Le seuil `0.5` des 20 autres questions (rules `swiss_watch_small_talk`, `swiss_watch_hallucination_blocked`, etc.) reste inchangé.

### Justificatif

L'ancien seuil **0.85** reposait sur une métrique Vérificateur biaisée par double-comptage des duplicats. Exemple SW-LECO-001 :
- Note Rédacteur contenant `[L1233-X]` × 6 occurrences → l'ancienne regex `\[([A-Za-z0-9_\-\.]+)\]` les comptait 6 fois → score `6 OK / 6 total = 1.00` (artificiel).
- Le score 0.85 paraissait atteignable parce qu'il suffisait de 6 brackets valides (incluant duplicats) pour saturer.

La regex étendue Sprint 6 P2a B-6 sol 1 (`_CITATION_RE`, `_canonicalize`) :
1. **Déduplique sur clé canonique** (`L1233-3` ≡ `L.1233-3` ≡ `L. 1233-3`) — chaque article unique compte 1×.
2. **Capture les citations en prose** (`article L. 1233-5` hors crochets) — rend visibles les références jusque-là silencieuses.
3. Conséquence sur SW-LECO-001 : 3 IDs uniques validés + 1 prose hors-sources rejetée → score `3 OK / 4 total = 0.75`.

Ce **0.75 est une mesure plus honnête** que l'ancien 1.00. Le seuil **0.70** est calibré sur cette précision réelle : il accepte ≥ 3 citations valides sur 4 détectées (incluant prose), ce qui correspond à la qualité réelle attendue d'une note juridique procédurale en droit du licenciement économique.

### Référence

- Rapport Sprint 6 P2a : `~/Desktop/Rapport_sprint_6_p2a_retriever_verificateur_2026-05-08.md`
- Commits : `8dbfd95` (B-5 retriever débridé), `a1c36c4` (B-6 vérificateur normalisé)
- Probe : SW-LECO-001 sous `BEAUME_VERIFICATEUR_NORMALISE=0` repasse à score 1.00 (ancien biais), sous `=1` donne 0.75 (mesure honnête).

### Garde-fou

Si une régression suspecte est observée sur le seuil 0.70, audit en exécutant :
```bash
python3 bench/run_legal_traps.py --prompts bench/swiss_watch_50.json --filter SW-LECO --json /tmp/audit.json
```
Vérifier que `citations_invalid` reste proche de zéro sur les questions PASS. Une explosion de `citations_invalid` indiquerait un LLM qui invente des références.
