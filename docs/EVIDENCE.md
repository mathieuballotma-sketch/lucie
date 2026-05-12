# Evidence — mapping claim → preuve → vérification

Chaque affirmation que le README fait sur Beaume doit pointer ici vers
une preuve cliquable dans le code, et vers une méthode de vérification
reproductible.

Si une affirmation du README n'a pas de ligne dans ce fichier, elle
doit être retirée du README. **Truth rule.**

---

## Architecture

| Affirmation README | Preuve dans le code | Vérification |
|---|---|---|
| Pipeline 100 % local (Ollama localhost) | [`lucie_v1_standalone/ollama_client.py`](../lucie_v1_standalone/ollama_client.py) | `grep -r "localhost\|127.0.0.1" lucie_v1_standalone/` |
| Cerveau Oiseaux — routeur déterministe (intent classifier + bornes) | [`lucie_v1_standalone/dialogue/intent_classifier.py`](../lucie_v1_standalone/dialogue/intent_classifier.py), [`lucie_v1_standalone/dialogue/`](../lucie_v1_standalone/dialogue/) | `pytest lucie_v1_standalone/tests/test_dialogue/test_intent_classifier.py -v` |
| Cerveau Humain — formulation LLM | [`lucie_v1_standalone/ollama_client.py`](../lucie_v1_standalone/ollama_client.py), [`lucie_v1_standalone/prompts/`](../lucie_v1_standalone/prompts/) | `cat lucie_v1_standalone/prompts/redacteur_search_system.txt` |
| Vérificateur déterministe (truth rule) — refuse les citations hors KB | [`lucie_v1_standalone/verificateur.py`](../lucie_v1_standalone/verificateur.py), [`lucie_v1_standalone/prompts/verificateur_system.txt`](../lucie_v1_standalone/prompts/verificateur_system.txt) | `pytest tests/test_truth_rule_pattern.py -v` |
| Retriever KB Légifrance | [`lucie_v1_standalone/retriever.py`](../lucie_v1_standalone/retriever.py), [`lucie_v1_standalone/knowledge_legifrance/retriever.py`](../lucie_v1_standalone/knowledge_legifrance/retriever.py) | `pytest tests/test_legifrance/ -v` (nécessite l'index local) |
| Mémoire adaptative par utilisateur | [`lucie_v1_standalone/memory/`](../lucie_v1_standalone/memory/) (`personal.py`, `abstract.py`, `store.py`, `sanitizer.py`) | `pytest tests/memory/test_memory_store.py -v` |

## Mesures de fiabilité

| Affirmation README | Preuve | Vérification |
|---|---|---|
| **62,5 %** sur batterie 16q multi-angles (2026-05-12) | [`bench/results/2026-05-12_battery_16q_post_p2a.md`](../bench/results/2026-05-12_battery_16q_post_p2a.md) | `BEAUME_RETRIEVER_DEBRIDE=1 BEAUME_VERIFICATEUR_NORMALISE=1 python3 bench/run_legal_traps.py --prompts bench/swiss_watch_50.json --filter SW-LECO --json /tmp/run.json` |
| Batterie 50q — **mesure clean en cours** | [`bench/results/2026-05-12_battery_50q_post_p2a.md`](../bench/results/2026-05-12_battery_50q_post_p2a.md) | À publier dès stabilisation. Pas de chiffre cité tant que le run clean n'est pas livré. |
| Seuil `verifier_score ≥ 0.70` calibré sur citations dédupliquées | [`bench/CHANGELOG.md`](../bench/CHANGELOG.md), [`bench/swiss_watch_50.json`](../bench/swiss_watch_50.json) (`pass_criteria.verifier_score_min`) | `grep -A2 verifier_score_min bench/swiss_watch_50.json \| head -30` |
| Tests : 23 fichiers `test_*.py`, ~132 tests unitaires | [`tests/`](../tests/) | `pytest tests/ --collect-only -q \| tail -5` |
| Truth rule appliquée architecturalement (refus avant LLM) | [`lucie_v1_standalone/verificateur.py`](../lucie_v1_standalone/verificateur.py) + [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) section "Truth enforcement" | Lecture directe + `tests/test_truth_rule_pattern.py` |

## Stack runtime

| Affirmation README | Preuve | Vérification |
|---|---|---|
| Gemma 4 e4b via Ollama | [`lucie_v1_standalone/config.py`](../lucie_v1_standalone/config.py) (`SPEED_MODEL`) | `grep -i "gemma\|model" lucie_v1_standalone/config.py` |
| HUD natif macOS via PyObjC | [`app/ui/hud_native.py`](../app/ui/hud_native.py) | `head -50 app/ui/hud_native.py` (imports PyObjC) |
| KB Légifrance SQLite indexé (FTS5) | [`lucie_v1_standalone/knowledge_legifrance/`](../lucie_v1_standalone/knowledge_legifrance/) | `cat lucie_v1_standalone/knowledge_legifrance/schema.sql` |
| Aucun appel cloud sortant en runtime | [`lucie_v1_standalone/ollama_client.py`](../lucie_v1_standalone/ollama_client.py) (base URL `http://127.0.0.1:11434`) | `grep -rE "https?://" lucie_v1_standalone/ --include='*.py' \| grep -v localhost \| grep -v 127.0.0.1` (résultat attendu : vide ou uniquement docstrings) |

## Sprint history (audit trail)

| Affirmation README | Preuve | Vérification |
|---|---|---|
| Sprint 6 P1 — Cerveau intelligent | [`docs/sprints/2026-05-08_sprint_6_p1_cerveau_intelligent.md`](sprints/2026-05-08_sprint_6_p1_cerveau_intelligent.md) | Lecture + `git log --grep="P1"` |
| Sprint 6 P1b — Refus contextuel `lic_perso` | [`docs/sprints/2026-05-08_sprint_6_p1b_refus_contextuel.md`](sprints/2026-05-08_sprint_6_p1b_refus_contextuel.md) | Lecture + `git log --grep="P1b"` |
| Sprint 6 P2a — Retriever débridé + Vérificateur normalisé | [`docs/sprints/2026-05-12_sprint_6_p2a_retriever_verificateur.md`](sprints/2026-05-12_sprint_6_p2a_retriever_verificateur.md) | Lecture + `git log --grep="P2a"` |

## Comment ajouter une affirmation au README

1. Identifier le claim à ajouter dans le README.
2. Identifier le fichier / la commande qui le prouve.
3. **Ajouter une ligne dans ce fichier d'abord.**
4. Citer le claim dans le README en pointant vers `docs/EVIDENCE.md#...` ou directement vers la preuve.

Si l'étape 2 échoue (pas de preuve), ne pas écrire le claim. C'est la
règle.
