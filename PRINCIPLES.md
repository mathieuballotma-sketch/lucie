# Principes Beaume

Six principes orientent toutes les décisions techniques et produit
de Beaume. Quand un arbitrage est ambigu, on revient à cette liste.

---

## 1. 100 % local

Les données d'un avocat ne quittent jamais sa machine. Aucun appel
sortant en runtime hors `127.0.0.1:11434` (Ollama local). Aucune
télémétrie. Pas de compte. Pas d'API key utilisateur.

Critère de violation : un seul appel `requests.post()` vers un
domaine externe en code production. Vérifiable par grep.

## 2. Truth rule absolue

Beaume préfère refuser que halluciner. Toute citation Légifrance qui
ne figure pas dans l'index local est rejetée *avant* d'arriver à
l'utilisateur. Toute métrique communiquée publiquement (README,
batterie, sprint) doit être reproductible — voir
[`docs/EVIDENCE.md`](docs/EVIDENCE.md) et
[`docs/REPRODUCE.md`](docs/REPRODUCE.md).

Critère de violation : une affirmation publique sans preuve cliquable
dans le code ou les rapports.

## 3. Architecte silencieux

Pas de marketing. Pas de superlatifs. Pas de pitch "révolutionnaire",
"AI-powered", "next-gen". Les chiffres parlent ; le code parle. La
voix de Beaume est factuelle, mesurable, sobre. Le HUD est silencieux
sauf quand il répond.

Critère de violation : un mot marketing dans un commit message, un
README, un prompt système.

## 4. Transparence radicale

Ce qui est cassé est documenté ([`KNOWN_ISSUES.md`](KNOWN_ISSUES.md)).
Ce qui a changé est daté ([`CHANGELOG.md`](CHANGELOG.md)). Ce qui a
été livré dans un sprint est résumé publiquement
([`docs/sprints/SUMMARY.md`](docs/sprints/SUMMARY.md)).

Ce qui reste **non public** (réserve compétitive) : les détails
diagnostic, les seuils empiriques, les prompts tunés finement, les
modules en stash. Voir [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

Critère de violation : un bug connu non documenté ; une métrique
publique sans méthode de vérification.

## 5. Mémoire adaptative par utilisateur

Aucune Beaume n'est identique. La mémoire (préférences, raccourcis,
contexte cabinet) s'enracine localement, sur la machine de
l'utilisateur. Deux Mac M2 voisins divergent après quelques
semaines d'usage.

Critère de violation : une mémoire partagée cloud, ou un fingerprint
exporté.

## 6. Qualité montre suisse

Précision déterministe **avant** créativité LLM. Le routeur
d'intention, le retriever Légifrance et le Vérificateur sont
déterministes. Le LLM intervient uniquement pour formuler une
réponse à partir de matériel déjà validé.

Le passage par le LLM est traçable : `verifier_score` exposé dans
le HUD, citations cliquables vers l'article exact, audit PAF
exportable.

Critère de violation : un LLM appelé sans gate déterministe en amont,
ou une réponse exposée sans `verifier_score`.

---

## Application au code

| Principe | Composant qui l'applique |
|----------|--------------------------|
| 100 % local | [`lucie_v1_standalone/ollama_client.py`](lucie_v1_standalone/ollama_client.py) — base URL = `127.0.0.1:11434` |
| Truth rule | [`lucie_v1_standalone/verificateur.py`](lucie_v1_standalone/verificateur.py) + [`tests/test_truth_rule_pattern.py`](tests/test_truth_rule_pattern.py) |
| Architecte silencieux | Code review humain, ce fichier comme garde-fou |
| Transparence radicale | [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md), [`CHANGELOG.md`](CHANGELOG.md), [`docs/sprints/SUMMARY.md`](docs/sprints/SUMMARY.md), [`docs/EVIDENCE.md`](docs/EVIDENCE.md), [`docs/REPRODUCE.md`](docs/REPRODUCE.md) |
| Mémoire adaptative | [`lucie_v1_standalone/memory/`](lucie_v1_standalone/memory/) (`personal.py`, `abstract.py`, `store.py`, `sanitizer.py`) |
| Qualité montre suisse | [`lucie_v1_standalone/dialogue/intent_classifier.py`](lucie_v1_standalone/dialogue/intent_classifier.py), [`lucie_v1_standalone/retriever.py`](lucie_v1_standalone/retriever.py), [`lucie_v1_standalone/verificateur.py`](lucie_v1_standalone/verificateur.py) |

---

Mathieu Bellot, 2026-05-12.
