# Proposition : Intégration de la Philosophie du Terrain dans l'Architecture V1

**Date :** 12 avril 2026  
**Statut :** Proposition à discuter — rien n'est implémenté

---

## Ce que j'ai compris de la philosophie

La philosophie du terrain dit : chaque interaction avec Lucie doit laisser le terrain plus riche qu'avant. Trois niveaux : consommation (interdit), observation (insuffisant), capitalisation (objectif). Chaque agent doit avoir trois couches : réactive, capitalisante, générative.

## Comment ça se mappe sur l'architecture V1 actuelle

L'archi V1 a 5 agents contraints (Router déterministe, Search E2B, Lecteur E2B, Rédacteur E4B, Vérificateur E2B) qui communiquent via un journal client en markdown. C'est déjà une base pour la capitalisation — le journal est la trace. Mais aujourd'hui le journal est un log (niveau 2). La philosophie demande qu'il devienne un outil d'apprentissage (niveau 3).

---

## Propositions concrètes par agent

### Router (code déterministe)

**Couche réactive (déjà prévue) :** Analyse l'intention, dispatch vers le bon agent.

**Couche capitalisante (à ajouter) :** Après chaque dispatch, le Router écrit dans le journal une entrée structurée :
```
[PATTERN] type_dossier=licenciement_eco | intention=vérifier_article | chemin=Search→Lecteur→Rédacteur | durée=12s
```
Après N interactions sur le même type de dossier, le Router a une table de fréquences des chemins empruntés. C'est exactement le **path compression** prévu dans la vision — mais implémenté de manière triviale (compteur dans un JSON) au lieu de nécessiter du ML.

**Couche générative (stretch V1) :** Quand le Router voit que l'avocat ouvre un nouveau dossier licenciement économique, il peut proposer : "Sur vos 5 derniers dossiers similaires, vous avez toujours vérifié L.1233-3 en premier. Voulez-vous que je commence par là ?" Ça demande juste de lire les patterns accumulés.

---

### Search / Retriever (E2B)

**Couche réactive :** Descend dans l'arbre de la base curatée, retourne 3-5 sources.

**Couche capitalisante :** Après chaque recherche, écrit :
```
[CHEMIN_EFFICACE] requête="obligations PSE" → match=knowledge/avocat/entreprise/contentieux_social/licenciement_economique/L1233-8.md | pertinence=haute
[LACUNE] requête="indemnité supra-légale licenciement" → aucun match dans la base curatée
```
Les chemins efficaces permettent un fast-path la prochaine fois (lookup direct au lieu de parcourir l'arbre). Les lacunes alimentent le pipeline de refresh pour combler les trous.

**Couche générative :** Quand une lacune revient 3 fois, le Search la signale proactivement : "Cette source manque dans votre base et revient souvent. Voulez-vous que je la récupère au prochain refresh ?"

---

### Lecteur (E2B)

**Couche réactive :** Lit le document client, extrait les faits clés.

**Couche capitalisante :** Après lecture, écrit dans le journal :
```
[PROFIL_CLIENT] entité=SARL Dupont | secteur=BTP | effectif=45 | convention=Bâtiment | points_sensibles=2_CDD_requalifiables
```
Ce profil client s'enrichit à chaque nouveau document lu. Après 3 documents, Lucie "connaît" le client.

**Couche générative :** Après avoir lu une lettre de licenciement, le Lecteur peut dire : "Ce document mentionne un motif économique mais ne cite pas l'obligation de reclassement (L.1233-4). C'est souvent un point d'attaque en contentieux." Il ne rédige pas (hors scope), mais il signale.

---

### Rédacteur (E4B)

**Couche réactive :** Rédige la note structurée à partir des sources fournies.

**Couche capitalisante :** Après rédaction, écrit :
```
[TEMPLATE_APPRIS] type=note_licenciement_eco | structure=contexte→base_légale→jurisprudence→analyse→recommandation | sources_utilisées=5 | longueur=2pages
```
Au bout de 5 notes similaires, le Rédacteur a un template implicite pour ce type de livrable. La prochaine note démarre avec une structure éprouvée au lieu de repartir de zéro.

**Couche générative :** "Sur vos précédentes notes de ce type, vous ajoutiez systématiquement une section 'risques pour l'employeur'. Voulez-vous que je l'ajoute ?"

---

### Vérificateur (E2B)

**Couche réactive :** Compare le texte rédigé aux sources, flagge les divergences.

**Couche capitalisante :** Après vérification, écrit :
```
[ERREUR_RÉCURRENTE] type=article_mal_cité | détail=L.1233-3 confondu avec L.1233-4 | fréquence=2/5_dernières_notes
```
Les patterns d'erreurs permettent au Vérificateur de devenir plus vigilant sur les points faibles récurrents.

**Couche générative :** Avant même que le Rédacteur livre, le Vérificateur peut pré-charger les vérifications probables basées sur le type de dossier : "Pour un licenciement économique, je vais vérifier en priorité : motif économique réel (L.1233-3), obligation de reclassement (L.1233-4), ordre des licenciements (L.1233-5), PSE si >10 salariés (L.1233-61)."

---

## Le journal comme terrain (pas comme log)

Aujourd'hui le journal est prévu comme un fichier markdown humainement lisible. La philosophie ne change pas ça — mais elle demande qu'on ajoute des **entrées structurées** (les blocs `[PATTERN]`, `[CHEMIN_EFFICACE]`, `[LACUNE]`, etc.) que le Router peut parser pour prendre de meilleures décisions.

**Format proposé :** Le journal reste markdown lisible, mais avec des blocs machine-parseable en code fences :

```markdown
## 2026-07-15 — Dossier SARL Dupont, licenciement économique

### Lecteur
Lu : lettre_licenciement_dupont.pdf
Faits extraits : motif économique invoqué (baisse CA 30%), 3 salariés concernés, pas de PSE mentionné

```meta
[PROFIL_CLIENT] entité=SARL_Dupont | effectif=45 | secteur=BTP
[SIGNAL] pas_de_PSE_mentionné_pour_effectif>10 → probable_obligation_L1233-61
```

### Search
Sources retournées : L.1233-3, L.1233-4, L.1233-5, Cass. soc. 2024-xxx

```meta
[CHEMIN_EFFICACE] licenciement_eco+motif → L1233-3.md (pertinence=haute)
[LACUNE] jurisprudence_récente_reclassement_2025 → absent
```
```

L'humain lit le markdown. Le Router lit les blocs `meta`.

---

## Ce qui est réaliste pour la démo V1 (fin juillet 2026)

| Couche | Faisabilité V1 | Effort |
|--------|----------------|--------|
| Réactive | ✅ Déjà dans le plan | 0 (c'est le plan actuel) |
| Capitalisante | ✅ Faisable | Moyen — ajouter les entrées structurées au journal + parser dans le Router |
| Générative | ⚠️ Stretch goal | Élevé — demande assez d'interactions accumulées pour être pertinent |

**Ma recommandation :** Implémenter les couches réactive + capitalisante pour la démo. La couche générative peut être montrée en "teaser" si on a assez de données d'exemple pré-remplies dans un dossier de démo.

---

## Ce que la philosophie NE change PAS dans l'archi V1

- Mono-process (pas de multi-processus)
- 2 tailles Gemma 4 (E2B/E4B)
- Agents = rôles contraints par prompt + refus hors scope
- Journal markdown comme mémoire partagée
- Base curatée locale comme source de vérité
- Router déterministe (code, pas LLM)

La philosophie s'intègre DANS cette architecture, elle ne la remplace pas. Elle ajoute une discipline : chaque agent écrit quelque chose d'utile pour le futur, pas juste pour le présent.

---

## Question ouverte pour toi

Le document mentionne SQLite pour les deltas appris. Pour V1, je propose de rester en markdown structuré (cohérent avec le journal humainement lisible). SQLite viendrait en V2 quand le volume de patterns justifie une vraie base de données. Qu'est-ce que tu en penses ?

---

*Proposition — pas de code touché. À discuter avant toute implémentation.*
