# Bulletin d'équipe — Mise à jour spec Lucie v1
**Date :** 2026-04-10  
**Fichier mis à jour :** `19_Lucie_v1_Aout_2026_Specification.md` (v2.2)  
**Auteur :** Mathieu Bellot

---

## Ce qui a changé

La spec v1 (architecture orchestrale complexe) a été entièrement réécrite. La v2.2 reflète l'architecture réelle simplifiée décidée après audit externe critique.

---

## Les 5 non-features assumées

| Non-feature | Justification courte |
|---|---|
| Pas d'orchestration multi-agents distribuée | Dev solo, 4 mois, impossible à débugger |
| Pas de multi-LLM thématiques simultanés | Budget RAM incompatible Mac 16 Go client |
| Pas d'audit LLM-sur-LLM | Limite structurelle — ne détecte pas les hallucinations subtiles |
| Pas de recherche web ouverte en runtime | Latence imprévisible, mode offline impossible, vecteur d'hallucination |
| Pas de bulletin inter-agents | Process séquentiel, journal.md suffit |

---

## Les 4 piliers de l'architecture v2.2

**1. Agents contraints par domaine**  
- 5 composants : Routeur (code), Lecteur (E2B), Retriever (E2B), Rédacteur (E4B), Vérificateur (E2B)
- Chaque agent a un prompt système ≤ 300 tokens, un domaine strict, une clause de refus `out_of_scope`
- "Agent" dans Lucie v1 = rôle isolé par prompt dans un seul LLM. Pas un processus séparé.

**2. Base de connaissances curatée pré-indexée**  
- `~/Lucie/Knowledge/avocat/` et `~/Lucie/Knowledge/comptable/`
- Quelques milliers d'entrées JSON par profession (Légifrance, JuriCA, PCG, BOFiP, CRC, URSSAF)
- Le Retriever fait un lookup déterministe local — pas d'exploration web en runtime
- Mise à jour hebdomadaire par script batch séparé (launchd, dimanche soir)
- Premier moat durable : quelques semaines de travail pour construire, valeur cumulative

**3. Vérification externe déterministe (Règle 19)**  
- Vérificateurs branchés : Légifrance API, JuriCA, PCG index local, bandit, semgrep, sandbox Python
- Aucune affirmation factuelle présentée sans vérification
- Zones de refus documentées (source indisponible, hors périmètre, jurisprudence non vérifiable)

**4. Couche de réflexion et auto-amélioration des prompts**  
- Chaque agent écrit des notes de réflexion anonymisées après chaque tâche
- Le Réflecteur (E4B en période d'inactivité) lit les notes et propose des améliorations de prompt
- Les propositions exigent des preuves citées — sans preuves = rejet automatique
- Validation humaine obligatoire avant toute modification de prompt (ligne rouge absolue)
- Versioning + rollback des prompts en fichiers séparés
- Rotation bi-hebdomadaire pour protéger le contexte du Réflecteur

---

## Décisions en attente (à trancher avant les jalons respectifs)

| Décision | Avant quoi |
|---|---|
| Option A (2 modèles en permanence, M2 16 Go) vs Option B (swap, M2 8 Go) | Jalon 1 |
| Gemma 4 E2B/E4B disponible sur Ollama en build stable, ou fallback Qwen3:8B | Jalon 1 |
| Légifrance PISTE API : compte utilisateur ou clé partagée Lucie | Jalon 2 |
| Format JSON entrées base curatée : fichiers individuels ou SQLite | Jalon 2 |
| Schéma journal.md figé (sections obligatoires, format entrées agents) | Jalon 2 |
| Seuils d'alerte taux out_of_scope (alerte : 15% ?, blocage adoption : 30% ?) | Jalon 3 |
| Format tests de régression prompts : Markdown subjectif ou script Python | Jalon 3 |
| Réflecteur peut-il proposer des additions à la base curatée ? | Jalon 3 ou 4 |

---

## Prochaines étapes concrètes

1. **Immédiat :** confirmer disponibilité Gemma 4 E2B + E4B sur Ollama
2. **Semaine suivante :** bench hardware (latences, RAM, décision Option A/B)
3. **Fin avril :** définir schéma journal.md + format JSON base curatée
4. **Mai :** Jalon 1 — Routeur + HUD + bench

---

_Bulletin écrit le 2026-04-10 — document de référence : `19_Lucie_v1_Aout_2026_Specification.md` v2.2_
