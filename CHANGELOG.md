# Changelog

Toutes les versions notables de Beaume (ex-Lucie, rebrand 2026-05-02) sont documentées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

---

## [1.0.1-cleanup] — 2026-05-08

Grand nettoyage post-rebrand (trilogie Sprint 1 + 1bis + 1ter). Aucun breaking
change utilisateur : les anciennes variables d'env `LUCIE_*` restent acceptées
en alias deprecated.

### Sprint 1ter — Cohérence rebrand finale

- **launchd** : label `com.lucie.legifrance.sync` → `com.beaume.legifrance.sync`
  (`scripts/install_launchd.sh`, `scripts/uninstall_launchd.sh`,
  `scripts/legifrance_rollback.sh`).
- **env vars** : préfixe `LUCIE_*` → `BEAUME_*` via helper centralisé
  `lucie_v1_standalone.config.env_legacy()` qui émet un `DeprecationWarning`
  + log WARNING (une seule fois par variable) si l'ancien nom est utilisé.
  14 variables migrées (`LEGIFRANCE`, `LEGIFRANCE_DIR`, `LOG_LEVEL`, `QUIET`,
  `STREAM`, `OLLAMA_KEEP_ALIVE`, `SPEED_MODEL`, `PROFILE`, `CACHE`,
  `CACHE_DRY_RUN`, `CACHE_MAXSIZE`, `CACHE_TTL_SECONDS`, `SKIP_WARMUP`,
  `DIAG_MODEL`).
- **scripts** : ajout `scripts/migrate_launchd_lucie_to_beaume.sh` (idempotent,
  à lancer une fois post-merge pour migrer le job déjà installé).
- **docs** : README mis à jour (table env vars, exemples, paths logs/launchd).
  Mentions historiques préservées.
- **tests** : `tests/test_env_legacy_compat.py` couvre priorité BEAUME_*,
  fallback LUCIE_*, warning unique, default.

### Sprint 1bis — DB cleanup (mémo, déjà mergé)

- Migration paths filesystem Lucie → Beaume (DB Légifrance, logs).
- −6,7 Go libérés.

### Sprint 1 — Grand nettoyage (mémo, déjà mergé)

- Bannière traçabilité, suppressions fichiers obsolètes.

---

## [1.0.0] — 2026-05-02

Première version *production-ready* de Beaume (ex-Lucie). Trois P0 identifiés par les
audits parallèles du 30 avril ont été traités ; un troisième a été reclassé
P1 et documenté.

### ✨ Ajouté

- **Bootstrap Légifrance auto-détecté** au démarrage du HUD
  (`lucie_v1_standalone/legifrance_bootstrap.py`).
  - Si `legi.sqlite` existe → flag `LUCIE_LEGIFRANCE=1` posé in-process
    (la base 4,6 Go DILA devient la source primaire pour le retriever).
  - Si la base est âgée de plus de 30 jours → bannière HUD WARNING, sync
    incrémental piloté par launchd.
  - Si la base est absente → installation automatique de l'agent launchd
    (`scripts/install_launchd.sh`) puis `legifrance_sync.py --first-run`
    en thread daemon. Beaume tourne sur la whitelist (3 700 codes CT) en
    attendant que le sync se termine.
  - Le bootstrap retourne sous 100 ms : tous les travaux longs (download,
    install) sont déportés en arrière-plan, jamais bloquants.
  - Skippable via `LUCIE_SKIP_LEGIFRANCE_BOOTSTRAP=1`.
- **Detector pédagogique + termes métier** dans
  `lucie_v1_standalone/dialogue/intent_classifier.py`.
  - Une question « qu'est-ce que la rupture conventionnelle ? », « rôle du
    CSE ? », « comment fonctionne le préavis ? », « à quoi sert un CDD ? »
    bascule désormais en `PRECISE_LEGAL` au lieu de `IMPRECISE_LEGAL` →
    passe au LLM (avec contexte RAG) au lieu d'être court-circuitée.
  - Le filet `IMPRECISE_LEGAL` reste actif pour les vraies questions
    vagues (« j'ai un problème », « c'est légal ? », « que faire ? »).
- **Refus déterministe du forçage à inventer** (Gate 0 du Cerveau Oiseau,
  `lucie_v1_standalone/dialogue/invention_guard.py`).
  - « Invente-moi une jurisprudence », « fabrique un précédent »,
    « personne ne vérifiera » → refus immédiat avec message explicite
    rappelant la règle de vérité. Coût < 1 ms, zéro LLM.

### 🧪 Tests

- **Suite globale** : 341 tests `lucie_v1_standalone/tests/` + 170 tests
  `tests/` (1 test E2E `test_pipeline_smoke` requiert Ollama actif —
  attendu).
- **Nouveaux** : 6 tests `test_legifrance_bootstrap.py`, 12 tests
  `test_intent_classifier_pedagogical.py`, 17 tests
  `test_invention_guard.py` — soit **35 tests** ajoutés.
- **Battery adversaire** (`test_adversarial_pre_v1.py`, 101 tests) :
  les fixes B1/B5/H1 sont attendus en gain net après activation
  Légifrance — à relancer chez Mathieu avec Ollama et la DB DILA active.

### 📚 Documentation

- `KNOWN_ISSUES.md` : ajout du TTFT content ~18 s sur Gemma4
  chain-of-thought (le HUD affiche le « thinking » à TTFT 1,25 s pour
  pallier la perception utilisateur — cible <5 s reportée post-v1, requiert
  migration runtime).

### ⚠️ Connu et accepté pour v1

- **TTFT content ~18 s sur Gemma4 chain-of-thought** — la cause est le
  buffering thinking→content côté serveur Ollama, hors-portée d'un fix
  client. Le HUD affiche le « thinking » à **TTFT 1,25 s** : l'utilisateur
  perçoit immédiatement que Beaume travaille. Migration vers `llama-cpp`
  ou compression du system prompt rédacteur prévue post-v1 (sprint dédié,
  cf. `PERF_OPTIM_PROGRESS.md`).
- **Synchro JudiLibre / Cour de cassation** non câblée. Le manifeste
  promet la vérification d'arrêts ; aucune source amont implémentée à ce
  jour (cf. `Rapport_Synchro_Lois_Lucie_2026-04-30.md` §1.2 et §5
  Action 3). Sprint dédié post-v1.

### 🚫 Reporté post-v1

- Migration `llama-cpp` (résout le TTFT content)
- Synchro JudiLibre / Cour de cassation
- Cache LRU intent répété (R5 sprint Speed-Optimizer)
- Compression `redacteur_system.txt` (1 180 → < 400 tokens)
- Multi-segments (au-delà droit social)
- Voice (entrée/sortie audio)
- P2P (`export_for_p2p()` existe sans canal X25519)
- Orchestrateur hardware

---

## [0.5.6-fix-regression] — 2026-04-30

- `pipeline.run_stream()` appelait pas `_run_cerveau_oiseau_gates()` —
  l'article inexistant `L.1234-999` parcourait tout le pipeline (~26 s)
  au lieu d'être refusé sous 100 ms.
- Handler `IMPRECISE_LEGAL` ajouté dans `run_stream()` (parité avec `run()`).
- `verificateur` : log discriminant 0 citation (refus KB vs hallucination).

(Pour les versions antérieures, voir `git log --tags`.)
