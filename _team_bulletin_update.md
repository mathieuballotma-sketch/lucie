# Bulletin d'équipe — Mise à jour spec Lucie v1
**Date :** 2026-04-10  
**Fichier mis à jour :** `19_Lucie_v1_Aout_2026_Specification.md` (v2.3)  
**Auteur :** Mathieu Bellot

---

## Ce qui a changé (toutes versions du 10 avril 2026)

La spec v1 (architecture orchestrale complexe) a été entièrement réécrite en quatre rounds de simplification le même jour.

---

## Les 5 non-features assumées

| Non-feature | Justification courte |
|---|---|
| Pas d'orchestration multi-agents distribuée | Dev solo, 4 mois, impossible à débugger |
| Pas de multi-LLM thématiques simultanés | Budget RAM incompatible Mac 16 Go client |
| Pas d'audit LLM-sur-LLM | Limite structurelle — ne détecte pas les hallucinations subtiles |
| Pas de recherche web ouverte en runtime | Garantie offline-first — aucun appel réseau pendant une session |
| Pas de bulletin inter-agents | Process séquentiel, journal.md suffit |

---

## Les 5 piliers de l'architecture v2.3

**1. Agents contraints par domaine**  
- 5 composants : Routeur (code), Lecteur (E2B), Retriever (E2B), Rédacteur (E4B), Vérificateur (E2B)
- "Agent" = rôle isolé par prompt système ≤ 300 tokens dans un seul LLM. Clause de refus `out_of_scope`.
- Deux tailles Gemma 4 : E2B pour les rôles courts, E4B pour la rédaction.

**2. Base de connaissances curatée en arbre hiérarchique**  
- Arbre : `~/Lucie/Knowledge/profession/client_type/matière/sous-matière/`
- Le Retriever est un marcheur d'arbre : classifie la requête en tuple, descend dans la feuille, lit 3-5 JSON.
- Refresh quotidien nocturne par script batch séparé (`launchd`). Digest quotidien `YYYY-MM-DD.md`.
- Stratégie v1 : 8-10 intersections couvertes magistralement (PoC initial : `avocat/entreprise/contentieux_social/prudhommes/`)

**3. Garantie offline-first**  
- Aucun agent runtime ne peut déclencher une connexion réseau. Ligne rouge architecturale.
- Arguments commerciaux vrais et défendables : confidentialité, RGPD simplifié, disponibilité sans réseau.

**4. Vérification externe déterministe (Règle 19)**  
- Légifrance API, JuriCA, PCG index local, bandit, semgrep, sandbox Python
- Zones de refus documentées. Aucune affirmation non vérifiée présentée comme vraie.

**5. Couche de réflexion et auto-amélioration des prompts**  
- Notes de réflexion anonymisées par agent après chaque tâche (`~/Lucie/Reflections/`)
- Réflecteur E4B en idle : lit les notes, propose des améliorations, cite des preuves
- Validation humaine obligatoire avant toute modification de prompt (ligne rouge absolue)
- Versioning + rollback des prompts en fichiers séparés (`~/Lucie/Prompts/`)
- Rotation bi-hebdomadaire pour protéger le contexte du Réflecteur

---

## Vérificateurs externes branchés

| Domaine | Vérificateur |
|---|---|
| Textes de loi (juridique) | Légifrance API + base curatée locale |
| Jurisprudence | JuriCA + base curatée locale |
| Comptabilité | PCG + CRC + BOFiP (index local) |
| Code sécurité | bandit + semgrep |
| Code exécution | Sandbox Python isolée |

---

## Décisions en attente avant les jalons

| Décision | Avant quoi |
|---|---|
| Option A vs B chargement modèles (bench hardware) | Jalon 1 |
| Gemma 4 E2B/E4B dispo Ollama stable, ou fallback Qwen3:8B | Jalon 1 |
| 8-10 intersections prioritaires (avec les pilotes) | Jalon 2 |
| Légifrance PISTE API : compte utilisateur ou clé partagée | Jalon 2 |
| Format JSON entrées : fichiers individuels ou SQLite | Jalon 2 |
| Sources transverses : `common/` + index de références vs symlinks Unix | Jalon 2 |
| Schéma journal.md figé | Jalon 2 |
| Classification Retriever : code déterministe vs E2B | Jalon 2 |
| Seuils taux out_of_scope (alerte / blocage) | Jalon 3 |
| Format tests de régression prompts | Jalon 3 |
| Réflecteur peut proposer additions à la base curatée ? | Jalon 3 ou 4 |

---

## Prochaines étapes concrètes

1. **Immédiat :** confirmer disponibilité Gemma 4 E2B + E4B sur Ollama
2. **Immédiat :** vérifier disponibilité gratuite des sources JuriCA/Légifrance pour le PoC prudhommes
3. **Semaine suivante :** bench hardware (latences, RAM, décision Option A/B)
4. **Fin avril :** schéma journal.md + format JSON base curatée + choix des 8-10 intersections avec les pilotes
5. **Mai :** Jalon 1 — Routeur + HUD + bench

---

_Bulletin mis à jour le 2026-04-10 — document de référence : `19_Lucie_v1_Aout_2026_Specification.md` v2.3_
