# Intégration Légifrance — Carnet de reprise

> Source de vérité pour reprendre la tâche si crash/interruption/relais. Mis à jour **avant** chaque transition d'étape. Commité au fil de l'eau sur `feat/legifrance-integration`.

## État global
- Dernière MAJ : `2026-04-20T00:00:00+02:00`
- Étape en cours : **3/6 — Implémentation**
- Statut global : `en cours`
- Worktree : `/Users/mathieu/Desktop/mon-agence-ia/.claude/worktrees/kind-mcclintock-8d2353`
- Branche feat : `feat/legifrance-integration` (ex `claude/kind-mcclintock-8d2353`)
- Branche cible merge : `integration/v1-consolidated-2026-04-17`
- Tests baseline : **185/185 verts** (133 lucie_v1_standalone/tests + 52 tests/)
- Plan de référence : `/Users/mathieu/.claude/plans/ton-r-le-ing-nieur-fluttering-babbage.md`

## Hash de reprise (pour rollback)
- **Pré-merge commit de la branche cible** : `d904a94` (`docs(audit): rapport audit système complet 2026-04-20`)
- Commande de rollback : `git checkout integration/v1-consolidated-2026-04-17 && git reset --hard d904a94`
- Base de l'arbre feat : `d904a94` (HEAD au moment du branching)

## Étapes

### ✅ Phase 1 — Recherche et arbitrage (terminée)
- Terminée le : `2026-04-20`
- Verdict :
  - **Source primaire** : dump officiel DILA LEGI sur `https://echanges.dila.gouv.fr/OPENDATA/LEGI/`. Archive full `Freemium_legi_global_*.tar.gz` (~1.1 GB) + incrémentaux quotidiens `LEGI_YYYYMMDD-HHMMSS.tar.gz` (300 KB–42 MB).
  - **Parser** : `legi.py` (Legilibre, CC0, ~60★) vendoré dans `lucie_v1_standalone/knowledge_legifrance/vendor/legi/`. Inactif depuis nov 2021 (`pushed_at: 2022-04-30`), officiellement Python 3.7-3.9 → patch requis pour Python 3.13.
  - **Exclus** : dila2sql (archivé 2020, PostgreSQL), codes-juridiques-francais (Markdown dérivé, MAJ opaque), API PISTE (authentifiée, non 100% local).
  - **Scope** : tout LEGI importé, filtrage par thème au retrieval (base ~3 GB).
- Fichiers produits : `/Users/mathieu/.claude/plans/ton-r-le-ing-nieur-fluttering-babbage.md`
- **Prochaine étape** : déjà passée — Phase 2.

### ✅ Phase 2 — Architecture (terminée)
- Terminée le : `2026-04-20`
- Décisions clés :
  - Stockage : `~/Library/Application Support/Lucie/legifrance/legi.sqlite` (override env `LUCIE_LEGIFRANCE_DIR`).
  - Mapping thème : YAML versionné `lucie_v1_standalone/knowledge_legifrance/theme_mapping.yaml` (6 thèmes : droit_social, baux_commerciaux, divorce_famille, societes, prudhommes, fiscal_comptable).
  - API Retriever : `LegifranceRetriever.search(query, themes, top_k) -> list[LegalArticle]` avec sérialisation JSON identique au contrat actuel (non-régression du pipeline aval).
  - Feature flag : `LUCIE_LEGIFRANCE=1` (env), avec fallback sur la base curatée existante si base absente ou miss.
  - Sync auto : `launchd` plist toutes 48h, incrémentaux quotidiens appliqués.
  - AuditTrail : entrée `legifrance_sync` signée HMAC après chaque sync.
- Fichiers produits : aucun (conception dans le plan).
- **Prochaine étape** : Phase 3 — implémentation.

### 🔄 Phase 3 — Implémentation (en cours)
- Commencée : `2026-04-20`
- Ce qui est fait :
  - Branche `feat/legifrance-integration` créée (renommée depuis `claude/kind-mcclintock-8d2353`).
  - Baseline tests : 185/185 verts confirmé.
  - Hash pré-merge enregistré : `d904a94`.
  - Carnet de reprise créé (ce fichier).
  - Vendoring `legi.py@64c2c49` commité (CC0, NOTICE.md explicite, pas de patch in-place).
  - Package `knowledge_legifrance/__init__.py` créé (exporte `LegifranceRetriever`, `LegalArticle`).
  - `theme_mapping.yaml` v1.0 créé (6 thèmes × CID/filtres/mots-clés).
  - `schema.sql` créé (tables articles, codes, articles_by_theme, sync_history + FTS5 + triggers).
- Ce qui reste à faire (ordre d'exécution) :
  1. [x] Vendor `legi.py` dans `lucie_v1_standalone/knowledge_legifrance/vendor/legi/` + NOTICE.md (pas de patch in-place — wrapper contourne hunspell).
  2. [x] Créer `lucie_v1_standalone/knowledge_legifrance/__init__.py`.
  3. [x] `theme_mapping.yaml` versionné (schéma dans le plan).
  4. [ ] `downloader.py` — parse HTML index DILA + download tarballs + checksum SHA256.
  5. [ ] `parser.py` — wrapper autour de `vendor/legi/tar2sqlite.py`.
  6. [ ] `indexer.py` — matérialise `articles_by_theme` depuis `theme_mapping.yaml`.
  7. [ ] `retriever.py` — `LegifranceRetriever.search()` avec `LegalArticle` dataclass + sérialisation JSON compatible.
  8. [ ] `diff.py` — human-readable diff pour audit trail (limité 50 lignes).
  9. [ ] `scripts/legifrance_sync.py` — CLI entrée manuelle (argparse).
  10. [ ] `scripts/install_launchd.sh` + `scripts/uninstall_launchd.sh`.
  11. [ ] `scripts/legifrance_rollback.sh` avec `--dry-run`.
  12. [ ] Modifier `lucie_v1_standalone/config.py` : `LEGIFRANCE_ENABLED`, `get_legifrance_db_path()`, `LEGIFRANCE_SYNC_INTERVAL_HOURS`.
  13. [ ] Modifier `lucie_v1_standalone/retriever.py` — gated Légifrance lookup avec fallback.
  14. [ ] Modifier `lucie_v1_standalone/dialogue/intent_classifier.py` — ajouter `detect_themes(query)`.
  15. [ ] Étendre `.gitignore`.
  16. [ ] `requirements.txt` — ajouter libarchive-c, lxml, PyYAML.
  17. [ ] Mettre à jour `README.md` — section Base juridique Légifrance.
  18. [ ] Créer fixture `tests/test_legifrance/fixtures/LEGI_sample_20260418.tar.gz` (≤1 MB, 6 articles canoniques).
  19. [ ] Écrire les 7 tests (`test_downloader`, `test_parser`, `test_indexer_themes`, `test_retriever_contract`, `test_sync_incremental`, `test_audit_entry`, smoke CLI).
- **Pour reprendre** : ouvrir `lucie_v1_standalone/knowledge_legifrance/vendor/legi/LEGI_PY_VERSION` pour voir l'étape atteinte du vendoring. Continuer avec le point coché suivant dans la liste ci-dessus. Toujours vérifier `git status` et `pytest` verts avant de poursuivre.
- Questions ouvertes :
  - Le téléchargement du dump DILA complet (1.1 GB) est lourd : en dev, limiter aux fixtures ; en recette, le lancer manuellement via `--first-run`.
  - Le helper `legifrance_freshness()` et son câblage HUD sont un bonus — non bloquant pour le merge.

### ⏳ Phase 4 — Tests (à venir)
- Pré-requis : Phase 3 terminée, tous les modules implémentés.
- Critère vert strict : **185/185 existants + nouveaux tests verts**.
- Commande : `pytest lucie_v1_standalone/tests/ tests/ -v`.
- **Pour reprendre** : lancer `pytest -x` et traiter les rouges un à un.

### ⏳ Phase 5 — Merge sur `integration/v1-consolidated-2026-04-17` (à venir)
- Pré-requis : Phase 4 verte + pré-conditions du plan (README, rollback exécutable, pas de secret, hooks verts).
- Procédure :
  ```bash
  git checkout integration/v1-consolidated-2026-04-17
  git pull --ff-only   # si remote configuré
  git merge --no-ff feat/legifrance-integration \
    -m "feat(knowledge): intégration Légifrance live avec sync auto 48h"
  git tag -a v0.3.0-legifrance-live -m "Base juridique Légifrance vivante, sync auto 48h"
  ```
- **Pour reprendre** : si merge échoue (conflit), analyser sans force-reset. Si remote absent, commit local + noter dans le rapport final.

### ⏳ Phase 6 — Rapport final (à venir)
- Fichier : `~/Documents/Lucie/04_Recherche/Integration_Legifrance_Rapport_2026-04-20.md`
- Contenu : choix parser + raison, schéma, résultats tests, commandes opérateur, coût disque mesuré, temps sync mesuré, limites, hash merge + tag.

## Décisions prises (append-only)
- `2026-04-20` : parser = **legi.py vendoré** (plutôt que parser custom ou hybride). Raison : CC0, battle-tested sur cas légaux tordus, inactif mais fonctionnel — risque de dette technique accepté, mitigé par le fait qu'il est vendoré (on peut patcher).
- `2026-04-20` : scope = **tout LEGI, filtrage au retrieval** (plutôt qu'ingestion filtrée). Raison : ajouter une édition = modifier YAML sans re-sync. Coût disque ~3 GB jugé acceptable pour un Mac avocat.
- `2026-04-20` : base de merge = **`integration/v1-consolidated-2026-04-17`** (pas `main` littéral qui est 30+ commits en retard). Mathieu a validé : `main` sera rattrapé séparément.
- `2026-04-20` : `LEGIFRANCE_ENABLED` feature flag **off par défaut** — on active seulement quand la base est synchronisée. Évite de casser le pipeline v1 si la base est absente.

## Blocages rencontrés
_(aucun pour l'instant)_
