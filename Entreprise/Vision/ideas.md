# Ideas — Lucie

## Format : [DATE] NOM — description courte

[2026-03-16] GHOST_TERMINAL — instance Terminal masquée permanente (Alpha=0), évite coût création processus. Gain : 2322ms → ~0ms
[2026-03-16] AX_OBSERVER — kAXWindowCreatedNotification au lieu de sleep fixes sur activation fenêtres macOS
[2026-03-16] VACUUM_HEALER — VACUUM SQLite dans HealerAgent pendant phases inactivité (homéostasie)
[2026-03-16] TASK_GRAPH — réseau d'exécution pour tâches complexes multi-étapes avec nodes dépendants
[2026-03-16] VISION_AGENT — moondream/llava pour remplacer sleep() aveugles par détection visuelle réelle
[2026-03-16] FEEDBACK_AGENT — boucle rétroaction sur succès/échecs agents, auto-apprentissage routage
[2026-03-16] CONTEXT_BRIDGE — ProfileAgent connecté à tous les agents via EventBus, contexte enrichi
[2026-03-16] MODELE_PULMONAIRE — score fraîcheur sur mémoire épisodique, purge auto données périmées
[2026-03-16] SEMAPHORE_3 — passer sémaphore Ollama de 2 à 3 slots après libération VRAM nano
[2026-03-16] TRIPLE_PIPELINE — qwen2.5:7b extract → qwen2.5:14b analyse → gemma2:9b rédige
[2026-03-16] EMBEDDING_CACHE — cache embedding blake2b sur requêtes répétées, gain 30-40ms
[2026-03-16] JS_POLLING — remplacer sleep fixe Google par polling JS document.querySelector