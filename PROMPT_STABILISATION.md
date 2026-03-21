# Prompt de stabilisation Lucie

Copie-colle ce prompt dans Claude Code :

---

Commence par lire CLAUDE.md à la racine du projet. Ce fichier est la référence absolue pour toutes les décisions de code. Lis-le entièrement avant de faire quoi que ce soit.

## Mission : Stabilisation complète de Lucie

Tu dois amener le projet Agent Lucide à un état de stabilité totale : 0 erreur mypy strict, 0 erreur ruff, 0 crash au démarrage, tous les imports valides, tous les tests passent. Voici l'ordre exact des opérations à suivre.

---

## ÉTAPE 0 — Lecture et cartographie

Avant de modifier quoi que ce soit :

1. Lis `CLAUDE.md` entièrement (racine du projet)
2. Liste tous les fichiers Python : `find app/ -name "*.py" | sort`
3. Liste tous les tests existants : `find tests/ -name "*.py" | sort` (le dossier peut être vide ou absent — c'est normal)
4. Lis `main_hud.py` (point d'entrée)
5. Lis `app/core/engine.py` (ou le fichier équivalent — LucidEngine)
6. Lis `app/brain/cortex.py` (FrontalCortex)
7. Lis `app/utils/metrics.py` — note exactement ce qui est exporté
8. Lis `app/utils/errors.py` — note exactement ce qui est exporté
9. Lis `app/utils/circuit_breaker.py`
10. Lis `app/brain/synapses/event_bus.py`

Ne commence pas les corrections avant d'avoir fait cet inventaire.

---

## ÉTAPE 1 — Audit ruff (linting)

Lance :
```bash
ruff check app/ --output-format=grouped 2>&1 | head -200
```

Note tous les fichiers avec des erreurs. Corrige-les dans cet ordre de priorité :
1. `E` (errors) — erreurs de syntaxe et logique
2. `F` (pyflakes) — imports non utilisés, variables non définies
3. `W` (warnings) — problèmes de style
4. `I` (isort) — ordre des imports

Après chaque groupe de corrections, relance `ruff check app/ --fix` pour auto-corriger ce qui peut l'être automatiquement.

Critère de succès : `ruff check app/` retourne 0 erreur.

---

## ÉTAPE 2 — Audit mypy (typage strict)

Lance :
```bash
python -m mypy app/ --ignore-missing-imports --strict 2>&1 | head -300
```

Corrige les erreurs dans cet ordre de priorité :

### 2a. Imports invalides
Toute ligne `error: Module "X" has no attribute "Y"` signifie que tu essaies d'importer quelque chose qui n'existe pas. Pour chaque cas :
- Ouvre le fichier source concerné
- Vérifie ce qui est réellement exporté
- Mets à jour l'import pour ne prendre que ce qui existe

Règle absolue : `MetricsCollector` n'existe pas — remplace toujours par les fonctions directes `record_tool_execution()`, `record_llm_request()`, `start_metrics_server()`.

### 2b. Optional non gardés
Toute ligne `error: Item "None" of "Optional[X]" has no attribute "Y"` :
```python
# AVANT (cassé)
await self.event_bus.subscribe(...)

# APRÈS (correct)
event_bus = self.event_bus
if event_bus is None:
    return
await event_bus.subscribe(...)
```

### 2c. Types manquants
Toute ligne `error: Function is missing a return type annotation` ou `error: Argument ... has incompatible type` :
- Ajoute les type hints manquants
- Utilise `Optional[X]` pour les paramètres qui peuvent être None
- Utilise `from pydantic.v1 import` (jamais `from pydantic import`)

### 2d. Async/sync mismatch
Toute ligne `error: Incompatible return value type` sur des coroutines :
- Les handlers EventBus doivent TOUJOURS être async
- `CircuitBreaker.call()` est synchrone uniquement — ne pas await

Critère de succès : `python -m mypy app/ --ignore-missing-imports --strict` retourne `Success: no issues found`.

---

## ÉTAPE 3 — Vérification des dépendances réelles

Pour chaque agent dans `app/agents/`, vérifie :

```bash
# Pour chaque fichier agent :
python -c "import app.agents.<nom_agent>" 2>&1
```

Si une `ImportError` ou `ModuleNotFoundError` apparaît :
1. Lis le fichier fautif
2. Identifie l'import invalide
3. Vérifie si le module/classe existe vraiment dans le projet
4. Si oui : corrige le chemin d'import
5. Si non : supprime l'import et adapte le code pour ne pas en avoir besoin

---

## ÉTAPE 4 — Test de démarrage

Lance :
```bash
PYTHONPATH=. timeout 10 python3 main_hud.py 2>&1 | head -100
```

(Le timeout évite que le HUD reste ouvert indéfiniment)

Si le démarrage échoue :
- Lis le traceback entièrement
- Identifie le fichier et la ligne exacte de l'erreur
- Lis ce fichier
- Corrige l'erreur
- Recommence

Si le démarrage réussit mais des warnings apparaissent dans les logs :
- `sentence-transformers non disponible` → NON BLOQUANT, ignorer
- `Port 8000 occupé` → lancer `pkill -f main_hud` puis réessayer
- Toute autre `Exception` ou `Error` → à corriger

Critère de succès : le processus démarre sans traceback non attrapé.

---

## ÉTAPE 5 — Vérification de connectivité EventBus

Pour chaque agent qui utilise EventBus, vérifie que :
1. Le token est généré correctement (via `uuid.uuid4()` dans `__init__` ou via `await register_source()` dans `start()`)
2. Les `subscribe()` sont bien `await`és
3. Les `publish()` sont bien `await`és
4. Les handlers sont tous `async def`

Lis `app/brain/cortex.py` et vérifie que chaque agent est bien initialisé et connecté.

---

## ÉTAPE 6 — Création des tests manquants

Si le dossier `tests/` est absent, crée-le :
```bash
mkdir -p tests/agents tests/brain tests/core tests/memory tests/utils
touch tests/__init__.py tests/agents/__init__.py tests/brain/__init__.py
touch tests/core/__init__.py tests/memory/__init__.py tests/utils/__init__.py
```

Crée les tests minimaux suivants (si ils n'existent pas déjà) :

### tests/utils/test_metrics.py
```python
"""Tests pour app/utils/metrics.py"""
import pytest
from app.utils.metrics import record_tool_execution, record_llm_request


def test_record_tool_execution_success():
    """record_tool_execution ne lève pas d'exception."""
    record_tool_execution(agent="test", tool="read", duration=0.1, success=True)


def test_record_tool_execution_failure():
    """record_tool_execution fonctionne même en cas d'échec."""
    record_tool_execution(agent="test", tool="write", duration=0.5, success=False)


def test_record_llm_request():
    """record_llm_request ne lève pas d'exception."""
    record_llm_request(model="llama3", tokens=100, duration=1.2)
```

### tests/utils/test_errors.py
```python
"""Tests pour app/utils/errors.py"""
from app.utils.errors import (
    ToolError, ToolValidationError, ToolExecutionError,
    ToolNotFoundError, AgentNotFoundError
)


def test_tool_error_is_exception():
    assert issubclass(ToolError, Exception)


def test_tool_not_found_error():
    err = ToolNotFoundError("my_tool")
    assert "my_tool" in str(err)


def test_agent_not_found_error():
    err = AgentNotFoundError("my_agent")
    assert "my_agent" in str(err)
```

### tests/brain/test_event_bus.py
```python
"""Tests pour app/brain/synapses/event_bus.py"""
import asyncio
import pytest
from app.brain.synapses.event_bus import EventBus


@pytest.mark.asyncio
async def test_event_bus_register_source():
    """register_source retourne un token non-vide."""
    bus = EventBus()
    token = await bus.register_source(
        source="test_agent",
        publish_channels=["test.out"],
        subscribe_channels=["test.in"]
    )
    assert token is not None
    assert len(str(token)) > 0


@pytest.mark.asyncio
async def test_event_bus_publish_subscribe():
    """Un message publié sur un canal est reçu par le subscriber."""
    bus = EventBus()
    received = []

    async def handler(event):
        received.append(event)

    token = await bus.register_source(
        source="publisher",
        publish_channels=["test.channel"],
        subscribe_channels=[]
    )
    await bus.subscribe(channel="test.channel", handler=handler, source="subscriber", token=token)
    await bus.publish(channel="test.channel", data={"msg": "hello"}, source="publisher", token=token)
    await asyncio.sleep(0.05)
    assert len(received) == 1
    assert received[0].data["msg"] == "hello"
```

Lance les tests :
```bash
PYTHONPATH=. python -m pytest tests/ -x -q 2>&1
```

Corrige tout test qui échoue en lisant le message d'erreur exact.

---

## ÉTAPE 7 — Validation finale complète

Lance les trois checks dans l'ordre :

```bash
echo "=== RUFF ===" && ruff check app/ && echo "OK"
echo "=== MYPY ===" && python -m mypy app/ --ignore-missing-imports --strict && echo "OK"
echo "=== PYTEST ===" && PYTHONPATH=. python -m pytest tests/ -x -q && echo "OK"
```

Si TOUT est OK, passe à l'étape 8.
Si l'un échoue, retourne à l'étape correspondante et recommence.

---

## ÉTAPE 8 — Commit

Commit chaque groupe de corrections séparément avec des messages clairs :

```bash
# Exemple de séquence de commits
git add -p
git commit -m "fix: résoudre les imports invalides dans les agents (mypy)"
git commit -m "fix: ajouter Optional guards sur les attributs EventBus"
git commit -m "fix: corriger les type hints manquants (mypy strict)"
git commit -m "test: ajouter tests unitaires pour utils/metrics et event_bus"
git commit -m "fix: ruff — supprimer imports non utilisés"
```

Ne pas utiliser `git add .` — préférer `git add -p` pour stagier précisément.
Ne pas `--amend` sauf si le commit n'a pas encore été pushé.

Après les commits :
```bash
git log --oneline -10
```

Montre-moi le résultat.

---

## Critères de succès globaux

La stabilisation est terminée quand :
- [ ] `ruff check app/` → 0 erreur
- [ ] `python -m mypy app/ --ignore-missing-imports --strict` → `Success: no issues found`
- [ ] `PYTHONPATH=. python -m pytest tests/ -x -q` → tous les tests passent
- [ ] `PYTHONPATH=. python3 main_hud.py` démarre sans traceback
- [ ] Les logs ne contiennent pas d'Exception non attrapée

Ne déclare pas la mission terminée si l'un de ces critères n'est pas satisfait.

---

## Règles pendant la mission

- Changements minimaux uniquement — pas de refactoring non demandé
- Ne pas ajouter de nouvelles fonctionnalités
- Si un fichier est complexe, le lire entièrement avant de le modifier
- Si un import semble manquer, vérifier dans le code qu'il existe réellement
- Ne pas supprimer de code fonctionnel — seulement corriger ce qui est cassé
- Tout commit doit avoir un message descriptif au format `type: description`

---