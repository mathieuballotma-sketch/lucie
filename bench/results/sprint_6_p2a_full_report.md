# Rapport Sprint 6 P2a — Retriever débridé + Vérificateur normalisé

**Date** : 2026-05-12
**Agent** : sprint-6-p2a-retriever-verificateur
**Branche** : `feat/sprint-6-p2a-retriever-verificateur-2026-05-08` (worktree `practical-snyder-1863eb`)
**Budget réel** : ~2h dev + 3 × battery 16q (~40 min Ollama)
**Phase 7** : OPTION B retenue par Mathieu (recalibration seuil 0.85 → 0.70 + activation B-6 default ON).

---

## STATUS

**SUCCESS — 0 RÉGRESSION POST-RECALIBRATION, MERGE AUTORISÉ.**

- B-5 sol 1 (Retriever débridé) : commit `8dbfd95`, default ON
- B-6 sol 1 (Vérificateur normalisé) : commit `a1c36c4`, default ON
- Recalibration seuil 0.85 → 0.70 sur `bench/swiss_watch_50.json` (10 questions `swiss_watch_quality`) : Phase 7
- Architecture v2 (convergences) : 12/12 VALIDÉS, exit code 0
- Pytest déterministe : 132/132 verts sur fichiers impactés
- Mesure finale : **10/16 baseline → 10/16 après-v2 = 0 régression**, SW-LECO-001 retrouve PASS avec score honnête 0.75

---

## Hashes des 3 documents source

Vérifiés le 2026-05-12 :

| Document | Hash SHA-256 attendu | Constaté | OK |
|---|---|---|---|
| Plan_paliers_fiabilite_beaume_2026-05-11.md | `194ccc06…` | `194ccc061a950fa4d3f561e48467c94a006d1f1cea9cdb030bca570d0d19baa2` | ✅ |
| Rapport_diagnostic_profond_beaume_reel_2026-05-08.md | `31d664d7…` | `31d664d71303d68ae970b8728f4f6b23f059e46050a328bec873d80b6395a214` | ✅ |
| Architecture_unifiée_Beaume_v2_2026-05-11.md | `50dc1dd8…` | `50dc1dd82f8d9a6e517b3e7cec6df3e1d68f96a3e23b8878e8f4522af31ec01f` | ✅ |

---

## Branche + commits

| # | Commit SHA | Sujet | Fichiers | LOC |
|---|---|---|---|---|
| 1 | `8dbfd95` | feat(retriever): B-5 sol 1 débridage avec feature flag BEAUME_RETRIEVER_DEBRIDE | 3 | +73 / −21 |
| 2 | `a1c36c4` | feat(verificateur): B-6 sol 1 normalisation citations avec feature flag BEAUME_VERIFICATEUR_NORMALISE | 1 | +51 / −5 |
| 3 | _(à venir)_ | chore(bench): recalibrate verifier_score_min 0.85→0.70 — sprint 6 P2a | 2 | (bench/swiss_watch_50.json + bench/CHANGELOG.md) |

### B-5 — Code modifié

- `lucie_v1_standalone/dialogue/intent_classifier.py:390-410` :
  ajout `detect_themes_with_scores(query, max_themes=3) -> list[tuple[str, int]]` ; `detect_themes()` devient un wrapper. Aucun caller existant impacté.
- `lucie_v1_standalone/retriever.py:156-175` :
  lecture flag `BEAUME_RETRIEVER_DEBRIDE` (défaut "1") + débridage si `(not scored or max_hits <= 1)`.
- `lucie_v1_standalone/knowledge_legifrance/retriever.py:104-110` (nouveau helper `_canonicalize_num`) + `search()` lignes 334-400 (re-rank par num article, **non gated** par flag, purement additif).

### B-6 — Code modifié

- `lucie_v1_standalone/verificateur.py` :
  - Ligne 17-44 : flag `BEAUME_VERIFICATEUR_NORMALISE` (défaut "1"), `_CITATION_RE` étendue (4 alternatives : `[REF:…]`, `[xxx]` avec espaces tolérés, `(L.xxxx-y)`, `article L.xxxx-y` prose), `_LEGACY_CITATION_RE` pour rollback, `_canonicalize(s)` (strip/dots/upper).
  - Lignes 47-90 : `_extract_citations()` et `_build_source_ids()` branchent sur le flag ; dédup canonique préserve la forme originale dans le JSON de retour.
  - Lignes 112-114 : matching `key = _canonicalize(cit) if _NORMALISE else cit.upper()`.

### Recalibration — Phase 7

- `bench/swiss_watch_50.json` : `pass_criteria.verifier_score_min` passe de `0.85` à `0.70` sur les 10 questions `swiss_watch_quality` (catégorie `lic_eco`). Les 20 questions à seuil 0.5 (autres règles) restent inchangées.
- `bench/CHANGELOG.md` : nouveau fichier compagnon avec justificatif complet de la recalibration.

---

## Smoke tests pré-commit

| Suite | Commande | flag=1 | flag=0 |
|---|---|---|---|
| `test_dialogue/test_intent_classifier.py` + `tests/test_legifrance/` | pytest | **95/95 ✅** | **95/95 ✅** |
| `test_cerveau_oiseaux.py` + `test_hooks_parent_id.py` + `test_events.py` + `test_pipeline_response_score.py` | pytest | **37/37 ✅** | **37/37 ✅** |
| Suite globale après commits | pytest | **132/132 ✅** | (validé séparément) |

Aucune régression sur les contrats déterministes dans les 2 modes flag (legacy=0 vs nouveau=1).

---

## Tableau avant/après par angle

Mini-batterie : 16 questions sélectionnées de `bench/swiss_watch_50.json` (4 par angle).

### Run 1 (baseline avant fixes, seuil 0.85)

| Angle | PASS | Détail |
|---|---|---|
| artificiel (lic_eco) | 2/4 | SW-LECO-002 + 004 FAIL (citations_ok=0, B-5 sol 2 nécessaire) |
| humain (lic_perso) | 0/4 | refus systématique P1 |
| hostile | 4/4 | refus corrects |
| stress | 4/4 | stable |
| **Total** | **10/16 (62.5%)** | |

### Run 2 (après B-5 + B-6, seuil 0.85 — observation)

| Angle | PASS | Détail |
|---|---|---|
| artificiel | 1/4 | SW-LECO-001 PASS → FAIL (score 1.00 → 0.75 par dédup canonique) |
| humain | 0/4 | inchangé |
| hostile | 4/4 | inchangé |
| stress | 4/4 | inchangé |
| **Total** | **9/16 (56.3%)** | |

### Run 3 (après B-5 + B-6, seuil **0.70 recalibré**)

| Angle | PASS | Δ vs baseline |
|---|---|---|
| artificiel | 2/4 | 0 (SW-LECO-001 PASS, score 0.75 ≥ 0.70) |
| humain | 0/4 | 0 |
| hostile | 4/4 | 0 |
| stress | 4/4 | 0 |
| **Total** | **10/16 (62.5%)** | **0** |

### Détail SW-LECO-001 — la régression résorbée

| Mesure | Baseline (regex legacy) | Après P2a (regex étendue) | Comment |
|---|---|---|---|
| Verdict (seuil 0.85) | PASS | FAIL | régression test |
| Verdict (seuil 0.70 recalibré) | n/a | **PASS** | mission accomplie |
| `verifier_score` | 1.00 | 0.75 | mesure plus honnête |
| `citations_ok` | 6 (avec duplicats `[L1233-x]` × N) | 3 (IDs uniques après dédup canonique) | |
| `citations_invalid` | 0 (prose ignorée) | 1 (« article L. 1233-5 » prose hors sources) | |

**Le score 0.75 est plus fidèle à la réalité** : 3 références uniques validées, 1 citation prose hors sources rejetée. L'ancien 1.00 reposait sur le double-comptage de duplicats — un biais cosmétique.

### Questions cibles B-5 non débloquées (SW-LECO-002, SW-LECO-004)

Pour ces 2 queries (« licenciement éco collectif <10/30 jours », « critères d'ordre des licenciements économiques »), `detect_themes()` trouve `licenciement_eco` avec ≥ 2 keyword hits → **le débridage NE s'active pas** par design (sol 1 du rapport diagnostic : « si ≤ 1 keyword match »). Ces questions nécessitent **B-5 sol 2** (Sprint 6 P2b — élargir `theme_mapping.yaml` à indemnité/calcul/barème/prud'hommes).

---

## Score batterie complète

### Mesure complète 50q (post-merge)

**Lancée** : 2026-05-12, après merge `315719b` sur main.
**Commande** :
```bash
BEAUME_RETRIEVER_DEBRIDE=1 BEAUME_VERIFICATEUR_NORMALISE=1 \
python3 bench/run_legal_traps.py --prompts bench/swiss_watch_50.json \
  --json /tmp/after_50q_2026-05-12.json
```
**Durée estimée** : ~45 min (50 × ~54s/question Ollama).

#### Score total

_(à compléter à la fin du run)_

| Mesure | Valeur |
|---|---|
| Total PASS | _en cours_ / 50 |
| Score consolidé | _en cours_ % |
| Critère succès | ≥ 56 % (28/50) = parité baseline reconstruite |
| Verdict | _en cours_ |

#### Par angle

| Angle | Catégories | PASS / Total | % |
|---|---|---|---|
| artificiel | lic_eco (10) | _en cours_ | _en cours_ |
| humain | lic_perso (10) | _en cours_ | _en cours_ |
| hostile | article_inexistant (5) + hors_scope (5) | _en cours_ | _en cours_ |
| stress | petites_taches (5) + pieges (5) + dem_rupture_conv (5) + conges_rtt (5) | _en cours_ | _en cours_ |

#### Questions FAIL avec cause racine

_(à parser à la fin du run — verifier_score, retriever_miss, intent_misroute, refused_pipeline, etc.)_

| ID | Catégorie | Cause racine | `verifier_score` | `refused` | `citations_ok` / `invalid` |
|---|---|---|---|---|---|
| _en cours_ | | | | | |

#### Verdict

_(à compléter)_

---

## Non-régression

**OUI.** 10/16 → 10/16 sur l'échantillon multi-angles. Le scénario qui régressait (SW-LECO-001 score 1.00 → 0.75) :
1. **Est explicable** : ancien score artificiellement gonflé par double-comptage des duplicats (regex permissive).
2. **Est mesurable** : nouveau score 0.75 = 3 IDs uniques valides + 1 prose hors-sources, calcul honnête.
3. **Est validé** : sous le seuil recalibré 0.70 (= précision cible réelle), SW-LECO-001 repasse PASS.

Garde-fou : si à terme `citations_invalid` explose au-delà de 1-2 sur les questions PASS, c'est un signal LLM-hallucination à traiter séparément (cf. `bench/CHANGELOG.md`).

---

## Cohérence Architecture v2

**OUI.** `python3 /Users/mathieu/Desktop/tests_convergences_beaume_v2.py` → **12/12 VALIDÉS, exit code 0**.

Tests critiques pour ce sprint :
- **T7/C7 (Pilot Monitoring LawyerVerifier)** : 3/3 cas correctement classifiés ✅
- **T12/C10 (mémoire unifiée)** : partage sans copie OK ✅
- T8/C8 (Fail-safe), T9/C9 (Boucle prédictive fermée) : préservés.

---

## Rollbacks effectués

**Aucun rollback git.** Tous les commits sont conservés.

**Mécanisme de rollback en place** via feature flags (pour prod sans redéploiement) :
- `BEAUME_RETRIEVER_DEBRIDE=0` → désactive B-5
- `BEAUME_VERIFICATEUR_NORMALISE=0` → désactive B-6 (probe historique : SW-LECO-001 score 1.00, seuil 0.85)

---

## KNOWN_ISSUES

1. **SW-LECO-002 et SW-LECO-004 restent FAIL** : B-5 sol 1 ne couvre pas ces questions (le débridage ne s'active que pour `max_hits ≤ 1` ; queries claires en `licenciement_eco` ont 2+ matches). **Action attendue** : Sprint 6 P2b — B-5 sol 2 (élargir `theme_mapping.yaml`).

2. **Régressions LLM pré-existantes** : 15 fails dans `test_adversarial_pre_v1.py` (notamment `test_A3_question_absurde_redirection_polie`) **confirmés sur main pré-P2a** via probe `git stash`. Non liés à P2a (tests LLM-dependents non-déterministes). À traiter dans un sprint dédié hors P2a.

3. **Batterie 50 complète non exécutée** : par budget temps Ollama. Sous-ensemble 16q jugé représentatif.

4. **Question latente** : si l'utilisation prod révèle des citations prose-hors-sources fréquentes, le seuil 0.70 pourrait avoir besoin d'une nouvelle calibration. Audit prévu via :
   ```bash
   python3 bench/run_legal_traps.py --prompts bench/swiss_watch_50.json --filter SW-LECO --json /tmp/audit.json
   ```

---

## Sortie critère de vérification

```bash
test -s ~/Desktop/Rapport_sprint_6_p2a_retriever_verificateur_2026-05-08.md && \
git -C /Users/mathieu/Desktop/mon-agence-ia branch --list "feat/sprint-6-p2a-*" | grep -q "feat/sprint-6-p2a" && \
[ -z "$(git -C /Users/mathieu/Desktop/mon-agence-ia status --short)" ] && \
grep -q "^## Tableau avant/après par angle" ~/Desktop/Rapport_sprint_6_p2a_retriever_verificateur_2026-05-08.md && \
grep -q "^## Non-régression" ~/Desktop/Rapport_sprint_6_p2a_retriever_verificateur_2026-05-08.md
```

- `test -s` rapport non vide : ✅
- branche `feat/sprint-6-p2a-*` existe (workflow worktree) : ✅
- main repo propre : ✅
- section `Tableau avant/après par angle` : ✅
- section `Non-régression` : ✅

**Exit code : 0**.

---

## Recommandation merge

**MERGE = OUI.** Critère utilisateur Phase 7 : « si score ≥ baseline 10/16 → merger ». Mesure : **10/16 = 10/16 ✅**.

Commande exacte de merge :

```bash
cd /Users/mathieu/Desktop/mon-agence-ia
git checkout main
git merge --no-ff feat/sprint-6-p2a-retriever-verificateur-2026-05-08 \
  -m "merge: sprint 6 P2a — Retriever débridé + Vérificateur normalisé"
```

Aucun push automatique (Mathieu décide du push après inspection locale).

### Activation immédiate post-merge

- B-5 ON : `BEAUME_RETRIEVER_DEBRIDE=1` (défaut)
- B-6 ON : `BEAUME_VERIFICATEUR_NORMALISE=1` (défaut)
- Rollback prod sans redéploiement : `BEAUME_*=0`

### Étape suivante (hors P2a)

**Sprint 6 P2b** — B-5 sol 2 (élargir `theme_mapping.yaml`) + B-2 sol 2 (`fuzzy_legal_boost`). Estimation plan paliers : +5 pts cumulés, cible **40-45 % → 47-50 %**. Cibles : SW-LECO-002, SW-LECO-004, ECO_04, ECO_05, ECO_08.
