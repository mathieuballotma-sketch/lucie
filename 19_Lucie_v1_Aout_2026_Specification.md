# Lucie v1 — Spécification technique
## Cible : Août 2026

**Version** : 3.0 — périmètre v1 resserré  
**Date** : 2026-04-10  
**Auteur** : Mathieu Bellot  
**Statut** : Document de travail — à tenir à jour jusqu'au lancement

> Ce document décrit ce que Lucie v1 sera réellement. Tout ce qui n'est pas mentionné ici est post-launch. L'annexe liste les items reportés avec leur justification.

---

## 1. Ce que Lucie v1 est

**Un seul processus macOS.** Application native PyObjC, un unique processus Python. Pas de microservices, pas de workers séparés.

**Un seul modèle local.** Gemma 4 via Ollama, taille à confirmer par bench (E2B ou E4B). Un seul modèle actif à la fois. Zéro appel API cloud.

**Un routeur déterministe en code.** La classification de l'intention utilisateur — est-ce une recherche juridique ? Une rédaction ? Une extraction de document ? — est faite par des règles Python : regex, dictionnaire de mots-clés, fuzzy matching. Aucun LLM n'intervient dans le routage. Le routeur est testable ligne par ligne.

**Quatre agents, chacun contraint par un prompt statique.** Un agent Lucie v1 est un rôle : un prompt système court (≤ 300 tokens) + un appel au modèle local. Chaque agent a un domaine défini. Si la requête sort de ce domaine, il retourne `out_of_scope` et le routeur reprend la main. Les quatre rôles :

| Agent | Rôle | Refuse si |
|---|---|---|
| Lecteur | Extraire les données structurées d'un document fourni | On lui demande de rédiger ou juger |
| Retriever | Chercher dans la base curatée locale | On lui demande de rédiger ou de fetcher |
| Rédacteur | Produire un livrable depuis les sources dans le contexte | Les sources nécessaires manquent |
| Vérificateur | Confronter le livrable à des sources déterministes | On lui demande de rédiger |

**Une base de connaissances curatée locale.** 2 à 3 intersections profession×matière pour v1 — voir §4. Le Retriever y fait un lookup déterministe. Aucune exploration web pendant une session.

**Un journal par dossier client.** `~/Lucie/Dossiers/{client}/journal.md` — Markdown lisible, chiffré au repos, append-only. Trace tout ce que chaque agent fait.

**La vérification externe n'est pas optionnelle (Règle 19).** Toute affirmation factuelle dans un livrable est confrontée à une source déterministe avant d'être montrée à l'utilisateur.

---

## 2. Ce que Lucie v1 n'est pas

- Pas d'agents parallèles ou distribués
- Pas de plusieurs modèles actifs simultanément
- Pas de recherche web ouverte en session (uniquement base curatée locale)
- Pas de fetch web à la demande pendant une session (post-launch)
- Pas de couche d'apprentissage ou de réflexion automatique (post-launch)
- Pas d'outil généraliste — deux professions, 2-3 matières, c'est tout

---

## 3. Architecture runtime

```
Utilisateur → HUD macOS (PyObjC)
     │
     ▼
Routeur déterministe (code Python)
     │ lit journal.md · classifie · dispatche
     │
     ├─► Lecteur ──── extrait données du document fourni
     ├─► Retriever ── lookup dans ~/Lucie/Knowledge/ → sources
     ├─► Rédacteur ── produit le livrable depuis les sources
     └─► Vérificateur ─ compare livrable aux sources déterministes
     │
     ▼
Journal dossier client (journal.md, chiffré)
     │
     ▼
Livrable → Utilisateur
```

L'exécution est **strictement séquentielle**. Les agents ne se parlent pas entre eux. Ils écrivent dans `journal.md` ; le routeur lit `journal.md` entre chaque étape.

---

## 4. Base de connaissances curatée

### Principe

Au lieu de faire explorer le modèle dans le vide, Lucie lui sert des sources officielles pré-sélectionnées et pré-téléchargées. Le modèle synthétise au lieu d'explorer — gain de vitesse et de précision.

### Périmètre v1 strict : 2-3 intersections

On ne crée une intersection que si elle contient du vrai contenu. Pour v1 :

| Intersection | Sources à couvrir |
|---|---|
| `avocat/prudhommes` | Cass. Soc. — arrêts de principe, art. L.1232-L.1243 Code du travail, procédure CPH |
| `avocat/baux_commerciaux` | Cass. Com. pertinents, art. L.145-1 à L.145-60 Code de commerce |
| `comptable/tva` | BOFiP TVA, art. 256 à 298 CGI, bulletins DGFiP récents |

<!-- À TRANCHER: sélection finale des 2-3 intersections avec les pilotes bêta (avocat + expert-comptable) avant Jalon 2. Ces exemples sont une proposition, pas une décision. -->

### Structure des fichiers

```
~/Lucie/Knowledge/
    avocat/
        prudhommes/
            arrets_principe.md      # 5-10 arrêts clés avec extraits
            articles_code.md        # textes consolidés L.1232-L.1243
            procedure.md            # étapes CPH, délais, formulaires
        baux_commerciaux/
            ...
    comptable/
        tva/
            ...
```

Chaque fichier est du Markdown avec les champs : source officielle, URL, extrait, date de dernière vérification, statut (en vigueur / modifié / abrogé).

**Ce que la base n'est pas :** elle n'est pas exhaustive. Elle couvre bien 2-3 cas fréquents, pas tout le droit français. Si une requête sort des intersections disponibles, le Retriever retourne `no_source_found` et Lucie le dit à l'utilisateur.

### Refresh hebdomadaire

Un script Python séparé (`scripts/refresh_knowledge.py`) tourne une fois par semaine via `launchd`. Il scanne les sources officielles (Légifrance, BOFiP, URSSAF), met à jour les fichiers Markdown, génère un digest `~/Lucie/Knowledge/digest_YYYY-MM-DD.md`.

Règle stricte : **ce script ne tourne jamais pendant une session utilisateur active.** Il n'a aucun contact avec le processus Lucie.

---

## 5. Modes réseau v1

**Mode 1 — Session (par défaut, toujours actif) :** Lucie travaille hors ligne. Aucun appel réseau. La base curatée locale suffit. Fonctionne en salle d'audience, en cabinet rural, dans le train. C'est le mode principal.

**Mode 2 — Background enrichment (hebdomadaire, automatique) :** Le script de refresh tourne la nuit, quand le Mac est disponible et connecté. Aucune interaction utilisateur. Aucune fenêtre visible.

Le Mode 3 (fetch à la demande avec consentement pendant une session) est post-launch — voir Annexe.

---

## 6. Comportement d'aveu honnête

Quand Lucie ne trouve pas une source dans sa base locale, elle **refuse de rédiger à l'aveugle** sur ce point précis.

Message type :
> "Je n'ai pas cette source dans votre base locale. Je préfère ne pas rédiger à l'aveugle sur ce point. Voulez-vous que je note le manque et continue avec un trou explicite dans le livrable ?"

**Options proposées à l'utilisateur :**
- Noter le manque → livrable produit avec `[SOURCE MANQUANTE — à compléter]`
- Fournir la source manuellement → Lucie l'intègre pour la session
- Abandonner ce point → livrable sans la section concernée

Ce comportement est un avantage concurrentiel direct : ChatGPT et Gemini comblent les trous avec des références inventées. Lucie préfère admettre le manque. La confiance dans le livrable final est absolue.

Chaque aveu est loggé dans `journal.md`.

---

## 7. Règle 19 — Vérification externe obligatoire

Toute affirmation factuelle dans un livrable est confrontée à une source externe déterministe avant d'être montrée à l'utilisateur. Ce n'est pas optionnel, ce n'est pas un bonus.

**Vérificateurs branchés en v1 :**

| Type d'affirmation | Vérificateur |
|---|---|
| Article de loi cité | Base curatée locale (hash + date de version) |
| Jurisprudence citée | Base curatée locale (numéro d'arrêt + source) |
| Code Python produit | bandit + semgrep (subprocess local) |
| Code Python exécutable | Sandbox Python isolée (pas de réseau) |

Si une affirmation ne peut pas être vérifiée : elle est marquée `[NON VÉRIFIÉ]` dans le livrable, jamais présentée comme vraie.

Le Vérificateur n'est pas un LLM qui "juge" un autre LLM — c'est du code qui compare à des sources déterministes.

---

## 8. Journal chiffré local

Chaque dossier client a son journal : `~/Lucie/Dossiers/{client}/journal.md`

Chiffrement au repos : AES-256 via `cryptography.fernet`. La clé de chiffrement est stockée dans le Keychain macOS, jamais en clair sur le disque.

Le journal enregistre, en append uniquement :
- Chaque requête utilisateur (timestamp + texte)
- Chaque agent invoqué (rôle + durée)
- Les sources consultées + statut de vérification
- Le livrable produit (ou chemin vers le fichier)
- Les aveux honnêtes (manques détectés)

Le journal est lisible par l'utilisateur après déchiffrement. Il n'est jamais synchronisé hors du Mac sans accord explicite.

---

## 9. Contraintes hardware

**Modèle :** Gemma 4 via Ollama. Taille à confirmer par bench (E2B ~2-3 Go RAM / E4B ~4-5 Go RAM). La décision est bloquante pour le Jalon 1.

**Plancher hardware :** à définir après bench. Proposition à valider : M2 8 Go minimum.

**Budget RAM estimé (à confirmer) :**
- Idle (Lucie + HUD) : ~200 Mo
- Session active avec modèle chargé : 4-8 Go selon la taille retenue
- Pic session (modèle + base chargée + journal) : < 10 Go

---

## 10. Jalons août 2026

Critère d'acceptation binaire pour chaque livrable — passe ou ne passe pas.

### Jalon 1 — Mai 2026 : Socle

| Livrable | Critère |
|---|---|
| Bench Gemma 4 | Rapport : latence, RAM, décision E2B/E4B documentée |
| Routeur déterministe | 95% classification correcte sur 100 requêtes annotées à la main |
| HUD macOS minimal | Saisie texte → réponse affichée, sans crash sur 30 min |
| Ollama + modèle retenu | Réponse Agent Lecteur en < 10s sur M-series |

### Jalon 2 — Juin 2026 : Pipeline complet

| Livrable | Critère |
|---|---|
| Base curatée v0 | 1 intersection complète (ex : avocat/prudhommes), 10-15 fichiers sources |
| Agent Lecteur | Extraction correcte sur 10 documents de test |
| Agent Retriever | 10 lookups corrects dans la base v0 |
| Journal.md fonctionnel | Reprise de session sur dossier fermé 48h sans perte |

### Jalon 3 — Juillet 2026 : Rédaction + vérification

| Livrable | Critère |
|---|---|
| Agent Rédacteur | Mise en demeure type validée par un avocat |
| Agent Vérificateur | 0 faux positif "confirmé" sur 10 tests de divergence connue |
| Aveu honnête fonctionnel | 10 tests `no_source_found` → comportement correct dans 100% des cas |
| Règle 19 complète | Aucune affirmation non vérifiée présentée comme vraie dans 20 sessions |

### Jalon 4 — Août 2026 : Beta fermée

| Livrable | Critère |
|---|---|
| 2 utilisateurs réels | 1 avocat + 1 expert-comptable, 2 semaines sur dossiers réels |
| Zéro hallucination non signalée | Audit 50 sessions : toutes les erreurs factuelles marquées ou bloquées |
| Documentation utilisateur | Prise en main sans assistance < 20 min |
| Packaging macOS | `.app` installable sur machine vierge sans CLI |

---

## Annexe — Post-launch backlog

Ces items sont des décisions délibérées de report. Ils ne sont pas abandonnés — ils sont hors périmètre v1 parce qu'ils alourdiraient l'implémentation sans bénéfice mesurable pour les deux premiers utilisateurs réels.

| Item reporté | Justification |
|---|---|
| Deux tailles de modèle simultanées (E2B + E4B) | Un seul modèle simplifie le bench, le packaging et la gestion mémoire. À revisiter si le bench montre une dégradation qualité rédaction inacceptable avec le modèle unique. |
| Refresh quotidien | Hebdomadaire suffit pour v1 beta. La plupart des arrêts et textes que les pilotes utiliseront sont des textes de référence stables, pas des publications du jour. |
| Mode 3 — fetch à la demande avec consentement | Ajoute un dialogue UX + navigateur headless WebKit + gestion des états réseau. Trop de surface pour v1. L'aveu honnête couvre le cas sans complexité. |
| Navigateur headless WebKit | Dépendance lourde (Playwright ou pyobjc WKWebView) inutile tant que Mode 3 est hors scope. |
| Couche de réflexion (notes d'agents + Réflecteur) | Valeur réelle mais zéro impact sur v1 à 2 utilisateurs. Ré-évaluer à v1.5 avec données réelles de sessions. |
| Prompts versionnés + rollback + rotation bi-hebdo | Nécessite des tests de régression par prompt. Trop tôt sans données d'usage réel. |
| Dossier `common/` mutualisé entre professions | Ajoute complexité de l'index de références. Pas nécessaire avec 2-3 intersections. |
| Expansion au-delà de 3 intersections | À décider avec les pilotes post-beta selon leurs besoins réels. |
| Path compression runtime | Optimisation de performance. Prématurée sans mesures réelles de latence en production. |
| Journal chiffré partagé entre professionnels | Multi-utilisateurs hors périmètre v1. |

---

## DÉCOUVERTES PENDANT RÉÉCRITURE — 2026-04-10

**D1 — La décision de resserrement du 2026-04-10.**  
Après cinq rounds de briefs successifs, la spec avait dérivé à > 1 300 lignes et 24 sections. Mathieu a acté le resserrement : v1 = périmètre minimal viable pour deux utilisateurs réels en août 2026. Tout le reste passe en backlog. Cette décision est la plus importante du jour — elle rend le lancement réaliste.

**D2 — Taille du modèle à décider par bench avant tout le reste.**  
La décision E2B vs E4B est bloquante pour les Jalons 1 et 2 (structure de la session active, budget RAM, plancher hardware). Elle doit être faite avant d'implémenter quoi que ce soit d'autre.

**D3 — Sélection des intersections à valider avec les pilotes.**  
Les exemples (prudhommes, baux, TVA) sont une proposition. La sélection finale dépend des besoins réels des deux utilisateurs pilotes. À confirmer avant Jalon 2.

**D4 — Schéma journal.md à figer avant Jalon 2.**  
Le routeur lit le journal pour décider du dispatch. Si le format change en cours d'implémentation, le routeur doit être mis à jour simultanément. Figer le schéma Markdown (sections, format des entrées) comme livrable du Jalon 1 ou pré-Jalon 2.
