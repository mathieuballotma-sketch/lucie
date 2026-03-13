# Agent Lucide — Contexte pour Claude Code

## Vision
Agent Lucide est un assistant IA local open-source pour macOS.
Il tourne entièrement sur la machine de l'utilisateur (Ollama + Python).
Objectif : démocratiser l'IA — pas un service cloud, mais une intelligence que l'utilisateur possède.

## Priorité absolue actuelle : STABILITÉ
Avant toute nouvelle fonctionnalité, le code doit être :
- Sans erreur Pylance (0 rouge dans VS Code)
- Sans crash au démarrage
- Sans warning critique dans les logs
- Avec des fallbacks gracieux partout

## Stack technique
- Python 3.13, asyncio, PyObjC (macOS)
- Ollama (LLM local)
- SQLite (mémoire épisodique)
- sentence-transformers + FAISS (RAG vectoriel — à activer)
- Prometheus (métriques)
- aiohttp (P2P)

## Architecture
```
app/
├── agents/        # Tous les agents spécialisés (BaseAgent)
├── brain/
│   ├── cortex.py          # FrontalCortex, orchestration
│   └── synapses/
│       ├── event_bus.py   # EventBus pub/sub async
│       └── bus.py         # SynapseBus
├── core/          # LucidEngine, Config, Executor, Elasticity
├── memory/        # EpisodicMemory (SQLite), WorkingMemory, MemoryService
├── providers/     # ProviderManager (Ollama)
├── services/      # PromptCache, RAG, Scheduler, WebSearch, Audio
├── ui/            # HUD natif Cocoa (PyObjC)
├── utils/         # CircuitBreaker, logger, metrics, errors, json_parser
└── p2p/           # P2PNode
```

## Règles de code — TOUJOURS respecter

### 1. Optional guards obligatoires
Partout où un attribut peut être None, utiliser une variable locale :
```python
# CORRECT
event_bus = self.event_bus
if event_bus is None:
    return
await event_bus.subscribe(...)

# INTERDIT
await self.event_bus.subscribe(...)  # self.event_bus peut être None
```

### 2. Jamais de MetricsCollector
`MetricsCollector` n'existe pas dans ce projet.
Utiliser les fonctions directes de `app/utils/metrics.py` :
- `record_tool_execution(agent, tool, duration, success)`
- `record_llm_request(model, tokens, duration)`
- `start_metrics_server(port)`

### 3. Imports pydantic
Toujours utiliser `from pydantic.v1 import` (compatibilité pydantic v2).

### 4. EventBus.register_source() est async
Dans les méthodes sync (__init__), utiliser `uuid.uuid4()` à la place.
Dans les méthodes async, toujours `await event_bus.register_source(...)`.

### 5. Handlers d'événements
Toujours async :
```python
async def _on_something(self, event: Event) -> None:
```

### 6. Typage complet
- `Optional[X]` pour tout paramètre avec valeur par défaut None
- Type hints sur toutes les méthodes publiques
- Docstrings sur toutes les classes et méthodes publiques

### 7. Logging
```python
from ..utils.logger import logger
logger.debug / info / warning / error
# Jamais logger.ERROR — niveau transitoire → debug
```

## APIs réelles confirmées

### app/utils/metrics.py
Exporte : `start_metrics_server(port)`, `record_tool_execution()`, `record_llm_request()`
N'exporte PAS : `MetricsCollector` (n'existe pas)

### app/utils/circuit_breaker.py
`CircuitBreaker.call(func, fallback, *args)` — synchrone uniquement

### app/utils/errors.py
`ToolError`, `ToolValidationError`, `ToolExecutionError`, `ToolNotFoundError`,
`PathExecutionError`, `AgentNotFoundError`

### app/brain/synapses/event_bus.py
- `register_source(source, publish_channels, subscribe_channels)` → async, retourne token
- `subscribe(channel, handler, source, token)` → async
- `publish(channel, data, source, token)` → async

## État actuel des agents

| Agent | État | Notes |
|-------|------|-------|
| HUD Cocoa | ✅ Opérationnel | Fenêtre flottante macOS |
| FrontalCortex | ✅ Opérationnel | Orchestration centrale |
| CyberAgent | ✅ Token injecté | Surveillance sécurité |
| HealerAgent | ✅ Token injecté | Surveillance fichiers |
| ProfileAgent | ✅ get_recent() ajouté | Profil utilisateur |
| PlannerAgent | ✅ Opérationnel | Décomposition tâches |
| CreatorAgent | ✅ Opérationnel | Génération contenu |
| FileAgent | ✅ Opérationnel | Gestion fichiers |
| ComputerControlAgent | ✅ Opérationnel | Contrôle macOS |
| DocumentAgent | ✅ Opérationnel | Word/PDF/Excel |
| ReminderAgent | ✅ Opérationnel | Rappels |
| DeceptionAgent | ✅ Opérationnel | Honeypots |
| KnowledgeAgent | ✅ Opérationnel | Base de savoir |
| RAG | ✅ Opérationnel | FAISS + mxbai-embed-large via Ollama |
| P2P | ⚠️ Non sécurisé | TLS à implémenter |

## Warnings non-bloquants connus
- `sentence-transformers non disponible` → concerne uniquement le PromptCache, pas le RAG (qui utilise OllamaEmbedder)
- Port 8000 occupé → instance précédente, faire pkill avant relance

## Commande de lancement
```bash
PYTHONPATH=. python3 main_hud.py
```

## Philosophie de développement
Appliquer les lois universelles au code :
- **Moindre action** : fix maximum impact, changements minimaux
- **Homéostasie** : fallbacks partout, le système se stabilise seul
- **Évolution** : adapter sans casser ce qui fonctionne
- **Symbiose** : chaque agent renforce les autres via EventBus
- **Entropie** : réduire le désordre — types stricts, erreurs explicites

## Ordre de priorité des tâches
1. **Stabilité** — 0 erreur statique, 0 crash runtime
2. **Connectivité** — tous les agents branchés et communicants
3. **Mémoire** — RAG vectoriel actif (sentence-transformers)
4. **Pipeline** — agents en chaîne automatique
5. **P2P sécurisé** — TLS + authentification mutuelle
6. **Tests** — pytest sur tout le core

## Ce qu'il NE FAUT PAS faire
- Ajouter des fonctionnalités avant que la stabilité soit atteinte
- Créer des dépendances circulaires entre agents
- Utiliser pickle pour la sérialisation (sécurité)
- Laisser des TODO sans ticket associé
- Ignorer les erreurs avec un bare `except: pass`