# Lucie v1 — Spécification technique
## Cible : Août 2026

**Version** : 2.3 — offline-first + arbre hiérarchique + refresh quotidien + stratégie étroite-profonde  
**Date de mise à jour** : 2026-04-10  
**Auteur** : Mathieu Bellot  
**Statut** : Spécification de travail — à tenir à jour jusqu'au lancement  

> **Note de version.** La v1.x décrivait une architecture multi-agents avec orchestration complexe, 7 modèles simultanés, 29 agents en RAM. Un audit externe a montré que c'était infaisable pour un dev solo à horizon 4 mois. La v2.0 a simplifié radicalement. La v2.1 : agents contraints + deux tailles Gemma 4. La v2.2 : base curatée + couche réflexion. La v2.3 acte la garantie offline-first, bascule le refresh quotidien, restructure la base en arbre hiérarchique sémantique, et adopte la stratégie "étroite et profonde" (8-10 intersections magistrales plutôt que 40 superficielles) comme décision explicite de tenue du jalon août 2026.

---

## 1. Ce que Lucie v1 EST

**Un seul processus.** Application macOS native (PyObjC), un unique processus Python. Pas de microservices, pas de workers séparés, pas de coordination inter-process.

**Deux tailles de modèle Gemma 4, exécutées séquentiellement.** E2B (~2-3 Go) pour les rôles courts (Lecteur, Retriever, Vérificateur). E4B (~4-5 Go) pour les rôles longs (Rédacteur). Un seul modèle actif à la fois — pas du multi-LLM parallèle. Voir §7 pour les options de chargement.

**Un routeur déterministe en code.** Classification de l'intention par regex, dictionnaire de mots-clés, fuzzy matching. Aucun LLM n'intervient dans le routage. Traçable en une ligne de log.

**Des agents contraints par domaine avec clause de refus.** Chaque agent a un prompt système court (≤ 300 tokens), un domaine défini, et retourne `out_of_scope` si la requête sort de ce domaine. Le routeur est le seul à décider quel agent appeler.

**Une base de connaissances curatée pré-indexée, locale, structurée en arbre hiérarchique.** Au lieu de faire chercher le LLM dans le vide, Lucie lui sert directement des sources officielles pré-sélectionnées et pré-fetchées. Le LLM passe de "explorer + synthétiser" à "synthétiser seulement". La base est organisée en arbre `profession / type_client / matière / sous-matière` — le Retriever descend dans la feuille correspondante et remonte les sources. Mise à jour quotidienne par script batch séparé.

**Une garantie offline-first.** Entre le lancement de Lucie et la livraison d'un livrable, aucun appel réseau n'est requis. La seule connexion sortante autorisée est le refresh nocturne de la base. Cette garantie est architecturalement vraie et commercialement différenciante.

**Une vérification externe déterministe obligatoire (Règle 19).** Toute affirmation factuelle dans un livrable est confrontée à une source externe avant d'être montrée à l'utilisateur. Voir §9.

**Un journal humainement lisible par dossier client.** `~/Lucie/Dossiers/{Client}/journal.md` — Markdown, append-only, seule mémoire partagée entre agents.

**Un outil pour professionnels réglementés.** Avocats (droit des affaires, contentieux commercial) et experts-comptables (bilans, liasses, veille fiscale).

---

## 2. Ce que Lucie v1 N'EST PAS

**1. Pas d'orchestration multi-agents au sens distribué.**  
Pas de processus séparés, pas de workers parallèles, pas de PlannerAgent qui dispatche vers des sub-agents concurrents. Les agents de Lucie v1 sont séquentiels dans un seul process — volontairement.  
_Pourquoi_ : un dev solo ne peut pas débugger un système distribué en 4 mois. Chaque couche de coordination supplémentaire double le temps de diagnostic.

**2. Pas de multi-LLM spécialisés thématiques simultanés.**  
Pas de modèle séparé pour le droit, la comptabilité, le code — actifs en même temps en RAM.  
_Pourquoi_ : budget RAM incompatible avec Mac 16 Go client. Deux tailles du même modèle couvrent tous les rôles v1 (voir §7).

**3. Pas d'audit LLM-sur-LLM comme garde-fou principal.**  
Le Vérificateur ne "juge" pas le Rédacteur via un LLM. Il compare le texte à des sources déterministes.  
_Pourquoi_ : un LLM ne détecte pas les hallucinations d'un LLM du même modèle avec les mêmes biais — il valide les mêmes erreurs. Limite structurelle, pas corrigible par prompt.

**4. Pas de recherche web en ligne pendant l'exécution normale.**  
L'Agent Retriever travaille exclusivement sur l'index local. La mise à jour de l'index est un script batch quotidien séparé, jamais une opération runtime.  
_Pourquoi_ : garantie offline-first — aucun appel réseau n'est requis pendant une session utilisateur. La latence réseau est imprévisible, le mode offline doit fonctionner intégralement, et l'exploration web ouverte est le principal vecteur d'hallucination.

**5. Pas de bulletin inter-agents comme mémoire distribuée.**  
Le journal par dossier (journal.md) est la seule mémoire partagée. Les agents ne communiquent pas entre eux directement.  
_Pourquoi_ : dans un process séquentiel, un bulletin distribué est de la complexité sans bénéfice.

---

## 3. Définition d'un agent dans Lucie v1

**Un agent Lucie v1 est :**
- un prompt système court et restrictif (≤ 300 tokens)
- assigné à un modèle précis (E2B ou E4B)
- invoqué de façon synchrone par le routeur
- contraint à un domaine de sortie défini
- équipé d'une clause de refus : si la requête sort du domaine → `{"status": "out_of_scope", "reason": "..."}`

**Un agent Lucie v1 n'est PAS :**
- un processus séparé
- une entité avec une mémoire propre
- un orchestrateur d'autres agents
- un juge de la qualité d'un autre agent

Cette définition est délibérément restrictive. Si pendant l'implémentation quelqu'un propose d'ajouter une "mémoire longue par agent" ou un "canal de communication inter-agents", la réponse est non — ce n'est pas ce que "agent" désigne ici.

---

## 4. Base de connaissances curatée

### 4.1 Principe

Le principal levier de vitesse et de précision de Lucie v1 n'est pas le LLM — c'est les données servies au LLM avant qu'il génère.

Sans base curatée : le LLM explore, navigue dans le flou, invente des références plausibles. ~30-50% du budget tokens brûlé en exploration, ~50-70% en synthèse utile.

Avec base curatée : l'exploration est remplacée par un lookup déterministe dans un index local. ~5% du budget tokens en classification de requête, ~95% en synthèse sur des sources réelles déjà présentes dans le contexte.

> **Note honnête :** ces ratios sont des estimations raisonnées. La traduction en latence perçue (de ~8-10s à ~2-3s de génération sur une rédaction type) sera confirmée par benchmark une fois la base construite. Ne pas les présenter à l'utilisateur comme des engagements.

### 4.2 Structure de stockage — arbre hiérarchique sémantique

La base n'est pas une table plate. C'est un arbre indexé par `profession / type_client / matière / sous-matière`. Les **feuilles** contiennent les fichiers JSON. Les **nœuds intermédiaires** contiennent uniquement un `README.md` décrivant le périmètre couvert. **On ne crée un dossier que s'il a du vrai contenu** — pas de coquilles vides.

```
~/Lucie/Knowledge/
    avocat/
        entreprise/
            litige_commercial/
                rupture_brutale_relations/   ← feuille : fichiers JSON
                bail_commercial/             ← feuille
                concurrence_deloyale/        ← feuille
            contentieux_social/
                prudhommes/                  ← feuille — PoC v1 initial
                licenciement_economique/     ← feuille
                rupture_conventionnelle/     ← feuille
            penal_affaires/
        particulier/
            famille/
                divorce/
                succession/
                autorite_parentale/
            immobilier/
            consommation/
        association/
        collectivite/

    comptable/
        tpe_pme/
            bilan_comptable/                 ← feuille
            tva/                             ← feuille
            is_bic/                          ← feuille
        profession_liberale/
        association/

    common/
        articles_codes/    # sources transverses référencées par plusieurs feuilles
        # (art. 1240 Code civil, L.1225-4 Code du travail, etc.)

    digests/               # rapports quotidiens de mise à jour
        YYYY-MM-DD.md
```

**Principe de sélectivité :** Lucie a accès à toute la base, mais le Retriever ne consulte que la feuille correspondant à la situation spécifique du client. Un dossier de prudhommes ne consulte pas les sources en bail commercial — même si les deux sont dans la base. C'est à la fois un argument commercial (largeur) et une garantie opérationnelle (précision).

<!-- À TRANCHER: sources transverses — option A : dossier `common/` avec index de références depuis les feuilles vers les entrées communes (plus propre, pas de duplication). Option B : symlinks Unix depuis les feuilles vers les entrées communes (plus simple, moins portable). À décider avant d'implémenter le Retriever. -->

### 4.3 Format d'une entrée

Chaque entrée est un petit fichier JSON :

```json
{
  "titre": "Article L.442-1 du Code de commerce",
  "source_officielle": "Légifrance",
  "url": "https://www.legifrance.gouv.fr/codes/article_lc/...",
  "extrait_pre_fetche": "Engage la responsabilité de son auteur et l'oblige à réparer le préjudice causé le fait, par tout producteur...",
  "hash_contenu": "sha256:a3f2...",
  "date_derniere_verification": "2026-04-07",
  "date_entree_en_vigueur": "2019-04-25",
  "mots_cles": ["déséquilibre significatif", "pratiques commerciales", "responsabilité"],
  "type_recherche": ["analyse-clause", "contentieux-commercial"],
  "profession": "avocat",
  "statut": "en_vigueur"
}
```

<!-- À TRANCHER: format JSON par fichier (un fichier par entrée) ou base SQLite avec schéma équivalent ? Le JSON est plus lisible et versionnable par git, SQLite est plus rapide en lookup. Décision à prendre avant d'implémenter le Retriever. -->

### 4.4 Volume et stratégie v1 — étroite et profonde

**Tenir août 2026 avec une base large et superficielle est impossible à qualité crédible.** Tenir août 2026 avec une base étroite et profonde est réaliste.

**Stratégie retenue :** démarrer par une preuve de concept sur **une seule intersection ultra-spécifique** — proposition initiale : `avocat/entreprise/contentieux_social/prudhommes/`. La peupler complètement avec 20-30 sources bien choisies (arrêts Cass. Soc. clés, articles L.1232 à L.1243, procédure CPH). Tester le retrieval bout en bout. Valider la qualité avec un vrai avocat si possible.

Si la preuve de concept est concluante en 2 semaines : industrialiser en déroulant 5-6 intersections supplémentaires par profession.

**Cible réaliste v1 : 8 à 10 intersections métier couvertes magistralement**, choisies avec les premiers pilotes, plutôt que 40 couvertes médiocrement.

<!-- À TRANCHER: choix exact des 8-10 intersections à couvrir en v1 — à définir avec les pilotes utilisateurs (avocat + expert-comptable bêta) avant Jalon 2. -->

**Ce que cette décision signifie pour le discours produit (défendable devant un critique) :**  
> "Lucie v1 ne prétend pas couvrir tout le droit français et toute la comptabilité française. Lucie v1 couvre 8 à 10 intersections métier précises, choisies avec les premiers pilotes, avec une profondeur qui permet à Lucie d'être réellement utile sur ces cas."

C'est une position honnête, buildable, et mesurable.

### 4.5 Risques et mitigations de la base curatée

**a) Explosion combinatoire**  
Profession × type_client × matière × sous-matière peut monter à 200-300 dossiers dans l'arbre complet. Mitigation : règle stricte "on ne crée un dossier que s'il a du vrai contenu". Démarrer avec les 8-10 intersections PoC, étendre au fil des besoins observés en production.

**b) Sources transverses — risque de duplication**  
L'article 1240 du Code civil (responsabilité extracontractuelle) est pertinent dans au moins 5 feuilles différentes. Dupliquer crée de la maintenance. Mitigation : dossier `common/` + index de références depuis les feuilles, ou symlinks Unix.

<!-- À TRANCHER: index de références vs symlinks — voir §4.2 -->

**c) Politesse réseau du pipeline quotidien**  
Légifrance, BOFiP, URSSAF, JuriCA peuvent bloquer les scrapers automatisés. Mitigation :  
- Respect strict des `robots.txt`  
- Backoff exponentiel sur HTTP 429  
- Étalement nocturne sur plusieurs heures (pas tout en même temps)  
- Cache par `hash_contenu` : pas de re-fetch si le contenu n'a pas changé  
- Note : certaines sources professionnelles (Doctrine, Lexbase, Lamyline) nécessitent un abonnement. À budgéter pour v2 si les sources gratuites ne couvrent pas assez.

**d) Qualité éditoriale — le code ne fait pas tout**  
Choisir quelle jurisprudence inclure dans `prudhommes/`, quels arrêts sont vraiment les arrêts de principe, quelle doctrine retenir — ce ne sont pas des décisions automatisables. Mitigation : approche "étroite et profonde" qui permet un travail éditorial sérieux sur chaque intersection, vs une approche large qui garantit la superficialité.

### 4.6 Ce que la base curatée n'est PAS

- Pas un moteur de recherche exhaustif du droit français
- Pas infaillible : les entrées peuvent être périmées en cas de bug du pipeline quotidien
- Pas un remplacement de l'expertise humaine : elle fournit des sources, pas des avis juridiques
- Pas exhaustive sur les premières versions : 8-10 intersections couvertes profondément, pas tout le droit

---

## 5. Pipeline quotidien de mise à jour

**Motif du passage à la fréquence quotidienne :** dans le juridique et le comptable, une circulaire BOFiP publiée le matin ou un arrêt de Cass rendu la veille peuvent changer la réponse à donner aujourd'hui. Une base datant de 6 jours est un risque professionnel pour l'utilisateur. Le Mac dort 8-10h par nuit — ce temps est largement suffisant pour un run de refresh.

### 5.1 Architecture du pipeline

Le pipeline de mise à jour est un **script Python séparé**, déclenché par `launchd` (macOS) chaque nuit. Il ne tourne PAS dans le processus Lucie. Il n'a aucun contact avec les agents runtime.

```
launchd (chaque nuit, heure configurable — défaut 2h00)
    │
    ▼
update_knowledge.py (script batch)
    │
    ├──► Scan Légifrance — publications du jour
    ├──► Scan JuriCA — arrêts publiés depuis le dernier run
    ├──► Scan BOFiP — bulletins DGFiP mis à jour
    ├──► Scan URSSAF — nouveaux barèmes ou communications
    └──► Scan ANC/CRC — bulletins comptables
    │
    ▼
Pour chaque entrée scannée :
    - hash_contenu comparé à l'entrée existante
    - Si identique : skip (pas de re-fetch)
    - Si nouveau ou modifié : mise à jour du fichier JSON + statut
    - Entrées obsolètes : taguées statut="supersede"
    │
    ▼
Génération du digest quotidien :
    ~/Lucie/Knowledge/digests/YYYY-MM-DD.md
    (5-10 entrées de changements par jour — lisible en 2 minutes)
    │
    ▼
Notification Lucie → présentée à l'utilisateur à la prochaine ouverture :
    "2 textes mis à jour cette nuit. Voir le digest du 2026-07-15."
```

### 5.2 Format du digest quotidien

```markdown
# Knowledge Digest — 2026-07-15

## Changements de la nuit
- **[nouveau]** Cass. Soc. 14/07/2026 — Licenciement économique : ordre des critères
  Feuille : avocat/entreprise/contentieux_social/licenciement_economique/
  Source : JuriCA | Mots-clés : licenciement, ordre critères, L.1233-5

- **[mis à jour]** Art. L.442-1 Code commerce — version consolidée 2026-07-01
  Feuille : common/articles_codes/
  Source : Légifrance

## Entrées obsolètes
- Aucune

## Run suivant : 2026-07-16 02:00
```

Le digest quotidien est lisible par l'utilisateur professionnel pour sa propre veille — remplace un abonnement à une newsletter juridique pour les cas couverts par la base.

### 5.3 Séparation stricte batch / runtime — garantie offline-first

Le pipeline de mise à jour ne peut pas être déclenché depuis un agent runtime. Il n'y a pas d'API interne entre `update_knowledge.py` et le processus Lucie. La seule communication est la modification des fichiers dans `~/Lucie/Knowledge/` et la création du digest.

**Cette séparation est la garantie architecturale de l'offline-first.** Si le Mac n'a pas accès à internet pendant une session, Lucie fonctionne normalement avec la base locale déjà présente. Le refresh quotidien se déclenche la nuit suivante si le réseau est disponible.

Règle d'implémentation : **aucun agent runtime ne peut jamais déclencher une connexion réseau.** Toute dépendance réseau introduite dans le process Lucie casse la garantie offline-first. Cette règle est une ligne rouge architecturale, à vérifier à chaque pull request.

---

## 6. Architecture runtime — les 5 composants en série

### 6.1 Vue d'ensemble

```
Utilisateur
    │ texte libre ou commande dictée
    ▼
┌──────────────────────────────────────────────────────────────┐
│ ROUTEUR (code pur, pas de LLM)                               │
│  lit le journal + classifie intention + dispatch             │
└────────────────────────┬─────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────────────┐
          ▼              ▼                       ▼
     [Lecteur]      [Retriever]           [Rédacteur]
       E2B            E2B                    E4B
    (si document   (lookup index         (si livrable
     fourni)        local)               demandé)
          │              │                       │
          └──────────────┴───────────────────────┘
                         │
                         ▼
              [Vérificateur — E2B]
               compare texte ↔ sources déterministes
               (même base curatée utilisée par Retriever)
                         │
                         ▼
           Journal dossier (journal.md)
                         │
                         ▼
                   Utilisateur
```

### 6.2 Séquence complète — tâche type

Pour "analyse la clause de non-concurrence de ce contrat et prépare une note d'analyse" :

```
1. Routeur (code)
   → lit journal.md : premier accès à ce dossier
   → classifie : juridique / analyse-clause + rédaction-note
   → dispatch → Lecteur (document fourni)

2. Lecteur (E2B)
   → extrait les clauses du contrat
   → retourne JSON : {clauses, parties, durée, périmètre}
   → écrit dans journal.md : "[10:32] Lecteur — 3 clauses extraites"

3. Routeur (code)
   → lit journal.md : extraction faite, besoin de sources
   → dispatch → Retriever

4. Retriever (E2B)
   → classifie la requête : "clause non-concurrence, validité, droit du travail"
   → lookup dans ~/Lucie/Knowledge/avocat/articles_codes/ et jurisprudence_cass/
   → retourne les 3-5 entrées les plus pertinentes avec leurs extraits pré-fetchés
   → écrit dans journal.md : "[10:33] Retriever — 4 sources trouvées, 1 arrêt récent pertinent"

5. Routeur (code)
   → lit journal.md : sources disponibles, rédaction demandée
   → dispatch → Rédacteur avec contexte = {extraction + sources}

6. Rédacteur (E4B)
   → reçoit : données extraites + 4 sources avec extraits
   → rédige la note d'analyse en citant les sources
   → refuse d'aller au-delà des faits dans le contexte
   → écrit dans journal.md : "[10:36] Rédacteur — note produite, 4 affirmations factuelles à vérifier"

7. Vérificateur (E2B)
   → reçoit : note rédigée + liste des affirmations
   → confronte à la même base curatée (cohérence garantie)
   → retourne : {confirmed: 3, divergence: 1, unverifiable: 0}
   → flaggue la divergence, corrige ou retire selon la règle
   → écrit dans journal.md : "[10:37] Vérificateur — 1 divergence corrigée"

8. Routeur
   → compile livrable final + trace dans journal
   → présente à l'utilisateur
```

---

## 7. Fiches techniques des agents

### 7.1 Routeur

| Propriété | Valeur |
|---|---|
| Type | Code déterministe (pas de LLM) |
| Modèle | Aucun |
| Domaine | Classification d'intention, lecture du journal, dispatch |
| Entrée | Texte brut + état du journal |
| Sortie | `{agent_cible, secteur, tâche, contexte_journal}` |
| Clause de refus | Ambiguïté non résolvable → demande de clarification à l'utilisateur |
| Implémentation | Regex + dictionnaire de mots-clés + fuzzy matching (threshold 80%) |

---

### 7.2 Agent Lecteur

| Propriété | Valeur |
|---|---|
| Modèle | Gemma 4 E2B |
| Domaine autorisé | Extraction de données structurées depuis un document fourni |
| Entrée | Document (PDF/DOCX converti en texte) + instruction d'extraction |
| Sortie | JSON structuré : `{parties, dates, clauses, montants, références}` |
| Clause de refus | Si demande de rédaction ou de jugement → `out_of_scope` |
| Vérification attachée | Aucune (la vérification est faite par le Vérificateur en aval) |
| Écrit dans journal | Oui — données extraites + timestamp |

**Prompt système (forme simplifiée) :**
```
Tu es un extracteur de données juridiques et comptables.
Tu lis uniquement ce qu'on te fournit. Tu n'inventes rien.
Tu retournes un objet JSON structuré avec les champs demandés.
Si un champ n'est pas présent dans le document, tu retournes null, pas une valeur plausible.
Si on te demande de rédiger ou d'émettre un avis, retourne {"status": "out_of_scope"}.
```

---

### 7.3 Agent Retriever — marcheur d'arbre sémantique

| Propriété | Valeur |
|---|---|
| Modèle | Gemma 4 E2B (classification de requête en tuple hiérarchique) |
| Domaine autorisé | Classifie la requête → descend dans l'arbre → retourne les sources de la feuille |
| Entrée | Question ou contexte + secteur (avocat / comptable) |
| Sortie | Liste de 3-5 entrées JSON pré-fetchées depuis la feuille correspondante |
| Clause de refus | Si feuille inexistante ou hors périmètre → `no_source_found` ; si demande de rédaction → `out_of_scope` |
| Lookup | Local uniquement. Zéro requête réseau. |
| Écrit dans journal | Oui — tuple (profession, client_type, matière, sous-matière) + sources retournées |

**Comportement de marcheur d'arbre :**

Le Retriever ne fait pas une recherche globale dans toute la base. Il suit trois étapes séquentielles :

```
1. Classification de la requête
   → produit un tuple : (profession, client_type, matière, sous-matière)
   → ex : ("avocat", "entreprise", "contentieux_social", "prudhommes")

2. Navigation dans l'arbre
   → descend dans ~/Lucie/Knowledge/avocat/entreprise/contentieux_social/prudhommes/
   → si la feuille n'existe pas : retourne no_source_found, le routeur informe l'utilisateur

3. Lecture des fichiers de la feuille
   → lit les 3-5 fichiers JSON présents dans la feuille
   → retourne leurs champs {titre, extrait_pre_fetche, source_officielle, date_derniere_verification}
   → ne remonte jamais dans les nœuds parents sauf si la feuille est vide
```

**Ce que le Retriever ne fait PAS :**
- Il ne fait pas d'exploration latérale (il ne regarde pas `licenciement_economique/` si on lui demande `prudhommes/`)
- Il ne synthétise pas les sources — c'est le Rédacteur
- Il ne fait aucune requête réseau

<!-- À TRANCHER: la classification initiale en tuple hiérarchique — option A : code déterministe (regex + dictionnaire de mots-clés sectoriels) pour les cas couverts, E2B uniquement en fallback pour les cas ambiguës. Option B : E2B systématiquement pour la classification, plus robuste aux formulations imprévues. L'option A est plus rapide et plus prévisible ; l'option B couvre mieux les cas rares. À décider pendant l'implémentation du Jalon 2. -->

**Prompt système (forme simplifiée — utilisé si E2B requis pour classification) :**
```
Tu reçois une question juridique ou comptable.
Tu retournes exactement un tuple JSON : {"profession": ..., "client_type": ..., "matiere": ..., "sous_matiere": ...}
Les valeurs possibles sont celles de l'arbre ~/Lucie/Knowledge/ — liste fournie en contexte.
Si la question ne correspond à aucune feuille connue, retourne {"status": "no_source_found"}.
Tu ne rédiges rien. Tu ne cherches pas. Tu classes.
```

---

### 7.4 Agent Rédacteur

| Propriété | Valeur |
|---|---|
| Modèle | Gemma 4 E4B |
| Domaine autorisé | Rédaction de livrables textuels à partir de sources fournies en contexte |
| Entrée obligatoire | Journal du dossier (contexte) + sources pré-fetchées par le Retriever |
| Sortie | Texte du livrable (mise en demeure, note, tableau) |
| Clause de refus | Si sources insuffisantes dans le contexte → `insufficient_context` (jamais d'invention) |
| Vérification attachée | Vérificateur obligatoire en aval (pas de livrable sans passer par le Vérificateur) |
| Écrit dans journal | Oui — livrable produit + liste des affirmations factuelles incluses |

**Pourquoi E4B et pas E2B :**  
La rédaction de livrables longs (mise en demeure, rapport d'analyse, note de synthèse) nécessite une fenêtre de contexte large (sources pré-fetchées + extraction + instructions) et un raisonnement de plus haute qualité sur la structure du texte. E4B est perceptiblement meilleur que E2B sur des générations > 500 tokens. E2B reste utilisé pour les rôles dont la sortie est courte et structurée (JSON, liste de sources).

**Prompt système (forme simplifiée) :**
```
Tu es un rédacteur juridique et comptable de précision.
Tu rédiges uniquement à partir des faits et sources présents dans le contexte fourni.
Tu n'inventes jamais un article de loi, une date, un montant, un nom de partie.
Si un fait nécessaire manque, tu le signales par [MANQUANT: description] et tu continues.
Si on te demande de chercher des sources ou d'extraire un document, retourne {"status": "out_of_scope"}.
```

---

### 7.5 Agent Vérificateur

| Propriété | Valeur |
|---|---|
| Modèle | Gemma 4 E2B |
| Domaine autorisé | Comparaison d'un texte rédigé à des sources déterministes + flagging des divergences |
| Entrée | Texte à vérifier + affirmations factuelles listées |
| Sources de vérification | Même base curatée utilisée par le Retriever (cohérence garantie) + vérificateurs externes |
| Sortie | `{affirmations[{claim, status, source}]}` — statuts : `confirmed`, `divergence`, `unverifiable` |
| Clause de refus | Si demande de rédaction ou de reformulation → `out_of_scope` |
| Écrit dans journal | Oui — résultats de vérification + sources consultées |

**Vérificateurs déterministes attachés :**

| Domaine | Vérificateur | Mode |
|---|---|---|
| Juridique — textes de loi | Base curatée locale + Légifrance API (confirmation online) | Local first, online si doute |
| Juridique — jurisprudence | Base curatée locale + JuriCA | Local first, online si doute |
| Comptable | Base curatée PCG + CRC + BOFiP | Index local |
| Code — sécurité | bandit + semgrep | subprocess local |
| Code — exécution | Sandbox Python isolée (pas de réseau) | subprocess local |

**Prompt système (forme simplifiée) :**
```
Tu reçois un texte et une liste d'affirmations factuelles.
Pour chaque affirmation, tu cherches sa confirmation dans les sources fournies.
Tu ne rédiges pas, tu ne reformules pas, tu ne juges pas le style.
Ta sortie : liste d'affirmations avec statut confirmed / divergence / unverifiable.
Si divergence, tu cites la source qui contredit. Si unverifiable, tu expliques pourquoi.
```

---

## 8. Mémoire de travail partagée

**Le journal du dossier est la seule mémoire partagée entre agents.**

Chemin : `~/Lucie/Dossiers/{nom_dossier}/journal.md`

Les agents n'ont pas de mémoire propre. Ils ne communiquent pas directement entre eux. Ils écrivent dans le journal en append, et le routeur lit le journal entre chaque étape.

**Format du journal :**

```markdown
# Journal — Dossier Dupont vs Martin
Dernière activité : 2026-07-15 10:37

## Contexte du dossier
- Type : Contentieux commercial — analyse clause non-concurrence
- Parties : Dupont SARL (demandeur), Martin SAS (défendeur)

## Timeline

### [10:32] Lecteur — E2B
Extraction réussie sur contrat_dupont_martin.pdf
3 clauses identifiées (art. 12.1, 12.2, 12.3)

### [10:33] Retriever — E2B
4 sources retournées depuis ~/Lucie/Knowledge/avocat/
- Art. L.1237-19 (articles_codes)
- Cass. Soc. 18/09/2002 n°99-46.136 (jurisprudence_cass)
- [2 autres]

### [10:36] Rédacteur — E4B
Note d'analyse produite — 4 affirmations factuelles à vérifier

### [10:37] Vérificateur — E2B
Résultats : confirmed: 3, divergence: 1
Divergence : art. 12.1 ne mentionne pas la contrepartie financière (L.1237-19 l'exige)

## Affirmations vérifiées
| Affirmation | Statut | Source |
|---|---|---|
| Art. L.1237-19 Code du travail | confirmed | Base curatée 2026-04-07 |
| Cass. Soc. 18/09/2002 n°99-46.136 | confirmed | Base curatée 2026-04-07 |

## Découvertes latérales
- [10:33] Retriever : art. 12.4 (pénalités) présent dans le contrat — non analysé, peut être pertinent

## Décisions en attente
- Utilisateur : valider si mise en demeure sur base de cette analyse ?
```

**Propriétés du journal :**
- Format Markdown, lisible dans n'importe quel éditeur
- Append-only (jamais d'effacement d'entrées passées)
- Schéma fixe défini avant le Jalon 2 (requis pour que le routeur le lise correctement)
- Exportable en PDF, copiable sans outillage spécial
- 100% local, jamais synchronisé sans accord explicite

---

## 9. Garanties d'isolation

Quatre couches de défense contre la dérive :

**1. Prompt court et restrictif (≤ 300 tokens).**  
Un prompt court concentre la distribution de sortie du modèle. Moins de tokens de contexte = moins de dérive thématique. C'est l'effet du role priming extrême.

**2. Clause de refus explicite.**  
Chaque agent retourne `out_of_scope` si la requête sort de son domaine. Un agent ne peut pas recruter un autre agent ou élargir son périmètre.

**3. Vérification externe déterministe en sortie.**  
Le Vérificateur confronte la sortie du Rédacteur à des sources déterministes. Il ne peut pas valider une hallucination — sa vérification ne passe pas par un LLM.

**4. Journal auditable en append.**  
Tout ce que chaque agent fait est tracé dans journal.md avec timestamp, modèle, et sources. L'utilisateur peut auditer n'importe quelle session. Aucune action n'est silencieuse.

**Défense contre la prompt injection :**  
La clause de refus hors-scope est aussi une couche de défense contre la prompt injection. Un document malveillant qui tenterait de faire "rédiger" le Lecteur ou "chercher" le Vérificateur recevrait un `out_of_scope`. Les tests du Jalon 3 incluent des cas d'injection déguisée en requête dans le domaine.

---

## 10. Règle 19 opérationnalisée

La Règle 19 du Manifeste Comportemental : toute affirmation factuelle vérifiable est confrontée à une source externe déterministe avant d'être montrée à l'utilisateur.

### 10.1 Pipeline de vérification

```
Rédacteur produit le texte + liste les affirmations factuelles
    │
    ▼
Vérificateur reçoit : texte + affirmations
    │
    ├──► Base curatée locale (premier filtre, cohérence)
    ├──► Légifrance API (textes de loi — confirmation online)
    ├──► JuriCA (jurisprudence — confirmation online)
    ├──► PCG index local (comptabilité)
    ├──► bandit / semgrep (code — sécurité)
    └──► Sandbox Python (code — exécution)
    │
    ▼
Statut par affirmation : confirmed | divergence | unverifiable
    │
    ├── divergence → affirmation corrigée ou retirée du livrable
    └── unverifiable → affirmation marquée explicitement dans le livrable
```

### 10.2 Zones où Lucie refuse de répondre

- **Source externe indisponible** + question sur du droit positif récent : Lucie ne présente pas d'affirmation factuelle. Elle dit explicitement qu'elle n'a pas de source vérifiée.
- **Hors périmètre des vérificateurs branchés** (droit social, pénal, fiscal international en v1) : la sortie est entièrement marquée "non vérifiable", avec recommandation de consulter un spécialiste.
- **Jurisprudence sans numéro vérifiable** : jamais présentée comme valide. Confirmée ou retirée.

---

## 11. Impact sur le budget tokens

> **Ces estimations sont à confirmer par benchmark.** Elles ne sont pas des engagements contractuels.

**Sans base curatée (exploration ouverte) :**
- Tokens brûlés en exploration/navigation : ~30-50%
- Tokens utiles en synthèse : ~50-70%
- Risque hallucination : élevé (articles inventés, arrêts paraphrasés)
- Latence perçue : 8-15s pour une rédaction type

**Avec base curatée (lookup + synthèse) :**
- Tokens en classification de requête (Retriever) : ~5%
- Tokens en synthèse sur sources réelles : ~95%
- Risque hallucination : réduit (les vraies sources sont dans le contexte)
- Latence perçue estimée : 2-4s pour une rédaction type

**Ce que ce changement ne fait PAS :**
- Il ne rend pas Lucie infaillible : les entrées de la base peuvent être périmées en cas de bug du pipeline de mise à jour
- Il ne couvre pas 100% des cas : les requêtes hors des 80% fréquents tombent sur "no_source_found" et le routeur le signale
- Il ne remplace pas la vérification externe (Règle 19) : même avec une base curatée, le Vérificateur confronte les affirmations aux sources officielles

---

## 12. Garantie offline-first

### 12.1 La garantie

**Lucie fonctionne à 100% hors ligne pendant une session de travail normale.** Entre le lancement de Lucie et la livraison d'un livrable, aucun appel réseau n'est requis. L'utilisateur peut travailler en salle d'audience, en cabinet client rural, dans le train, dans une zone à wifi médiocre — Lucie fonctionne.

**La seule connexion sortante autorisée** est le pipeline quotidien de mise à jour de la base (`update_knowledge.py`), qui tourne la nuit quand le Mac est en veille et connecté au réseau domestique ou de bureau. Si le réseau n'est pas disponible la nuit en question, le refresh est différé à la nuit suivante. Ce n'est pas bloquant.

### 12.2 Pourquoi cette garantie est architecturalement vraie

Elle n'est pas une promesse marketing ajoutée après coup — elle découle directement des décisions architecturales :

- **Base curatée locale** : les sources sont pré-fetchées et stockées dans `~/Lucie/Knowledge/`. Le Retriever fait un lookup sur des fichiers locaux. Zéro requête réseau.
- **Gemma 4 via Ollama** : le modèle tourne localement. Zéro appel API cloud.
- **Séparation batch/runtime** : le pipeline de refresh est un script séparé qui ne tourne jamais pendant une session utilisateur.

### 12.3 Limites honnêtes de la garantie

La garantie offline-first couvre la session de travail. Elle ne couvre pas :
- La fraîcheur de la base (si le Mac n'a pas eu de réseau depuis 5 jours, la base a 5 jours de retard)
- Les requêtes hors des intersections couvertes (Lucie dit "non trouvé" sans réseau)
- Le premier setup (Ollama + Gemma 4 + base initiale nécessitent un téléchargement initial)

**Ce que cette garantie n'est jamais :** "Lucie connaît tout le droit en permanence à jour en temps réel hors ligne." Ce claim est faux et ne sera jamais fait.

### 12.4 Argument commercial

La garantie offline-first est un avantage différentiant réel vs les concurrents cloud (ChatGPT Plus, Gemini, Copilot, etc.) pour les professionnels réglementés :
- Confidentialité des données client (les dossiers ne transitent pas par des serveurs tiers)
- Conformité RGPD simplifiée (traitement 100% local)
- Disponibilité sans dépendance réseau

Ces trois points sont vrais et défendables. Ne pas en rajouter.

---

## 13. Positionnement produit vs architecture interne

**Principe :** vérité absolue vers l'utilisateur sur ce que Lucie fait, discrétion légitime sur comment elle le fait.

**Phrase produit vérifiable et honnête :**  
> "Lucie connaît les sources officielles de votre profession, mises à jour chaque semaine, et les utilise pour rédiger vos livrables en citant systématiquement ses sources."

Cette phrase est défendable devant un audit d'honnêteté :
- "connaît les sources officielles" : vrai — base curatée sur Légifrance, JuriCA, PCG, BOFiP
- "mises à jour chaque semaine" : vrai — pipeline batch hebdomadaire
- "cite systématiquement ses sources" : vrai — le Vérificateur bloque tout ce qui n'est pas sourcé

**Ce qui reste savoir-faire propriétaire (non communiqué, non mensonger) :**
- La structure exacte de l'index (JSON, schéma, organisation par type_recherche)
- Les règles de classification de requête du Retriever
- Le pipeline de mise à jour hebdomadaire (scripts, sources scannées, heuristiques de pertinence)
- Le mapping E2B / E4B par rôle

**Ce qui n'est jamais dit parce que ce serait faux :**
- "Lucie est exhaustive" → non, elle couvre ~80% des cas fréquents
- "Lucie ne fait jamais d'erreur" → non, les hallucinations résiduelles sont détectées et signalées, pas éliminées
- "Lucie est à jour en temps réel" → non, l'index est mis à jour hebdomadairement

**La discrétion sur l'architecture n'est pas un mensonge.** Aucune affirmation fausse n'est faite. Le mécanisme technique reste un secret industriel — exactement comme un cabinet d'avocats ne publie pas ses bases de données internes.

---

## 14. Moat produit

La base de connaissances curatée constitue le premier actif durable non-reproductible en quelques jours par un concurrent.

Construire un index de qualité couvrant le droit français des affaires + la comptabilité française à ce niveau de granularité (entrées pré-fetchées, mots-clés, types de recherche, hash de vérification) demande plusieurs semaines de travail minutieux. Ce n'est pas une barrière technologique — c'est une barrière d'effort.

Contrairement à l'ancienne architecture orchestrale (qui aurait pu être copiée d'une semaine sur l'autre), cet actif est transférable au produit et à ses utilisateurs via le digest hebdomadaire. Il prend de la valeur à chaque mise à jour.

**Ce que le moat n'est PAS :**
- Une barrière technique insurmontable : n'importe qui peut construire un index similaire avec assez de temps
- Une protection légale : les textes de loi sont publics
- Un avantage permanent : si Légifrance ouvre une API plus simple ou si un concurrent investit massivement, l'avantage s'érode

Le moat est réel pour la fenêtre août 2026 — premiers utilisateurs réels. Il n'est pas permanent.

---

## 15. Couche de réflexion et auto-amélioration

### 14.1 Principe

C'est le troisième pilier architectural de Lucie v1, après les agents contraints et la base curatée. C'est aussi la mise en œuvre concrète du pilier "path compression par apprentissage" de la roadmap long terme.

**Le problème qu'il résout :** le modèle E4B tourne en RAM pendant les périodes d'inactivité utilisateur sans produire de valeur. Entre deux sessions, il dort. Cette couche exploite ce temps mort.

**Le mécanisme :** chaque agent contraint écrit en fin de tâche une petite note de réflexion structurée dans son dossier. Pendant les périodes d'inactivité (≥ 5-10 minutes sans activité utilisateur), le Réflecteur — une instance du LLM E4B — lit les notes récentes, repère les patterns, et propose des améliorations aux prompts système des agents. Les propositions sont versionnées et **exigent une validation humaine avant d'être appliquées**.

**Ce que le Réflecteur ne peut jamais faire :** modifier un prompt de sa propre initiative. Jamais. Cette ligne rouge est non-négociable et structurellement enforced — les prompts sont des fichiers versionnés, et seule une action humaine explicite (accepter une proposition) peut en créer une nouvelle version.

**Lien avec le path compression :** les prompts améliorés réduisent progressivement la distribution de sortie des agents → les patterns émergent plus clairement → les fast-paths du routeur se compilent plus facilement. Après quelques mois d'usage, Lucie devient non-remplaçable pour SON utilisateur : base curatée enrichie + prompts affinés par ses propres dossiers + fast-paths appris = un outil taillé sur mesure.

### 14.2 Structure de stockage

```
~/Lucie/Reflections/
    current/                    # fenêtre de 2 semaines en cours
        retriever/
            YYYY-MM-DD.md       # notes journalières de l'agent
        lecteur/
            YYYY-MM-DD.md
        redacteur/
            YYYY-MM-DD.md
        verificateur/
            YYYY-MM-DD.md
    archive/
        YYYY-Www/               # semaine ISO, fenêtre archivée et résumée
            retriever_summary.md
            lecteur_summary.md
            redacteur_summary.md
            verificateur_summary.md
    proposals/                  # propositions du réflecteur, en attente de validation
        YYYY-MM-DD_{agent}.md
    digests/
        week_YYYY-Www.md        # rapport hebdomadaire humainement lisible

~/Lucie/Prompts/                # prompts agents versionnés comme du code
    retriever_v1.md
    retriever_v2.md
    retriever_changelog.md
    retriever_regression_tests.md
    lecteur_v1.md
    ...
```

### 14.3 Format des notes de réflexion

Chaque agent écrit une entrée courte et structurée après chaque tâche non-triviale. L'entrée ne contient jamais d'identifiants utilisateur — uniquement des patterns abstraits.

```markdown
## [2026-07-15 10:37] — task_id: T2026-07-15-003

**Ce qui était demandé (pattern abstrait) :** analyse de clause contractuelle + comparaison jurisprudentielle

**Ce qui a été facile :** extraction des clauses avec les champs connus (durée, périmètre, parties)

**Ce qui a coincé :** le champ "contrepartie financière" n'était pas dans mon schéma d'extraction habituel — j'ai retourné null mais l'utilisateur avait besoin de ce champ pour la vérification

**Ce qui aurait aidé :**
- Une entrée "contrepartie_financiere" dans mon schéma d'extraction par défaut pour les clauses de non-concurrence
- Un exemple dans la base curatée spécifiquement sur les cas où la contrepartie manque

**Out_of_scope déclenché :** non

**Durée d'exécution :** 2.3s
```

**Règle d'anonymisation :** pas de nom de partie, pas de référence de dossier, pas de date d'audience, pas de montant spécifique. Uniquement des patterns de tâche et des retours sur les capacités de l'agent.

### 14.4 Le Réflecteur d'inactivité

**Déclenchement :** 5-10 minutes d'inactivité utilisateur (seuil configurable).

**Ce qu'il fait :**
1. Lit les notes de réflexion de la fenêtre courante (`current/`)
2. Repère les patterns récurrents : erreurs systématiques, champs manquants, cas de refus hors-scope fréquents
3. Formule des propositions d'amélioration de prompt
4. Écrit les propositions dans `proposals/`

**Format d'une proposition :**
```markdown
# Proposition — Lecteur v3 → v4
Date : 2026-07-15
Agent cible : lecteur
Auteur : Réflecteur

## Modification proposée

**Actuel (lecteur_v3.md):**
> Tu retournes un objet JSON structuré avec les champs demandés.
> Si un champ n'est pas présent, tu retournes null.

**Proposé (lecteur_v4.md):**
> Tu retournes un objet JSON structuré avec les champs demandés.
> Si un champ n'est pas présent, tu retournes null.
> Pour les clauses de non-concurrence, tu ajoutes systématiquement le champ
> "contrepartie_financiere" même si non demandé explicitement.

## Preuves obligatoires
- T2026-07-14-002 : null retourné sur contrepartie_financiere, champ attendu par Vérificateur
- T2026-07-15-003 : même pattern, utilisateur a dû relancer l'extraction manuellement
- T2026-07-12-005 : cas similaire, même blocage

## Risque de régression estimé
Faible — ajout d'un champ optionnel, pas de modification d'un champ existant.

## Tests de régression recommandés
- doc_test_01.pdf : extraction standard sans clause de non-concurrence → champ doit être absent
- doc_test_07.pdf : contrat avec clause NC sans contrepartie → champ doit être "absent" explicitement
```

**Règle de rejet automatique :** une proposition sans preuves citées (entrées de réflexion concrètes) est rejetée automatiquement par le système. Le Réflecteur ne peut pas proposer une modification "parce qu'il pense que c'est mieux" — il doit montrer les preuves.

### 14.5 Gate de validation humaine

Toute proposition est soumise à validation humaine avant d'être appliquée.

**Interface minimale :**
- Notification Lucie : "1 proposition d'amélioration de prompt disponible — Agent Lecteur"
- L'utilisateur voit : titre de la proposition, diff du prompt, preuves citées
- L'utilisateur choisit : accepter / rejeter / demander révision
- Si rejetée : archivée avec le motif, le Réflecteur en tient compte

**Ce qui se passe après acceptation :**
1. Le nouveau fichier de prompt est créé (`lecteur_v4.md`)
2. La version précédente reste accessible (`lecteur_v3.md`)
3. Le changelog est mis à jour
4. Les tests de régression sont exécutés — si un test échoue, la version n'est pas activée
5. La nouvelle version est activée pour les sessions suivantes

### 14.6 Versioning et rollback des prompts

Chaque prompt agent est un fichier Markdown versionné :

```
~/Lucie/Prompts/lecteur_v1.md    # version initiale
~/Lucie/Prompts/lecteur_v2.md    # première amélioration acceptée
~/Lucie/Prompts/lecteur_changelog.md
~/Lucie/Prompts/lecteur_regression_tests.md
```

Le changelog documente : quelle version, quelle date, quelle proposition, qui a accepté, quel pattern a motivé le changement.

**Rollback :** une commande simple dans l'interface Lucie permet de revenir à la version précédente d'un prompt. Cas d'usage : une nouvelle version dégrade les performances réelles malgré le passage des tests de régression.

<!-- À TRANCHER: format exact du mini jeu de tests de régression. Option A : cas de test en Markdown (input → output attendu, vérification humaine). Option B : cas de test exécutables (script Python qui appelle le modèle et vérifie la sortie). Option A est plus simple mais subjectif. Option B est plus fiable mais demande du code à écrire par Mathieu pour chaque agent. -->

### 14.7 Rotation bi-hebdomadaire

Tous les 15 jours (à la bascule semaine ISO paire), le processus suivant se déclenche en période d'inactivité :

1. Le Réflecteur synthétise chaque dossier agent de `current/` en un fichier `{agent}_summary.md` dans `archive/YYYY-Www/`
2. Le dossier `current/` se vide — nouvelle fenêtre démarre
3. Le digest hebdomadaire est généré dans `digests/week_YYYY-Www.md`
4. Notification à l'utilisateur : "Réflexion bi-hebdomadaire complète — voir le digest"

**Motif de la rotation :**
- Protéger le contexte du Réflecteur : le LLM E4B a une fenêtre de contexte limitée — il ne peut pas lire 15 jours de notes brutes sans overflow
- Garantir la lisibilité humaine : les logs restent auditables par Mathieu ou l'utilisateur
- Éviter l'accumulation infinie : le dossier `current/` reste léger

### 14.8 Digest hebdomadaire

```markdown
# Digest Lucie — Semaine 2026-W28

## Volume de tâches
- Lecteur : 23 tâches
- Retriever : 31 tâches
- Rédacteur : 12 tâches
- Vérificateur : 12 tâches

## Patterns émergés cette semaine
- Lecteur : 4 occurrences du même champ manquant (contrepartie_financiere)
- Retriever : 2 requêtes retournant no_source_found sur droit URSSAF
- Rédacteur : temps de génération moyen 3.2s (stable vs 3.0s semaine précédente)

## Taux out_of_scope par agent
- Lecteur : 0% (0/23) — nominal
- Retriever : 6% (2/31) — dans la norme
- Rédacteur : 8% (1/12) — à surveiller (seuil d'alerte : 15%)
- Vérificateur : 0% (0/12) — nominal

## Propositions du réflecteur
- 1 proposition émise (Lecteur v3 → v4) — en attente de ta validation
- 0 proposition rejetée

## Versions de prompts actives
- lecteur_v3.md (depuis 2026-07-01)
- retriever_v2.md (depuis 2026-06-15)
- redacteur_v1.md
- verificateur_v1.md
```

### 14.9 Risques documentés

**Dérive de prompts :** un prompt amélioré itérativement peut dériver vers une sur-spécialisation qui dégrade les cas généraux. Mitigation : versioning + rollback + tests de régression + tracking du taux out_of_scope.

**Sur-spécialisation (taux out_of_scope anormal) :** si un agent refuse trop de requêtes légitimes, son prompt est trop restrictif.

<!-- À TRANCHER: seuil d'alerte exact sur le taux out_of_scope. 15% semble raisonnable pour déclencher une notification, 30% pour bloquer l'adoption d'une nouvelle version de prompt. À valider avec les premières données réelles. -->

**Hallucination du Réflecteur :** le Réflecteur est lui-même un LLM et peut proposer des modifications non justifiées. Mitigation : exigence de preuves citées dans chaque proposition. Sans preuves = rejet automatique.

**Overflow de contexte du Réflecteur :** trop de notes brutes = le Réflecteur perd le fil. Mitigation : rotation bi-hebdomadaire qui synthétise avant d'archiver.

**Fuite de données utilisateur :** les notes de réflexion pourraient contenir des données nominatives si les agents ne sont pas stricts. Mitigation : règle d'anonymisation dans le prompt de chaque agent + audit lors de la validation humaine des propositions.

---

## 16. Choix de chargement des modèles — Option A vs Option B

Décision reportée au bench Gemma 4 (session en cours au 2026-04-10).

### Option A — Deux modèles en permanence

| | Valeur |
|---|---|
| RAM modèles | ~6-8 Go (E2B + E4B) |
| RAM process complet | ~8-10 Go |
| Plancher hardware | M2 16 Go minimum |
| Avantage | Aucune latence de chargement |
| Inconvénient | Exclut M2 8 Go |

### Option B — Swap on-demand via Ollama

| | Valeur |
|---|---|
| RAM modèles | ~2-5 Go (modèle actif seulement) |
| RAM process complet | ~4-7 Go |
| Plancher hardware | M2 8 Go viable |
| Avantage | Ouvre le parc Mac 8 Go |
| Inconvénient | Première requête E4B : 1-2s de chargement (annoncé à l'utilisateur) |

**Critères de décision du bench :**
1. Latence réelle de chargement Ollama E4B (avec keep_alive configuré)
2. RAM totale process sur session 30 min en Option A
3. Perception utilisateur du swap E2B↔E4B en Option B

**Default en l'absence de bench :** implémenter Option B. Option A disponible comme paramètre de config.

<!-- À TRANCHER: Si E4B dépasse 6 Go de RAM sur M2 8 Go, Option B n'est pas viable. Dans ce cas, E2B seul pour tous les rôles avec perte de qualité mesurable sur la rédaction — à quantifier en bench avant de décider. -->

---

## 17. Contraintes hardware

**Budget RAM estimé (à confirmer par bench) :**

| Scénario | Option A | Option B |
|---|---|---|
| Idle | ~200 Mo | ~200 Mo |
| Retriever/Lecteur/Vérificateur actif (E2B) | ~3-4 Go | ~2-3 Go |
| Rédacteur actif (E4B) | ~7-9 Go | ~5-6 Go |
| Peak session | ~10-12 Go | ~7-8 Go |
| Plancher hardware recommandé | M2 16 Go | M2 8 Go |

---

## 18. Périmètre v1 strict

**Lucie v1 fait exactement quatre choses :**

1. **Lecture de documents** — extraction structurée (Lecteur) depuis PDF/DOCX
2. **Retrieval de sources** — lookup dans la base curatée (Retriever) + vérification online si nécessaire
3. **Rédaction de livrables** — texte produit à partir de sources vérifiées (Rédacteur + Vérificateur)
4. **Journal et mémoire de dossier** — persistance, reprise de session, découvertes latérales

**Explicitement hors v1 :**
- Envoi d'emails ou de documents
- Intégration agenda / calendrier
- Module de facturation / CRM
- Droit social, pénal, fiscal international
- Fine-tuning sur données cabinet
- Multi-utilisateurs / partage de dossier

**Règle SASU.** Aucune structuration juridique de l'entreprise avant que les 3 piliers fonctionnent de façon irréprochable avec au moins deux utilisateurs réels en beta.

---

## 19. Jalons août 2026

### Jalon 1 — Socle (mai 2026)

| Livrable | Critère d'acceptation |
|---|---|
| Routeur déterministe | 95% classification correcte sur 100 requêtes annotées |
| Ollama + Gemma 4 installé | Réponse Agent Lecteur en < 10s sur M-series |
| HUD macOS minimal | Saisie → réponse, sans crash en 30 min |
| Bench hardware | Rapport avec latences mesurées, décision Option A/B, plancher hardware défini |

### Jalon 2 — Pipeline 5 composants + base curatée (juin 2026)

| Livrable | Critère d'acceptation |
|---|---|
| Agent Lecteur | Extraction correcte sur 10 documents de test |
| Agent Retriever | 10 lookups corrects dans la base curatée v0 |
| Base curatée v0 | ≥ 500 entrées par profession, couverture des 20 cas fréquents documentés |
| Journal.md schéma défini | Schéma publié, routeur capable de le lire correctement |
| Schéma JSON entrée défini | Format validé par les deux premiers agents qui l'utilisent |

### Jalon 3 — Rédacteur + Vérificateur + isolation testée (juillet 2026)

| Livrable | Critère d'acceptation |
|---|---|
| Agent Rédacteur | Mise en demeure type validée par un avocat |
| Agent Vérificateur | 0 faux positif "confirmed" sur 10 tests de divergence connue |
| Pipeline hebdomadaire v1 | Premier run complet, digest généré correctement |
| Couche réflexion v0 | Notes d'agents produites après chaque tâche, lisibles et anonymisées |
| Réflecteur v0 | Première proposition générée avec preuves citées, gate de validation fonctionnel |
| Clause de refus testée | 20 tests out_of_scope + 5 tests injection déguisée, tous détectés |
| Règle 19 complète | Aucune affirmation non vérifiée présentée comme vraie dans 20 sessions |

### Jalon 4 — Beta fermée (août 2026)

| Livrable | Critère d'acceptation |
|---|---|
| 2 utilisateurs réels | 1 avocat + 1 expert-comptable, 2 semaines sur dossiers réels |
| Zéro hallucination non signalée | Audit 50 sessions : toutes les erreurs factuelles marquées ou bloquées |
| Documentation utilisateur | Prise en main sans assistance < 20 min |
| Base curatée v1 | ≥ 3000 entrées par profession |
| Packaging macOS | `.app` installable sur machine vierge sans CLI |

---

## 20. Vision long terme (annexe, non engageante pour v1)

<!-- Vision à 18-36 mois — ne pas laisser influencer les décisions v1. -->

- Extension à d'autres secteurs réglementés
- Partage de sessions entre professionnels d'un cabinet
- Mode offline complet avec index synchronized localement
- Fine-tuning local contrôlé par l'utilisateur
- Base curatée enrichie par les corrections des utilisateurs (feedback loop)

Ces évolutions ne seront considérées qu'après validation des 4 jalons.

---

## Annexe A — Ce qui a changé depuis la version précédente

### Supprimé

| Élément supprimé | Raison |
|---|---|
| 29 agents en RAM simultanément | Infaisable solo, incompatible budget RAM |
| 7 modèles LLM thématiques | Remplacés par 2 tailles Gemma 4 |
| FrontalCortex / PathManager complexe | Remplacé par routeur déterministe |
| Agent Search exploratoire | Remplacé par Agent Retriever sur index local |
| Bulletin inter-agents | Remplacé par journal.md centralisé |
| Audit LLM-sur-LLM | Remplacé par vérificateurs déterministes |
| Worktrees git | Sans objet en process unique |
| SoulAgent, DeceptionAgent, WakeAgent, etc. | Hors périmètre v1 |
| P2P / Couche 2 | Hors périmètre v1 |

### Ajouté

| Élément ajouté | Justification |
|---|---|
| Base de connaissances curatée en arbre hiérarchique (§4) | Retriever sémantique, pas de table plate |
| Agent Retriever marcheur d'arbre (§7.3) | Lookup déterministe par tuple (profession/client/matière/sous-matière) |
| Pipeline quotidien batch (§5) | Refresh nocturne — base datant de 6 jours = risque professionnel |
| Garantie offline-first (§12) | Aucun appel réseau en runtime — décision architecturale et argument commercial |
| Stratégie étroite-profonde (§4.4) | 8-10 intersections magistrales pour tenir août 2026 |
| Risques et mitigations base curatée (§4.5) | 4 risques documentés honnêtement |
| Impact sur budget tokens (§11) | Quantifie le gain, honnêteté sur les limites |
| Positionnement produit vs architecture (§13) | Clarifie ce qui est dit / non dit / jamais dit |
| Moat produit (§14) | Actif durable, valeur réaliste définie |
| Définition stricte "agent" (§3) | Évite la confusion avec vocabulaire orchestral |
| Garanties d'isolation (§9) | Défense contre dérive + injection |
| Couche de réflexion et auto-amélioration (§15) | Exploitation des temps morts E4B + path compression |
| Jalons avec critères binaires (§19) | Remplace estimations subjectives |

### Reformulé

| Avant | Après |
|---|---|
| "Agent" = entité autonome | "Agent" = rôle isolé par prompt dans un LLM |
| "Orchestration" = coordination multi-process | "Pipeline" = séquence dans un process unique |
| "Search" = exploration web ouverte | "Retriever" = lookup déterministe sur index local |
| "Vérification" = LLM audite LLM | "Vérification" = sources déterministes |
| "Mémoire partagée" = bulletin inter-agents | "Mémoire partagée" = journal.md par dossier |

---

## DÉCOUVERTES PENDANT RÉÉCRITURE — 2026-04-10

**D1 — Gemma 4 E2B/E4B : disponibilité Ollama à confirmer.**  
Gemma 4 annoncé par Google mais disponibilité en build stable Ollama avec quantisation Q4 à confirmer avant de le verrouiller. Fallback documenté : Qwen3:8B (déjà dans le repo, latence et RAM connues).

**D2 — Conflit apparent entre Règle 17 (archétypes) et nouvelle architecture.**  
Le Manifeste (Règle 17) décrit des agents avec identités professionnelles. Ces identités deviennent les prompts système des agents contraints. La règle reste applicable — la forme change. À documenter par un commentaire dans chaque fichier prompt.

**D3 — Règle 3 (chargement paresseux) à adapter.**  
La Règle 3 s'applique au niveau des secteurs (juridique/comptable) au premier lancement, pas au niveau des modèles (E2B/E4B qui suivent la tâche, pas le choix utilisateur). À documenter dans l'onboarding.

**D4 — Légifrance PISTE API : conditions d'accès à clarifier avant Jalon 2.**  
API PISTE nécessite inscription. Question : compte utilisateur ou clé partagée Lucie ? Impact sur l'onboarding. À trancher avant de commencer le Jalon 2.

**D5 — Schéma JSON de la base curatée à figer avant Jalon 2.**  
Le Retriever et le Vérificateur consomment le même format d'entrée. Si le schéma change entre Jalon 1 et Jalon 2, les deux agents sont à mettre à jour simultanément. Définir le schéma dès que possible — idéalement avant d'implémenter le premier agent.

**D6 — Tests d'injection déguisée à inclure dans Jalon 3.**  
La clause de refus hors-scope est une défense contre prompt injection. Les tests doivent inclure des injections déguisées en requêtes légitimes, pas seulement des requêtes clairement hors domaine.

**D7 — Décision architecturale du 2026-04-10 : base curatée pré-indexée.**  
Mathieu a décidé d'ajouter une base de connaissances curatée locale comme pilier de performance. Motif double : (1) levier de vitesse sans tricher — le LLM synthétise au lieu d'explorer, gain estimé de 30-50% sur le budget tokens utiles ; (2) moat transférable — l'index est un actif durable que Lucie cumule dans le temps, contrairement à l'ancienne architecture orchestrale qui ne produisait pas d'actif cumulatif. Cette décision est cohérente avec l'architecture mono-process et agents contraints décidée le même jour.

**D8 — Journal.md doit avoir un schéma figé avant Jalon 2.**  
Le routeur lit le journal pour décider du dispatch. Si le format Markdown des entrées d'agents change en cours de route, le routeur doit être mis à jour simultanément. Définir le schéma (sections obligatoires, format des entrées par agent) comme contrainte du Jalon 2, pas du Jalon 3.

**D9 — Décision architecturale du 2026-04-10 : couche de réflexion et auto-amélioration.**  
Mathieu a décidé d'ajouter une couche de réflexion exploitant les temps morts de l'E4B. Motif double : (1) exploiter le temps d'inactivité de l'E4B qui dort en RAM entre sessions sans produire de valeur ; (2) mettre en œuvre concrètement le pilier "path compression par apprentissage" de la roadmap long terme. Les prompts améliorés progressivement narrowent la distribution de sortie des agents, les fast-paths du routeur deviennent plus fiables, et Lucie devient non-remplaçable pour SON utilisateur après quelques mois d'usage. La ligne rouge absolue : le Réflecteur ne peut jamais modifier un prompt sans validation humaine explicite — structurellement enforced par le versioning des prompts en fichiers séparés.

**D10 — Interaction entre base curatée et couche réflexion à penser.**  
La couche réflexion peut identifier des lacunes dans la base curatée ("Retriever retourne no_source_found trop souvent sur droit URSSAF"). Le Réflecteur pourrait donc proposer non seulement des améliorations de prompt mais aussi des additions à la base curatée. Ce cas d'usage n'est pas documenté dans la spec v2.3 — à trancher avant d'implémenter le Réflecteur (Jalon 3 ou Jalon 4 ?).

**D11 — Décisions architecturales du 2026-04-10 (4e brief) : offline-first + quotidien + arbre hiérarchique + stratégie étroite-profonde.**  
Quatre décisions prises simultanément : (1) garantie offline-first actée explicitement — aucun agent runtime ne peut déclencher de connexion réseau, la séparation batch/runtime est la garantie architecturale ; (2) refresh quotidien plutôt qu'hebdomadaire — dans le juridique et le comptable, 6 jours de retard est un risque professionnel ; (3) arbre hiérarchique `profession/client_type/matière/sous-matière` à la place d'une table plate — le Retriever devient un marcheur d'arbre déterministe, plus précis et plus rapide ; (4) stratégie étroite-profonde : 8-10 intersections magistralement couvertes valent mieux que 40 couvertes médiocrement pour tenir août 2026.

**D12 — Prudhommes comme PoC initial : vérifier la disponibilité des sources.**  
L'intersection `avocat/entreprise/contentieux_social/prudhommes/` est proposée comme preuve de concept initiale. Avant de commencer, vérifier que les sources clés (Cass. Soc. récents, articles L.1232-L.1243, procédure CPH) sont disponibles gratuitement sur JuriCA et Légifrance sans abonnement. Si certains arrêts de principe ne sont accessibles que via Lexbase ou Doctrine, documenter l'écart avant de commencer la construction de la feuille.
