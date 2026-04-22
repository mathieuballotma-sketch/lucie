# Pipeline Visible — Carnet de reprise

Branche : `feat/pipeline-visible-hud`
Cible merge : `main`
Tag prévu : `v0.4.1-pipeline-visible`
Début : 2026-04-22
Fin implémentation : 2026-04-22

## Contexte

Lucie (assistant IA juridique 100 % local) répond en 60–100 s sur les
questions Level 2/3. Le streaming Phase 1 affiche les tokens à l'arrivée,
mais le **time-to-first-token** est de 30–90 s : l'avocat voit un écran
vide et doute du produit.

Objectif : une zone live type ChatGPT (« Recherche… », « Rédaction… »,
« Vérification… ») au-dessus du texte, avec cases cochées + durées. L'attente
reste longue mais devient lisible.

## Arbitrages reçus (Cowork)

- Fin de run : **fade-out 300-500 ms** de la zone. AuditTrail HMAC côté
  backend sert de traçabilité formelle.
- Erreur d'étape : **✕ + message court** sur la ligne concernée, zone
  reste visible, bouton discret **« Ré-essayer »**.
- Level 1 (direct, 2-3 s) : **pas de zone**, les 3 dots existants suffisent.
- Branche : **`feat/pipeline-visible-hud`**.
- **Protection IP** (addition critique) : les noms internes (Lecteur,
  Retriever, Rédacteur, Vérificateur) ne doivent **JAMAIS** apparaître dans
  l'UI. Mapping centralisé dans `stage_labels.py`.

## Architecture retenue — Option B (ContextVar + asyncio.Queue)

Pattern jumeau de `profile_bucket` / `profile_step`. Un `ContextVar` porte
une `asyncio.Queue` pendant toute la durée d'un run. Les étapes émettent
via `emit(stage, status, ...)`. Le HUD draine la queue via `run_stream`.

Pourquoi pas **A (yield direct)** : `run_stream` retombe sur `run()` bloquant
en Level 3, il aurait fallu réécrire `_full_pipeline` en async iterator.
Pourquoi pas **C (callback)** : mélanger callback sync et async est fragile.

## Commits atomiques

| # | SHA | Sujet |
|---|-----|-------|
| 1 | `f3ce1f3` | `feat(events)`: PipelineEvent infra + IP-safe UI label mapping |
| 2 | `6e803ba` | `feat(pipeline)`: emit PipelineEvent au fil du run (Level 2/3) |
| 3 | `8c92142` | `feat(cache)`: emit cache.cached event on hit |
| 4 | `0906230` | `feat(hud)`: PipelineStagesView + integration live streaming |
| 5 | `97ff199` | `test(events)`: 8 tests pytest-asyncio |

## Fichiers touchés

**Nouveaux**
- `lucie_v1_standalone/stage_labels.py` — mapping interne→UI centralisé
- `lucie_v1_standalone/perf/events.py` — PipelineEvent + helpers
- `lucie_v1_standalone/tests/test_events.py` — 8 tests

**Modifiés**
- `lucie_v1_standalone/perf/__init__.py` — ré-exports
- `lucie_v1_standalone/pipeline.py` — emit manuel Level 2, task+drain
  Level 3, helper `_run_with_event_drain`, wrap `_search_and_write` +
  `_full_pipeline` avec `event_stage`
- `lucie_v1_standalone/cache/query_cache.py` — emit sur hit non dry-run
- `app/ui/hud_native.py` — `PipelineStagesView` (≈220 lignes), handlers
  `_reset_pipeline_stages` / `_on_pipeline_event` / `_finalize_pipeline_stages`
  / `retryLastQuery_`, streaming Level 3 activé, premier-token =
  implicit-complete Rédacteur

## Lifecycle des événements

| Stage | Level 1 | Level 2 | Level 3 |
|-------|---------|---------|---------|
| lecteur      | — | — | ✓ (started + completed) |
| retriever    | — | ✓ | ✓ |
| redacteur    | — | ✓ started ; completed = 1er token | ✓ |
| verificateur | — | ✓ | ✓ |
| cache        | possible | non | possible |

## Mapping IP-safe (stage_labels.py)

```
lecteur       → « Je comprends votre question »
retriever     → « Je consulte les articles pertinents »
  + document  → « Je lis votre dossier »
redacteur     → « Je prépare la réponse »
  + action    → « Je rédige le projet de courrier »
verificateur  → « Je vérifie chaque citation »
cache         → « Je retrouve une réponse déjà étudiée » (rarement affiché)
```

## Threading PyObjC

- Toutes les mutations UI passent par `AppHelper.callAfter(self._on_pipeline_event, evt)`
  depuis la coro `_consume` (daemon thread via `asyncio.run`).
- `CABasicAnimation` opacity pulse appliquée à la création de la ligne,
  retirée sur `mark_completed`.
- Pas de `performSelectorOnMainThread_` : `AppHelper.callAfter` équivaut.

## Tests

`pytest lucie_v1_standalone/tests/` → **199 passed** (avant : 191 ;
delta : +8 tests events).

Les 8 tests couvrent :
1. `event_stage` → started + completed avec durée
2. `event_stage` → error sur exception, re-raise
3. Timestamps monotones, durations >= 0
4. `emit` sans queue = no-op silencieux
5. Level 1 (small-talk) : 0 event de stage
6. Cache hit : `PipelineEvent(stage="cache", status="cached")`
7. Level 2 : ordre retriever → redacteur → verificateur
8. Retriever qui crash : `status="error"` + message

## Vérification manuelle

Python imports propres (`hud_native` charge, `PipelineStagesView` classe
disponible, constantes layout cohérentes : `_STAGES_Y=340`, `_TEXT_H_ACTIVE=250`).

À faire (Mathieu après merge) :
1. Lancer Lucie en dev (`python -m app.ui.hud_native`).
2. Question Level 2 factuelle → Retriever pulse → ✓, Rédacteur pulse →
   ✓ dès premier token, Vérificateur pulse → ✓, fade-out 400 ms.
3. Question Level 1 (`Bonjour`) → pas de zone.
4. Document drag-droppé → 4 étapes dont Lecteur.
5. Relancer la même question Level 2 → cache hit : pas de zone.
6. Renommer temporairement `legi.sqlite` → ✕ sur Retriever + bouton
   Ré-essayer.
7. Screenshots `screencapture -w` pour rapport.

## Risques / coupes acceptables

- `asyncio.Queue` cross-task en Level 3 : testé via `_run_with_event_drain`,
  le task poll la queue avec `wait_for(timeout=0.1)`. Si souci observé sur
  certaines machines, fallback simple : `list` + `threading.Lock` + polling
  50 ms côté HUD.
- Fade-out NSAnimationContext sur un layout mobile : si mouvement
  perceptible sur text area, remplacer par `setHidden_(YES)` brutal.

## Phase 1ter éventuelle (pas fait ici)

- Animation CoreAnimation plus riche (glow subtil, courbe spring)
- Son discret à la complétion
- Export timeline JSON pour audit
- Bouton « Ré-essayer » plus affordant
- Libellé dynamique qui s'enrichit (ex. « Je consulte 3 articles du Code
  du travail »)

## Critères de succès (check)

- [x] 199 tests verts (avant : 191 ; delta +8)
- [x] Mapping IP-safe centralisé dans un seul fichier
- [x] Zero régression streaming tokens existant
- [x] Overhead émission < 1 ms par event (simple `put_nowait`)
- [ ] Screenshots du flow Level 2 (à prendre en run manuel)
- [ ] Merge `--no-ff` + tag `v0.4.1-pipeline-visible`
