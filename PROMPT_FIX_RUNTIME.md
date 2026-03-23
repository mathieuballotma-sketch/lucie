# Prompt de réparation runtime — Lucie

Lis CLAUDE.md avant de commencer. Corrige ces bugs dans l'ordre exact. Valide après chaque fix avec `ruff check app/ && python3 -m mypy app/ --ignore-missing-imports --strict`.

---

## FIX 1 — CRITIQUE : Rendre les appels LLM non-bloquants

### Problème
`ExecutionEngine.call_llm()` dans `app/brain/cortex.py:1053` est synchrone. Quand appelé depuis `think()` (async), il bloque la boucle asyncio pendant 10-15s, empêchant les timeouts de fonctionner.

### Fix
Transformer `call_llm` en coroutine async et wrapper `manager.generate()` dans `run_in_executor`.

**Fichier** : `app/brain/cortex.py`

**Ancien code** (ligne ~1053) :
```python
def call_llm(self, query: str, model_profile: str) -> str:
    model_name = self.model_mapping.get(model_profile)
    enriched = self._enrich_query(query)
    ...
    def _generate() -> str:
        ...
        return self.manager.generate(...)

    try:
        response: str = (
            self.llm_circuit_breaker.call(_generate)
            if self.llm_circuit_breaker is not None
            else _generate()
        )
    ...
```

**Nouveau code** :
```python
async def call_llm(self, query: str, model_profile: str) -> str:
    model_name = self.model_mapping.get(model_profile)
    enriched = self._enrich_query(query)
    ...
    def _generate() -> str:
        ...
        return self.manager.generate(...)

    loop = asyncio.get_running_loop()
    try:
        response: str = await loop.run_in_executor(
            None,
            lambda: (
                self.llm_circuit_breaker.call(_generate)
                if self.llm_circuit_breaker is not None
                else _generate()
            ),
        )
    ...
```

**AUSSI** : `execute_semantic_parsing` (ligne ~993) est aussi sync — le rendre async avec `run_in_executor`.

### Validation
```bash
ruff check app/ && python3 -m mypy app/ --ignore-missing-imports --strict
```

---

## FIX 2 — HAUTE : Augmenter le timeout interne

### Problème
`effective_timeout = 15.0` est trop court pour un LLM local (10-12s de génération seule).

**Fichier** : `app/core/engine.py`

**Lignes** ~659 et ~696 :
```python
# Ancien
effective_timeout = 60 if self._is_multi_step(query) else 15

# Nouveau
effective_timeout = 120 if self._is_multi_step(query) else 45
```

Appliquer dans `process()` ET `process_async()`.

---

## FIX 3 — MOYENNE : Corriger le formatage logger

**Fichier** : `app/core/engine.py`

**Ligne ~674** :
```python
# Ancien
logger.debug("engine.process_latency", latency)
# Nouveau
logger.debug(f"engine.process_latency: {latency:.3f}")
```

**Ligne ~714** :
```python
# Ancien
logger.debug("engine.process_async_latency", latency)
# Nouveau
logger.debug(f"engine.process_async_latency: {latency:.3f}")
```

---

## FIX 4 — HAUTE : Les lambdas LLM ne sont pas détectées comme async

Les lambdas `lambda q: executor.call_llm(q, "speed")` wrappant une coroutine retournent un awaitable, mais `asyncio.iscoroutinefunction` retourne False pour les lambdas.

**Fix dans `think()`** (cortex.py, ligne ~1390) :
```python
# Ancien
if asyncio.iscoroutinefunction(path_func):
    response = await path_func(user_query.text)
else:
    response = path_func(user_query.text)

# Nouveau
result = path_func(user_query.text)
if asyncio.iscoroutine(result):
    response = await result
else:
    response = result
```

---

## Validation finale

Après tous les fixes :
```bash
ruff check app/ --fix
python3 -m mypy app/ --ignore-missing-imports --strict
PYTHONPATH=. python3 -m pytest tests/ -x -q
PYTHONPATH=. python3 test_real_usage.py 2>&1 | tee logs/test_rerun.log
```

Critère de succès : >70% des requêtes retournent une réponse utile (pas "requête trop longue").
