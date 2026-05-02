# KNOWN_ISSUES — Lucie V1

Fichier de suivi des problèmes connus, classés par bloc et priorité.
Mis à jour par chaque agent lors de ses découvertes.

---

## v1.0.0 — 2026-05-02

### KI-V1-001 — TTFT content ~18 s sur Gemma4 chain-of-thought
**Statut :** OUVERT (P1, accepté pour v1)
**Priorité :** MOYENNE (post-v1)
**Détecté par :** Sprint Speed-Diag (commit `3368682`), confirmé par audit
archi pré-v1 du 2026-04-30.
**Symptôme :** Le premier token *content* de réponse arrive ~18 s après la
question (cible v1 : ≤ 5 s). Le premier token *thinking* arrive en 1,25 s.
**Cause racine :** Buffering thinking→content **côté serveur Ollama**.
Gemma4 absorbe la chain-of-thought en interne avant de relâcher le content,
hors-portée d'un fix client (httpx `aiter_lines` n'est pas le coupable).
**Mitigation v1 :** Le HUD affiche le « thinking » dès **TTFT 1,25 s** —
l'utilisateur perçoit immédiatement que Lucie travaille (`ollama_client.
generate_stream_chat`, commit `8d96b55`).
**Plan post-v1 :** sprint dédié — évaluer migration `llama-cpp`, compresser
`redacteur_system.txt` (1 180 → < 400 tokens), cache LRU intent répété.
Cf. `PERF_OPTIM_PROGRESS.md` § R5 / R7.

### KI-V1-002 — `test_pipeline_smoke` requiert Ollama actif
**Statut :** ATTENDU (test E2E)
**Priorité :** BASSE
**Détecté par :** `tests/test_legal_pipeline_v1.py::test_pipeline_smoke`
**Symptôme :** Le test timeout après 300 s avec « Lucie prend plus de
temps que prévu » si Ollama n'est pas actif ou n'a pas le modèle chargé.
**Note :** Comportement intentionnel. Le test fait un round-trip complet
contre `localhost:11434`. À skipper en CI sans Ollama. Pas une régression.

### KI-V1-003 — Synchro JudiLibre / Cour de cassation non câblée
**Statut :** OUVERT (post-v1)
**Priorité :** HAUTE (différée)
**Détecté par :** `Rapport_Synchro_Lois_Lucie_2026-04-30.md` §1.2.
**Symptôme :** Le retriever expose un champ `jurisprudences` cosmétique
(filtre par pattern d'ID) mais n'a aucune source amont. Tout arrêt cité
par le LLM serait halluciné — seuls les heuristiques anti-hallucination le
bloquent côté Vérificateur.
**Plan post-v1 :** Module `knowledge_judilibre/` symétrique à
`knowledge_legifrance/`, source API PISTE (`api.piste.gouv.fr/cassation/
judilibre/v1.0`) avec OAuth gratuite, ou exports JuriCA `data.gouv.fr`
mensuels en alternative *zero-auth*.

---

## Bloc 0 — découvertes du corpus exhaustif (2026-04-17)

### KI-001 — Filtre OOS insuffisant pour les questions médico-sociales
**Statut :** OUVERT  
**Priorité :** MOYENNE  
**Détecté par :** runner_exhaustif.py, requête OOS-01  
**Symptôme :** Une question sur le licenciement *pendant* un arrêt maladie
("licencier pendant mon arrêt maladie longue durée") passe le router car le
verbe "licencier" est présent. Le pipeline produit une réponse — honnêtement
limitée ("Aucune source disponible") — mais ne refuse pas poliment.
**Cause racine probable :** `_SEARCH_TRIGGERS` (router.py) est basé sur
des mots-clés. "Licencier" est un trigger fort, mais la co-présence avec
"maladie/arrêt/inaptitude" devrait déclencher un filtre de hors-scope.
**Candidat :** Bloc 1 (refacto router) — ajouter une liste `_OOS_OVERRIDES`
qui annule un trigger si des termes d'exclusion sont présents.

### KI-002 — Lecteur échoue à extraire JSON depuis un document texte simple
**Statut :** OUVERT  
**Priorité :** HAUTE  
**Détecté par :** test_pipeline_smoke (exécuté en Bloc 0)  
**Symptôme :** Lorsque `document_text` contient une lettre de licenciement
en texte brut, le Lecteur retourne "Extraction JSON impossible après retry"
et le pipeline bascule sur un message d'erreur au lieu d'analyser le document.
**Cause racine probable :** Le modèle gemma4:e4b ne produit pas toujours
un JSON valide sur le prompt du Lecteur — manque de robustesse du prompt
ou du parsing de la réponse LLM.
**Candidat :** Bloc 2 (refacto Lecteur) — améliorer le prompt et la logique
de retry/parsing JSON.

### KI-003 — Vérificateur : score vacueux quand aucune citation n'est faite
**Statut :** OUVERT  
**Priorité :** BASSE  
**Détecté par :** runner_exhaustif.py, requête ADV-04  
**Symptôme :** Quand le pipeline répond "Aucune source disponible" sans
citer d'articles, le vérificateur retourne score=1.00 (vacuously true :
0 citation invalide / 0 citation totale = 100%). Ce score peut être
trompeur pour l'utilisateur — un "VALIDÉ 100%" sur un refus.
**Cause racine :** `verificateur.py` calcule `nb_ok / nb_total`. Si
`nb_total == 0`, retourne 1.0 par défaut.
**Candidat :** Bloc 2 (refacto Vérificateur) — distinguer "aucune
citation = non applicable" de "toutes citations valides".

### KI-004 — B2 candidat : vérification de la date d'applicabilité
**Statut :** OUVERT (KNOWN LIMITATION)  
**Priorité :** BASSE (post-pilote)  
**Détecté par :** corpus DATE-01 / DATE-02  
**Symptôme :** Le pipeline ignore les mentions de dates dans la requête
("au 1er janvier 2020 ?" vs "au 1er janvier 2026 ?"). Les deux questions
reçoivent la même réponse basée sur la base curatée actuelle, sans signaler
l'absence de contrôle temporel.  
**Note :** Ce comportement est correct pour la v1 (base curatée statique),
mais il devrait être signalé à l'utilisateur.  
**Candidat :** Bloc 2 — ajouter un avertissement si une date est détectée
dans la requête et que la base n'a pas de marquage temporel.

### KI-005 — Détecteur runner_exhaustif : faux positifs sur ADV-01 et ADV-04
**Statut :** FERMÉ (faux positif du détecteur, pipeline correct)  
**Détecté par :** analyse post-runner  
**Note :** Le détecteur `runner_exhaustif.py` flagge tout texte contenant
"9999" ou "2080", y compris quand le modèle cite ces valeurs pour les
réfuter explicitement. Les réponses des deux requêtes sont correctes :
le pipeline dit explicitement que L.9999-99 et Cass. soc. 2080 n'existent
pas dans la base. Correction à apporter au runner pour Bloc 1 :
utiliser une regex plus précise pour la détection de citation.
