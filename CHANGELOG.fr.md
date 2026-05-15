# Changelog

*[Read in English](CHANGELOG.md)*

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

## [1.2.1-swiss-watch] — 2026-05-08

Sprint « Swiss watch » — polish ciblé pour clore Beaume v1 avec la qualité
montre suisse exigée avant la prospection avocats sem 12-18 mai 2026
(30 cabinets ciblés, 2-3 pilotes signés). Pas de refactor architecture,
pas de feature creep — uniquement les 7 règles produit appliquées.

### ✨ Ajouté (par règle Swiss watch)

#### Règle 1 — Truth rule (déjà à 95% — KI-003 documenté)
- Aucun changement majeur, l'audit a confirmé que Cerveau Oiseaux v2,
  Vérificateur déterministe et Pipeline async sont déjà conformes.

#### Règle 2 — Montre suisse / élégance silencieuse
- **Badge `verifier_score` sous chaque réponse** (`app/ui/hud_native.py`) :
  vert ≥ 90 %, ambre 70-89 %, rouge < 70 %. Caché sur refus précoce et
  sur 0 citation extraite (évite KI-003 « vacuously true »).
- Tooltip badge expose `X citations vérifiées sur Y` + verdict.

#### Règle 3 — 100 % local
- Tooltip badge enrichi : « Vous pouvez couper votre Wi-Fi, Beaume continue
  de fonctionner » + path local du badge propagé sur l'icône lock + label.

#### Règle 4 — Archétype silencieux
- Disclaimer pipeline `Lucie V1 → Beaume v1`.
- Prompts système (`direct_system.txt`, `redacteur_search_system.txt`,
  `small_talk_handler.py`) rebrand cohérent.

#### Règle 5 — Plan psychologique avocat
- **Phrase d'accueil** au premier lancement (3 promesses : 100% local,
  vérification, sources cliquables) — flag `welcomed_v1` dans
  `~/Library/Application Support/Beaume/prefs.json`.
- Badge `verifier_score` (cf règle 2) — l'avocat voit la fiabilité.

#### Règle 6 — Transparence radicale
- **Page « Ce que Beaume sait de vous »** : popover enrichie avec en-tête,
  sous-titre 100% local + path, liste 5 types de souvenirs, bouton
  « Effacer toute la mémoire » avec **double confirmation** (NSAlert
  irréversibilité + saisie « EFFACER »).
- Backend : `MemoryStore.reset()` + `PersonalMemory.reset_all()` +
  `AbstractMemory.clear()`.

#### Règle 7 — Conscience simulée
- Pas de changement (déjà fonctionnel — 27 tests memory existants OK,
  + 5 nouveaux tests reset).

### 🔄 Renommé

- **Lucie → Beaume** (rebrand officiel 2026-05-02 finalisé côté code) :
  - Tous les strings user-facing du HUD (sender name, états, notifications).
  - Disclaimer pipeline + prompts système (small_talk, direct, redacteur_search).
  - `main_hud.py` (header + log de lancement).
  - **Préservé** (différé KI-SW-002 — post-pilote) : variable
    `_lucie_state` interne, imports `lucie_v1_standalone.*`,
    variables d'env `LUCIE_*` (compat backward).
  - **Classe `LucieState`** renommée en `BeaumeState` lors du
    nettoyage horloger du 2026-05-15 (voir entrée
    `[1.3.0-horloger-sprints]`).
- **Alias module Python** (nouveau) : `beaume/__init__.py` ré-exporte
  tout depuis `lucie_v1_standalone/` — `from beaume import pipeline`
  fonctionne. Rename physique du package reporté post-pilote.
- **Migration data dir** auto idempotente :
  `~/Library/Application Support/Lucie` → `Beaume` au premier démarrage
  (best-effort, fallback legacy si copytree échoue).

### 🛠️ Modifié

- `PipelineResponse` étendu : `citations_ok`, `citations_invalid`,
  `verdict` (champs optionnels). `verifier_score` désormais propagé
  jusqu'au HUD via ContextVar `_VERIFICATION_META` (set par
  `_format_final`, lu par `run()` et `run_stream()`).
- `bench/run_legal_traps.py` : flag `--prompts` pour pointer sur
  `bench/swiss_watch_50.json` ; `response_to_dict` élargi
  (verdict, citations_ok, citations_invalid, citations_total) ;
  champ synthétique `_swiss_watch_hallucination_signal` pour la règle
  pièges (refus OU score<0.5 OU mention « pas dans mes sources »).

### 🧪 Tests

- **Nouveaux** :
  - `tests/test_pipeline_response_score.py` — 10 tests sur la propagation
    verifier_score, counts cohérents, disclaimer Beaume.
  - `tests/memory/test_memory_reset.py` — 5 tests sur reset (clears
    nodes/patterns, counts, observe post-reset, idempotence).
- **Battery Swiss watch 50 questions** (`bench/swiss_watch_50.json`) :
  - 10 lic_eco, 10 lic_perso, 5 conges_rtt, 5 dem_rupture_conv,
    5 article_inexistant, 5 hors_scope, 5 petites_taches, 5 pieges.
  - 3 nouvelles règles : `swiss_watch_quality`, `swiss_watch_small_talk`,
    `swiss_watch_hallucination_blocked`.

### 📚 Documentation

- `KNOWN_ISSUES.md` mis à jour (cf section dédiée).
- Plan sprint : `~/.claude/plans/qui-tu-es-jiggly-twilight.md`.
- Rapport final : `~/Desktop/Rapport_v1-Swiss-watch_2026-05-06.md`.

### 🏷️ Tag

- Tag local `v1.2.1-swiss-watch` (pas de push — Mathieu valide
  visuellement avant push).

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
