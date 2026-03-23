# Rapport de test utilisateur — Lucie

**Date** : 2026-03-23
**Testeur** : Claude Code (QA automatisé)
**Durée session** : ~7 minutes (20:32 — 20:39)

## Résumé exécutif

| Métrique | Valeur |
|----------|--------|
| Tests exécutés | 29 |
| Réellement réussis (réponse utile) | 7 |
| Timeouts internes (15s → "requête trop longue") | 18 |
| Timeouts externes (30s → crash test) | 2 |
| Erreurs runtime | 0 |
| Taux de réussite **réel** | **24%** |

> Note : Le code retourne "OK" pour les timeouts internes car ils sont gérés gracieusement, mais l'utilisateur reçoit "Désolé, la requête a pris trop de temps" — ce qui est un échec fonctionnel.

## Ce qui fonctionne

- **Salutations** (fast path) : instantanées (<1ms) — "bonjour", "salut", "merci", "au revoir"
- **Initialisation complète** : moteur, 15 agents, EventBus, P2P, énergie, mémoire — tout s'initialise sans crash
- **Pipeline multi-étapes** : la décomposition LLM fonctionne (PlannerAgent décompose correctement), mais trop lent
- **Création de fichiers** : 1 fichier sur 3 créé avec succès (`idees_projet.txt` en 25s)
- **Arrêt propre** : `stop_async()` ferme tous les composants sans erreur

## Ce qui ne fonctionne pas

### Bug 1 — CRITIQUE : Appels LLM synchrones bloquent la boucle asyncio

- **Symptôme** : 18/29 requêtes timeout à exactement 15.0s
- **Commandes affectées** : TOUTES les requêtes non-salutations qui ne sont pas des pipelines
- **Cause racine** : `ExecutionEngine.call_llm()` (cortex.py:1053) est une méthode **synchrone** qui appelle `manager.generate()` — un appel HTTP bloquant. Quand elle est invoquée depuis `think()` (async), elle bloque le thread de la boucle événementielle pendant 10-15s. Le timeout de `asyncio.wait_for()` ne peut pas se déclencher car la boucle est gelée.
- **Fichier** : `app/brain/cortex.py:1053-1095`
- **Chaîne d'appel** : `process_async()` → `_process_async_core()` → `cortex.think()` → `path_func(query)` [sync lambda] → `call_llm()` → `manager.generate()` [bloque le thread]
- **Impact** : Lucie est inutilisable pour toute question nécessitant le LLM

### Bug 2 — HAUTE : Timeout interne trop court (15s)

- **Symptôme** : Même quand le LLM répond (10-12s pour qwen2.5:7b), le pipeline complet dépasse 15s
- **Cause** : `effective_timeout = 15.0` dans `process_async()` (engine.py:696)
- **Fichier** : `app/core/engine.py:696`
- **Fix** : Augmenter à 30-45s pour les requêtes simples

### Bug 3 — HAUTE : Pipeline multi-étapes timeout à 30s

- **Symptôme** : 2 créations de fichiers échouent par timeout (30s)
- **Commandes** : "crée un fichier dossier_dupont.txt..." et "crée un fichier todo.md..."
- **Cause** : Le pipeline décompose en 2 étapes (WorkspaceAgent + FileAgent), chacune nécessitant un appel LLM. La décomposition prend ~11s, puis chaque étape ~5-7s = 23-25s total. Le timeout de 30s du test est trop juste.
- **Fichier** : `app/core/engine.py:659` (`effective_timeout = 60.0`)

### Bug 4 — MOYENNE : Erreur de formatage logger

- **Symptôme** : `TypeError: not all arguments converted during string formatting` dans les logs
- **Fichier** : `app/core/engine.py:674` et `app/core/engine.py:714`
- **Cause** : `logger.debug("engine.process_latency", latency)` utilise le formatage `%` au lieu de f-string
- **Fix** : `logger.debug(f"engine.process_latency: {latency:.3f}")`

### Bug 5 — INFO : Thalamus sémantique désactivé

- **Symptôme** : Warning à chaque requête non-salutation
- **Cause** : sentence-transformers non installé, le Thalamus tente de s'initialiser et échoue
- **Impact** : Log pollution, pas de crash

## Détail par profil

| Profil | Commandes | Réussies | Timeout 15s | Timeout 30s |
|--------|-----------|----------|-------------|-------------|
| Avocat | 6 | 1 (bonjour) | 4 | 1 |
| Développeur | 5 | 0 | 3 | 2 (dont 1 réussie à 25s) |
| Étudiant | 4 | 0 | 4 | 0 |
| Entrepreneur | 4 | 0 | 4 | 0 |
| Créatif | 3 | 1 (fichier créé 25s) | 2 | 0 |
| Transversal | 7 | 3 (salutations) | 4 | 0 |

## Latences observées

| Type | Latence | Statut |
|------|---------|--------|
| Salutations (fast path) | <1ms | OK |
| Décomposition pipeline (LLM) | 10-12s | Lent mais fonctionne |
| Appel LLM simple | >15s | Timeout |
| Pipeline complet (2 étapes) | 25-30s | Borderline |

## Priorité des fixes

1. **Bug 1** — Rendre `call_llm` async avec `run_in_executor` → débloque 90% des requêtes
2. **Bug 2** — Augmenter le timeout à 30s minimum → évite les faux timeouts
3. **Bug 4** — Corriger le formatage logger → nettoie les logs
4. **Bug 3** — Augmenter le timeout pipeline → les pipelines passent
5. **Bug 5** — Informatif, pas de fix nécessaire
