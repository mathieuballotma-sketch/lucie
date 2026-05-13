# MIGRATION_PLAN — fr_droit_travail vers Manifest-Driven Engine

**Sprint G-1 étape 2 (et étape 3 si besoin).** Plan de refactor pour extraire
le hardcoding actuel du Code du travail vers `corpus/fr_droit_travail/`.

**Statut** : PLAN UNIQUEMENT — aucun code ici. Le refactor effectif est Sprint
G-1 étape 2, à conduire une fois Sprint 6 P3 mergé sur `main` (pour éviter
les conflits sur `knowledge/`, `theme_mapping`, `bench/swiss_watch_50.json`).

---

## Vue d'ensemble

- **Audit étape 1** : ~5293 LOC hardcodées identifiées dans 20 fichiers core
  (dont 4555 LOC auto-générées par script DILA → trivial à externaliser).
- **Effort humain réel** : ~1100 LOC à refactor, réparties sur 8 sous-étapes.
- **Estimation effort étape 2** : initial 5-8 j-IA → **révisé 6-9 j-IA**.
  Recommandation : sortir la sous-étape 8 (intent_classifier) en Sprint G-1
  étape 3 pour limiter le risque cumulé sur la batterie 50q → étape 2 redescend
  à 5-7 j-IA.
- **Stratégie générale** : feature flag `BEAUME_MANIFEST_ENABLED` (défaut OFF)
  pendant la migration ; shadow mode → canary 10% → rollout 100% → cleanup
  legacy. Sortie progressive sans rupture de la batterie 50q.

---

## Ordre d'exécution (risque croissant)

| # | Sous-étape | Source actuel | Cible corpus | LOC | Complexité (1-5) | Risque régression 50q (1-5) |
|---|------------|---------------|--------------|-----|------------------|-----------------------------|
| 1 | article_bounds_data → JSON | `lucie_v1_standalone/dialogue/article_bounds_data.py` (auto-gen) | `corpus/fr_droit_travail/generated/article_bounds.json` | 4555 | 1 | 1 |
| 2 | Whitelist racines → YAML | `lucie_v1_standalone/dialogue/whitelist_ct.py` (`_RANGES`) | `corpus/fr_droit_travail/whitelist.yaml` | 342 | 2 | 2 |
| 3 | theme_mapping → corpus | `lucie_v1_standalone/knowledge_legifrance/theme_mapping.yaml` | `corpus/fr_droit_travail/themes.yaml` | 184 | 2 | 3 |
| 4 | out_of_scope → corpus | `lucie_v1_standalone/dialogue/out_of_scope_config.yaml` | `corpus/fr_droit_travail/refusals.yaml` | 108 | 2 | 3 |
| 5 | _REFUSAL_MESSAGE router | `lucie_v1_standalone/router.py:21-25` | `refusals.yaml::scope_refusal` | 5 | 2 | 3 |
| 6 | URLs Légifrance | `lucie_v1_standalone/knowledge_legifrance/parser.py:40-41` | `manifest.yaml::sources` | 2 | 1 | 1 |
| 7 | Regex citations centrales | 5 fichiers (verificateur, retriever, article_bounds, article_validator, intent_classifier) | `manifest.yaml::citation_patterns` | ~22 | 3 | 4 |
| 8 | Regex intent_classifier | `lucie_v1_standalone/dialogue/intent_classifier.py` (6 regex `_LEGAL_*`, `_LIC_PERSO_RE`, `_FAKE_ARTICLE_RE`) | `manifest.yaml::intent_patterns` (schéma v1.1) | ~60 | 4 | 5 |

---

## Détail par sous-étape

### Sous-étape 1 — `article_bounds_data.py` → JSON externe

- **Fichier source** : `lucie_v1_standalone/dialogue/article_bounds_data.py` (4555 LOC, AUTO-GENERATED par `scripts/build_article_bounds.py`)
- **Cible** : `corpus/fr_droit_travail/generated/article_bounds.json`
- **Action** : modifier `scripts/build_article_bounds.py` pour émettre du JSON au lieu d'un module Python. `lucie_v1_standalone/dialogue/article_bounds.py` charge le JSON (déjà un loader propre — minimal change).
- **Stratégie test** :
  - Hash sha256 du dict `ARTICLE_BOUNDS_DATA` pre vs post migration → identique
  - Batterie 50q complète → 100% pass
- **Why first** : effort minimal, risque quasi-nul, libère ~80% du volume LOC du chantier.

### Sous-étape 2 — Whitelist racines → `whitelist.yaml`

- **Fichier source** : `lucie_v1_standalone/dialogue/whitelist_ct.py` (constante `_RANGES`, ~250 entrées, format `[(prefix, base, suffix_min, suffix_max), ...]`)
- **Cible** : `corpus/fr_droit_travail/whitelist.yaml` (format `[{prefix, base, suffix_range: [min, max]}]`)
- **Action** : convertir tuples → YAML structuré ; adapter `whitelist_ct._build_whitelist()` pour charger depuis YAML ; supprimer la constante `_RANGES` quand le loader fonctionne.
- **Stratégie test** :
  - Test de parité : ancien `_RANGES` build vs nouveau YAML build → frozenset identique
  - Tests existants `tests/lucie_v1_standalone/tests/test_dialogue/test_whitelist*.py` doivent passer inchangés
  - Batterie 50q → 100% pass

### Sous-étape 3 — `theme_mapping.yaml` → corpus

- **Fichier source** : `lucie_v1_standalone/knowledge_legifrance/theme_mapping.yaml` (184 LOC, déjà YAML)
- **Cible** : `corpus/fr_droit_travail/themes.yaml`
- **Action** : déplacement physique + redirection chemin via `manifest.paths.themes`. Adapter les 3 consommateurs (`intent_classifier.py`, `indexer.py`, `retriever.py`) pour lire depuis `manifest.paths.themes` au lieu d'un chemin hardcodé.
- **Stratégie test** :
  - Tests existants `test_dialogue/test_intent_classifier*.py` doivent passer
  - Batterie 50q → 100% pass
- **Note Sprint 6 P3** : ce fichier est touché en parallèle par P3 → **REBASE plutôt que MERGE** au moment de Sprint G-1 étape 2 pour absorber le diff P3 proprement.

### Sous-étape 4 — `out_of_scope_config.yaml` → corpus

- **Fichier source** : `lucie_v1_standalone/dialogue/out_of_scope_config.yaml` (108 LOC, déjà YAML)
- **Cible** : `corpus/fr_droit_travail/refusals.yaml` (structure étendue : `scope_refusal` + `domains` + `priority_override`)
- **Action** : déplacement + extension format (ajout `scope_refusal` venant de la sous-étape 5) ; adapter `dialogue/out_of_scope.py` pour lire depuis `manifest.paths.refusals`.
- **Stratégie test** :
  - Tests existants `test_out_of_scope*.py` doivent passer
  - Batterie 50q → 100% pass

### Sous-étape 5 — `_REFUSAL_MESSAGE` du router → manifest

- **Fichier source** : `lucie_v1_standalone/router.py:21-25` (constante Python `_REFUSAL_MESSAGE`)
- **Cible** : `corpus/fr_droit_travail/refusals.yaml::scope_refusal` (clé top-level)
- **Action** : remplacer la constante par un chargement au boot depuis le manifest. Préserver le format exact du message (contrat utilisateur — la chaîne « Beaume V1 (licenciement économique) » est testée).
- **Stratégie test** :
  - `test_router_widening.py` adapté pour vérifier le message exact via manifest
  - Batterie 50q (les questions hors-scope sont testées sur le message exact dans `expected_behaviors.json`)

### Sous-étape 6 — URLs Légifrance → `manifest.sources`

- **Fichier source** : `lucie_v1_standalone/knowledge_legifrance/parser.py:40-41` (2 templates URL)
- **Cible** : `corpus/fr_droit_travail/manifest.yaml::sources[*].url_template`
- **Action** : remplacer les constantes par lecture depuis le manifest au boot. Pattern déjà validé par le mock-up `fr_pharma_ansm`.
- **Stratégie test** :
  - Test round-trip : `cid → URL canonique` identique pre/post
  - Tests `tests/test_legifrance/test_parser.py` doivent passer

### Sous-étape 7 — Regex citations centrales → `manifest.citation_patterns`

- **Fichiers sources** :
  - `lucie_v1_standalone/verificateur.py:35-43` (`_CITATION_RE`, `_LEGACY_CITATION_RE`)
  - `lucie_v1_standalone/retriever.py:35` (`_LEGAL_REF_RE`)
  - `lucie_v1_standalone/dialogue/article_bounds.py:87-90` (`_ARTICLE_RE`)
  - `lucie_v1_standalone/dialogue/article_validator.py:47-50` (`ARTICLE_PATTERN`)
- **Cible** : `corpus/fr_droit_travail/manifest.yaml::citation_patterns` (liste de `CitationPattern`)
- **Complexité** : ces 4 regex se recouvrent partiellement (acceptent `L.1233-3`, `L 1233-3`, `L1233-3`, `L.1233`, `[REF: L.1233-3]`, etc.) avec des nuances (suffixe max 3 vs 5 chiffres, présence d'un format prose `article L...`, etc.). Le refactor doit produire **une regex unifiée par kind** ou **plusieurs patterns coexistants** dans le manifest, sans changer la sémantique observable.
- **Stratégie test** :
  - Suite de 100+ formes de citations canoniques → toutes doivent matcher comme avant
  - Tests `tests/lucie_v1_standalone/tests/test_verificateur*.py` (couverture exhaustive)
  - Batterie 50q → 100% pass
  - Adversarial `test_adversarial_pre_v1.py` (couvre les pièges de citations)
- **Risque clé** : la normalisation `_canonicalize` dans `article_validator.py` est sensible à la position des groupes regex → tester avec et sans `BEAUME_VERIFICATEUR_NORMALISE`.

### Sous-étape 8 — Regex `intent_classifier` → `manifest.intent_patterns` (schéma v1.1)

- **Fichier source** : `lucie_v1_standalone/dialogue/intent_classifier.py` (regex `_LEGAL_REF_RE`, `_LEGAL_FIGURE_RE`, `_LEGAL_PROCEDURE_RE`, `_LEGAL_KEYWORD_RE`, `_LIC_PERSO_RE`, `_FAKE_ARTICLE_RE` — ~60 LOC)
- **Cible** : `corpus/fr_droit_travail/manifest.yaml::intent_patterns` (extension schéma v1.1 — ajout de la classe Pydantic `IntentPattern`)
- **Action** : (1) étendre `corpus/_schema/manifest_schema.py` en v1.1 avec `IntentPattern`, (2) externaliser les 6 regex, (3) adapter `intent_classifier.py` pour charger via manifest.
- **Stratégie test** :
  - `tests/lucie_v1_standalone/tests/test_intent_classifier.py` exhaustif (toutes branches)
  - `test_adversarial_pre_v1.py` (1017 LOC de cas limites — couvre les régressions classification)
  - Corpus exhaustif `tests/corpus_exhaustif/` (~230 cas)
  - Batterie 50q → 100% pass
- **Risque clé** : cette sous-étape touche le **cœur de la classification d'intent** — une régression ici impacte router widening, lic_perso detection, fake article detection. **Recommandation : différer en Sprint G-1 étape 3** (sortie progressive, test long après chaque pattern migré).

---

## Stratégie d'intégration recommandée

### Phase 1 — Shadow mode (1-2 j-IA)

Feature flag `BEAUME_MANIFEST_ENABLED=0` par défaut. Le moteur charge le
manifest mais continue d'utiliser les chemins legacy. Logs comparatifs si
divergence (manifest vs legacy) sur 10 requêtes types.

### Phase 2 — Canary (1-2 j-IA)

`BEAUME_MANIFEST_ENABLED=1` activé pour 10% des cas en local. Batterie 50q
en mode canary → comparer scores.

### Phase 3 — Rollout (1 j-IA)

Activer manifest par défaut. Le code legacy reste présent mais inerte (sous
flag inverse `BEAUME_MANIFEST_DISABLED`).

### Phase 4 — Cleanup (0.5 j-IA)

Suppression du code legacy. Réduction de ~1100 LOC dans `lucie_v1_standalone/`.

---

## Co-existence avec Sprint 6 P3 (autre branche)

- P3 touche `knowledge/`, `theme_mapping`, `bench/swiss_watch_50.json`
- Notre étape 1 (Sprint G-1) NE TOUCHE PAS ces fichiers → **zéro conflit**
- Sous-étape 3 (theme_mapping → corpus) absorbera le diff P3 par **rebase**
  au moment de Sprint G-1 étape 2 — pas par merge naïf

## Décisions à trancher avant étape 2

1. **Whitelist racines (sous-étape 2)** : YAML autonome (`whitelist.yaml`)
   ou dérivée automatiquement du manifest `themes.yaml::filtres_articles[].range` ?
   - Pour autonome : simplicité + indépendance des thèmes
   - Pour dérivée : DRY, single source of truth, mais couplage thèmes/whitelist
2. **Sous-étape 8 (intent_classifier)** : inclure en étape 2 (6-9 j-IA) ou
   différer en étape 3 (étape 2 redescend à 5-7 j-IA, risque cumulé limité) ?
3. **Articles ANSM `cid` Légifrance** (mock-up) : valider manuellement avant
   étape 2 ou laisser les `SOURCE_TO_VERIFY` ?
4. **Schéma manifest v1.1** : concevoir avant ou pendant étape 2 ?
   (recommandation : avant, pour ne pas mélanger refactor moteur et évolution schéma)
