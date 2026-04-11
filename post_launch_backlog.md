# Lucie — Post-launch backlog
**Date de création :** 2026-04-10  
**Statut :** Items délibérément reportés hors v1

Ces items sont des décisions de design, pas des oublis. Ils seront reconsidérés après la beta fermée (août 2026) sur la base de données d'usage réelles.

---

## Couche réseau avancée

**Mode 3 — Fetch à la demande avec consentement utilisateur**  
Pendant une session, si une source manque et que le wifi est disponible, proposer à l'utilisateur de la fetcher en temps réel.  
_Pourquoi reporté :_ ajoute un dialogue UX + navigateur headless + gestion d'états réseau. L'aveu honnête (déjà dans v1) couvre le cas sans complexité additionnelle.

**Navigateur headless WebKit (Playwright ou pyobjc WKWebView)**  
Moteur de rendu identique à Safari pour le fetch de sources officielles.  
_Pourquoi reporté :_ dépendance lourde inutile tant que Mode 3 est hors scope.

**Refresh quotidien de la base curatée**  
Passer le script de refresh de hebdomadaire à nocturne quotidien.  
_Pourquoi reporté :_ hebdomadaire suffit pour les textes de référence stables utilisés en beta. Ré-évaluer si les pilotes travaillent sur des dossiers d'actualité jurisprudentielle.

---

## Modèle et performance

**Deux tailles de modèle (E2B pour rôles courts, E4B pour rédaction)**  
Assigner E2B aux agents Lecteur/Retriever/Vérificateur et E4B au Rédacteur.  
_Pourquoi reporté :_ un seul modèle simplifie bench, packaging et gestion mémoire. À revisiter si le bench montre une dégradation qualité rédaction inacceptable avec le modèle unique.

**Path compression runtime**  
Optimisation des fast-paths du routeur sur la base des patterns observés.  
_Pourquoi reporté :_ prématurée sans mesures réelles de latence en production avec utilisateurs réels.

---

## Couche réflexion et apprentissage

**Notes de réflexion anonymisées par agent**  
Chaque agent écrit une note courte après chaque tâche (`~/Lucie/Reflections/`).  
_Pourquoi reporté :_ zéro impact sur v1 à 2 utilisateurs. Ré-évaluer à v1.5 avec données réelles.

**Réflecteur d'inactivité (E4B en idle)**  
Lecture des notes de réflexion + proposition d'améliorations de prompt pendant les temps morts.  
_Pourquoi reporté :_ dépend des notes d'agents (ci-dessus). Valeur réelle mais non prioritaire pour beta.

**Prompts agents versionnés + rollback + rotation bi-hebdomadaire**  
Versioning des prompts système comme du code, avec tests de régression.  
_Pourquoi reporté :_ nécessite des tests de régression par prompt. Trop tôt sans données d'usage réel pour valider les critères d'amélioration.

---

## Base de connaissances

**Dossier `common/` mutualisé entre professions**  
Sources transverses (art. 1240 Code civil, etc.) référencées depuis plusieurs intersections sans duplication.  
_Pourquoi reporté :_ pas nécessaire avec 2-3 intersections. Ré-évaluer quand l'arbre dépasse 10 feuilles.

**Expansion au-delà de 3 intersections**  
Couvrir plus de matières (droit de la famille, pénal des affaires, IS/BIC, etc.).  
_Pourquoi reporté :_ à décider avec les pilotes post-beta selon leurs besoins réels. Risque de diluer l'énergie loin de la profondeur sur les 2-3 intersections v1.

---

## Multi-utilisateurs et partage

**Journal chiffré partagé entre plusieurs professionnels d'un cabinet**  
Synchronisation des dossiers entre plusieurs instances de Lucie.  
_Pourquoi reporté :_ multi-utilisateurs hors périmètre v1. Architecture à repenser entièrement (identité, permissions, sync).

---

## Infra et déploiement

**CI/CD + coverage report automatisé**  
Pipeline de tests automatisés à chaque commit.  
_Pourquoi reporté :_ utile mais pas bloquant pour une beta fermée à 2 utilisateurs.

**Licensing / clé produit**  
Mécanisme d'activation pour la distribution commerciale.  
_Pourquoi reporté :_ nécessaire pour la commercialisation, inutile pour la beta fermée.
