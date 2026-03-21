# Agent Lucide — Contexte pour Claude Code (V2)

## Vision
Agent Lucide est un assistant IA local open-source pour macOS.
Il tourne entièrement sur la machine de l'utilisateur (Ollama + Python).
Objectif : démocratiser l'IA — pas un service cloud, mais une intelligence que l'utilisateur possède.

---

## Priorité absolue actuelle : STABILITÉ
Avant toute nouvelle fonctionnalité, le code doit être :
- Sans erreur Pylance (0 rouge dans VS Code)
- Sans crash au démarrage
- Sans warning critique dans les logs
- Avec des fallbacks gracieux partout

---

## Stack technique
- Python 3.13, asyncio, PyObjC (macOS)
- Ollama (LLM local)
- SQLite (mémoire épisodique)
- sentence-transformers + FAISS (RAG vectoriel — à activer)
- Prometheus (métriques)
- aiohttp (P2P)

---

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

---

## Ce que Claude Code doit TOUJOURS faire

1. **Lire les fichiers avant de les modifier** — jamais de modification aveugle
2. **Vérifier que les imports existent réellement dans le projet** — grep avant d'importer
3. **Tester après chaque modification** — ruff + mypy + pytest dans cet ordre
4. **Faire des changements minimaux** — pas de refactoring non demandé, pas de "nettoyage" spontané
5. **Respecter le style existant** — indentation, nommage, structure des classes déjà présentes
6. **Ne jamais créer de classes qui n'existent pas** dans le projet (ex: `MetricsCollector` n'existe pas)
7. **Toujours confirmer avant un commit ou un push** — décrire ce qui va être commis

---

## Workflow obligatoire

```
1. Comprendre le contexte (lire les fichiers concernés)
2. Faire le changement minimal nécessaire
3. Vérifier : ruff check app/ --fix
4. Vérifier : python -m mypy app/ --ignore-missing-imports --strict
5. Tester  : PYTHONPATH=. python -m pytest tests/ -x -q
6. Si tout passe → commit avec message descriptif
7. Si échec → corriger et recommencer au step 3
```

**Si un des checks échoue, corriger AVANT de commit. Jamais de commit rouge.**

---

## Commandes de validation obligatoires

Avant chaque commit, Claude Code DOIT exécuter ces trois commandes dans l'ordre :

```bash
# 1. Linting et auto-fix
ruff check app/ --fix

# 2. Typage strict
python -m mypy app/ --ignore-missing-imports --strict

# 3. Tests
PYTHONPATH=. python -m pytest tests/ -x -q
```

Critères de succès :
- `ruff` : 0 erreur restante après `--fix`
- `mypy` : 0 error, 0 note
- `pytest` : tous les tests passent (0 failed)

---

## Règles de code — TOUJOURS respecter

### 1. Optional guards obligatoires
Partout où un attribut peut être None, utiliser une variable locale avant d'appeler dessus :

```python
# CORRECT
event_bus = self.event_bus
if event_bus is None:
    return
await event_bus.subscribe(...)

# INTERDIT — self.event_bus peut être None → AttributeError ou erreur mypy
await self.event_bus.subscribe(...)
```

### 2. Jamais de MetricsCollector
`MetricsCollector` n'existe pas dans ce projet. Ne pas l'inventer.
Utiliser les fonctions directes de `app/utils/metrics.py` :

```python
# CORRECT
from app.utils.metrics import record_tool_execution, record_llm_request
record_tool_execution(agent="file", tool="read", duration=0.1, success=True)

# INTERDIT — MetricsCollector n'existe pas
from app.utils.metrics import MetricsCollector  # ImportError garanti
mc = MetricsCollector()
```

Fonctions disponibles :
- `record_tool_execution(agent, tool, duration, success)`
- `record_llm_request(model, tokens, duration)`
- `start_metrics_server(port)`

### 3. Imports pydantic
Toujours utiliser `from pydantic.v1 import` (compatibilité pydantic v2) :

```python
# CORRECT
from pydantic.v1 import BaseModel, Field, validator

# INTERDIT — casse avec pydantic v2
from pydantic import BaseModel
```

### 4. EventBus.register_source() est async
Dans `__init__` (sync), utiliser `uuid.uuid4()` pour générer un token manuellement.
Dans les méthodes async, toujours `await event_bus.register_source(...)` :

```python
# CORRECT dans __init__
import uuid
self._token = str(uuid.uuid4())

# CORRECT dans une méthode async
self._token = await event_bus.register_source(
    source=self.name,
    publish_channels=["agent.output"],
    subscribe_channels=["agent.input"]
)

# INTERDIT dans __init__
self._token = event_bus.register_source(...)   # ne peut pas await dans __init__
```

### 5. Handlers d'événements
Toujours définir les handlers comme async :

```python
# CORRECT
async def _on_something(self, event: Event) -> None:
    data = event.data
    ...

# INTERDIT — le bus attend un coroutine
def _on_something(self, event: Event) -> None:
    ...
```

### 6. Typage complet
- `Optional[X]` pour tout paramètre avec valeur par défaut `None`
- Type hints sur toutes les méthodes publiques
- Docstrings sur toutes les classes et méthodes publiques

```python
# CORRECT
from typing import Optional

def process(self, text: str, context: Optional[str] = None) -> str:
    """Traite le texte avec contexte optionnel."""
    ...

# INTERDIT — mypy --strict refusera
def process(self, text, context=None):
    ...
```

### 7. Logging
```python
# CORRECT
from ..utils.logger import logger
logger.debug("message de debug")
logger.info("événement notable")
logger.warning("situation anormale non-critique")
logger.error("erreur récupérée")

# INTERDIT — print() pour debug
print("debug:", value)

# INTERDIT — logger.ERROR n'existe pas (c'est une constante, pas une méthode)
logger.ERROR("message")
```

---

## Patterns INTERDITS — liste exhaustive

| Pattern | Pourquoi interdit | Alternative |
|---------|------------------|-------------|
| `import *` | Pollue le namespace, mypy ne peut pas résoudre | Importer explicitement chaque symbole |
| `except: pass` | Masque les vraies erreurs, impossible à déboguer | `except Exception as e: logger.error(...)` |
| `def f(x=[])` | Mutable default partagé entre appels | `def f(x: Optional[list] = None): x = x or []` |
| `global variable` | Rend le code imprévisible | Passer en paramètre ou via attribut d'instance |
| `pickle` | Vecteur d'exécution de code arbitraire | `json`, `msgpack`, ou SQLite |
| `time.sleep()` dans async | Bloque la boucle événementielle entière | `await asyncio.sleep()` |
| `print()` pour debug | Pas de niveau, pas de fichier, pas de timestamp | `logger.debug()` |
| Chemins ou ports hardcodés | Casse sur d'autres machines | Utiliser `Config` ou variables d'environnement |
| Créer des classes inexistantes | `ImportError` garanti au runtime | Vérifier dans le code avant d'importer |
| `bare except` | Attrape même `KeyboardInterrupt` | `except Exception` au minimum |

```python
# TOUS INTERDITS — exemples concrets

from os import *              # import *
try: ...
except: pass                  # bare except + pass

def agent_init(tools=[]):     # mutable default
    ...

global _current_agent         # global keyword

import pickle                 # pickle
pickle.dumps(agent_state)

time.sleep(1.0)               # sleep dans async (bloque le thread)

print("DEBUG:", result)       # print debug

DB_PATH = "/Users/mathieu/db" # chemin hardcodé
PORT = 8765                   # port hardcodé

from app.utils.metrics import MetricsCollector  # classe inexistante
```

---

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

---

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

---

## Warnings non-bloquants connus
- `sentence-transformers non disponible` → concerne uniquement le PromptCache, pas le RAG (qui utilise OllamaEmbedder)
- Port 8000 occupé → instance précédente, faire `pkill -f main_hud` avant relance

---

## Diagnostic rapide

```bash
# Lancer Lucie
PYTHONPATH=. python3 main_hud.py

# Tuer une instance précédente
pkill -f main_hud

# Vérifier qu'Ollama tourne
curl http://localhost:11434/api/tags

# Voir les logs en temps réel
tail -f logs/lucie.log

# Linting
ruff check app/ --fix

# Typage
python -m mypy app/ --ignore-missing-imports --strict

# Tests
PYTHONPATH=. python -m pytest tests/ -x -q
```

---

## Convention de tests

- Tests dans `tests/` avec **structure miroir** de `app/`
  - `app/agents/file_agent.py` → `tests/agents/test_file_agent.py`
- Nommage : `test_<module>.py`, fonctions `test_<comportement>()`
- Chaque nouvelle fonctionnalité = au moins un test associé
- Utiliser `pytest` + `pytest-asyncio` pour les fonctions async
- **Mock Ollama dans les tests** — pas de dépendance réseau dans la CI

```python
# Exemple de test async correct
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_file_agent_read(tmp_path):
    """L'agent lit un fichier existant sans erreur."""
    (tmp_path / "test.txt").write_text("hello")
    with patch("app.providers.provider_manager.ProviderManager") as mock_pm:
        mock_pm.return_value.generate = AsyncMock(return_value="résumé")
        # ... test
```

---

## Hooks Claude Code recommandés

Ajouter dans `.claude/settings.json` pour auto-linting après chaque écriture :

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "command": "ruff check app/ --fix --quiet"
      }
    ]
  }
}
```

---

## Philosophie de développement
Appliquer les lois universelles au code :
- **Moindre action** : fix maximum impact, changements minimaux
- **Homéostasie** : fallbacks partout, le système se stabilise seul
- **Évolution** : adapter sans casser ce qui fonctionne
- **Symbiose** : chaque agent renforce les autres via EventBus
- **Entropie** : réduire le désordre — types stricts, erreurs explicites

---

## Ordre de priorité des tâches
1. **Stabilité** — 0 erreur statique, 0 crash runtime
2. **Connectivité** — tous les agents branchés et communicants
3. **Mémoire** — RAG vectoriel actif (sentence-transformers)
4. **Pipeline** — agents en chaîne automatique
5. **P2P sécurisé** — TLS + authentification mutuelle
6. **Tests** — pytest sur tout le core

---

## Ce qu'il NE FAUT PAS faire
- Ajouter des fonctionnalités avant que la stabilité soit atteinte
- Créer des dépendances circulaires entre agents
- Utiliser pickle pour la sérialisation (sécurité)
- Laisser des TODO sans ticket associé
- Ignorer les erreurs avec un bare `except: pass`
- Refactorer du code non demandé
- Commiter avec des erreurs mypy ou ruff
- Utiliser `print()` au lieu du logger
- Hardcoder des chemins, des ports, ou des URLs
