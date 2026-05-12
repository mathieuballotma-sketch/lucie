# Tests Beaume

Tests unitaires et d'intégration pour le pipeline Beaume.

## Lancer les tests

### Tous les tests (rapide, sans Ollama)

```bash
pytest tests/ -v --ignore=tests/integration --ignore=tests/llm
```

Couvre : routeur d'intention, vérificateur, retriever, sanitizer mémoire,
parsers, env legacy compat. ~5 secondes sur Mac M1.

### Suite complète (avec Ollama)

```bash
# Prérequis : ollama serve + ollama pull gemma2:9b
pytest tests/ -v
```

Inclut les tests LLM (`tests/llm/`) et l'intégration end-to-end
(`tests/integration/`). ~2-3 minutes selon le matériel.

### Test unique

```bash
pytest tests/test_truth_rule_pattern.py -v
pytest tests/security/ -v
```

## Structure

| Dossier | Couverture |
|---------|------------|
| `tests/agents/` | Agents et workers du pipeline |
| `tests/core/` | Cœur déterministe : routeur, classification, gates |
| `tests/dialogue/` | Dialogue, refus contextuel, intent classifier |
| `tests/integration/` | Bout-en-bout pipeline → Ollama → réponse |
| `tests/llm/` | Tests qui nécessitent un LLM Ollama actif |
| `tests/memory/` | Mémoire adaptative, sanitizer PII |
| `tests/security/` | Détection PII, sandbox, exfiltration |
| `tests/services/` | Services internes (cache, profiling) |
| `tests/test_legifrance/` | Knowledge base : retriever, indexer |
| `tests/ui/` | HUD, badge `verifier_score`, popover mémoire |
| `tests/utils/` | Utilitaires (env_legacy, paths, etc.) |

Tests racine : `test_truth_rule_pattern.py`, `test_pipeline_a_smoke.py`,
`test_env_legacy_compat.py`, `test_warmup.py`,
`test_pipeline_response_score.py`.

## Convention

- Fichier `test_<module>.py` pour un module donné, sauf si plusieurs
  aspects justifient un fichier dédié.
- Pas de mock du Vérificateur ni du retriever déterministe — ce sont
  les composants vérité. Mocker un Vérificateur reviendrait à invalider
  la truth rule (cf [`PRINCIPLES.md`](../PRINCIPLES.md)).
- Mocker uniquement les appels Ollama réseau dans les tests `*_smoke.py`.

## Configuration

Pytest est configuré via [`conftest.py`](../conftest.py) à la racine
(fixtures partagées) et [`pyproject.toml`](../pyproject.toml) (section
`[tool.pytest.ini_options]` si présente).

Si vous ajoutez un test qui requiert une variable d'environnement,
documentez-la ici et dans le test lui-même.
