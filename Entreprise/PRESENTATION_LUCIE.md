# Lucie — L'IA personnelle qui tourne sur votre Mac

---

## En une phrase

Lucie est un assistant IA qui tourne **entièrement sur votre machine**, sans cloud, sans abonnement, sans que vos données ne quittent jamais votre ordinateur.

---

## Le problème qu'on résout

Aujourd'hui, utiliser l'IA c'est :
- Envoyer ses fichiers, ses conversations, ses habitudes à des serveurs qu'on ne contrôle pas
- Payer un abonnement mensuel pour un outil générique qui ne vous connaît pas
- Dépendre d'une connexion internet pour réfléchir
- Faire confiance aveuglément à une entreprise avec ses données les plus sensibles

**Lucie change ça.** L'IA tourne chez vous. Point.

---

## Ce que Lucie fait concrètement

**Aujourd'hui, Lucie sait :**

- Lire, créer et organiser vos fichiers (Word, PDF, Excel, texte)
- Chercher dans vos documents avec une compréhension sémantique (pas juste des mots-clés)
- Planifier des tâches et les décomposer en étapes
- Surveiller la sécurité de votre système en arrière-plan
- Contrôler votre Mac par commande naturelle (ouvrir des apps, automatiser des actions)
- Générer du contenu, résumer, traduire
- Apprendre vos habitudes et s'adapter à vous au fil du temps
- Communiquer entre plusieurs Macs en pair-à-pair (réseau local)

**Tout ça sans internet. Tout ça en local.**

---

## Comment c'est possible

Lucie repose sur une architecture multi-agents inspirée du cerveau humain :

**Le cerveau** — Un orchestrateur central (FrontalCortex) reçoit vos demandes et les route vers l'agent le plus compétent, comme un cortex préfrontal qui décide où envoyer l'attention.

**Les agents** — 15+ agents spécialisés, chacun expert dans son domaine. Ils ne se chargent en mémoire que quand vous en avez besoin (lazy loading), comme des neurones qui s'activent à la demande.

**La mémoire** — Un graphe de mémoire avec neuroplasticité (les connexions se renforcent quand elles sont utiles, s'affaiblissent sinon). Plus vous utilisez Lucie, plus elle vous comprend.

**La sécurité** — Un système ActionGate à 3 niveaux vérifie chaque action avant exécution. Les opérations sensibles (supprimer un fichier, exécuter une commande) demandent confirmation.

**Le moteur** — Ollama et MLX pour faire tourner les modèles d'IA directement sur la puce Apple Silicon, sans serveur distant.

---

## Ce qui rend Lucie unique

| | Lucie | ChatGPT / Claude / Gemini | Siri | LM Studio / Jan.ai |
|---|---|---|---|---|
| **100% local** | ✅ | ❌ Cloud | ❌ Cloud | ✅ |
| **Multi-agents** | ✅ 15+ agents | ❌ Un seul modèle | ❌ | ❌ |
| **Mémoire persistante** | ✅ Graphe hebbien | ❌ Reset à chaque session | ❌ | ❌ |
| **Contrôle du Mac** | ✅ Natif PyObjC | ❌ | Partiel | ❌ |
| **Sécurité vérifiable** | ✅ Open-source | ❌ Boîte noire | ❌ | Partiel |
| **Apprend de vous** | ✅ | ❌ | ❌ | ❌ |
| **Fonctionne hors-ligne** | ✅ | ❌ | ❌ | ✅ |
| **Interface native macOS** | ✅ HUD Cocoa | ❌ Web/Electron | ✅ | ❌ |

**Aucun concurrent ne combine tous ces éléments.** C'est là que Lucie se positionne : à l'intersection exacte de la vie privée, de l'intelligence et de l'intégration native.

---

## La vision

### Court terme (3-6 mois)
Lucie devient l'assistant Mac que tout le monde attendait. Open-source, gratuit, avec un tier supporter pour ceux qui veulent contribuer. Lancement sur GitHub, Product Hunt, Hacker News.

### Moyen terme (6-18 mois)
- Marketplace d'agents (comme les extensions VS Code — la communauté crée ses propres agents)
- Réseau P2P sécurisé entre Macs (partager des workflows entre collègues, en local)
- Mémoire contextuelle profonde (Lucie anticipe vos besoins avant que vous les exprimiez)
- Gestion intelligente de l'énergie (s'adapte à la batterie, à la température, à votre usage)

### Long terme (18+ mois)
- **Modèle LLM propriétaire** optimisé pour Apple Silicon — un modèle 3B spécialisé qui bat les modèles 70B généralistes sur les tâches Lucie
- Écosystème complet : Lucie devient la couche d'intelligence de votre Mac
- Expansion entreprise : déploiement flottes Mac avec administration centralisée

---

## Pourquoi maintenant

**La fenêtre est ouverte pour 12-18 mois.**

1. **Apple Intelligence déçoit.** Siri reste limité, les fonctionnalités IA d'Apple arrivent lentement et avec des taux de fiabilité autour de 67%. Les utilisateurs Mac veulent mieux.

2. **La défiance envers le cloud explose.** 90% des utilisateurs ne font pas confiance à l'IA avec leurs données personnelles. L'EU AI Act (application complète 2026-2027) renforce cette tendance.

3. **Le hardware est prêt.** Les puces Apple Silicon (M1-M4) peuvent faire tourner des modèles 7B-13B en local avec des performances acceptables. C'était impossible il y a 2 ans.

4. **Personne n'occupe cette place.** Les outils IA locaux actuels sont soit des chatbots basiques (LM Studio, Jan.ai), soit des outils cloud déguisés. Aucun n'offre un vrai assistant multi-agents natif macOS.

---

## Le moat (ce qui protège Lucie)

**1. La mémoire personnelle** — Plus vous utilisez Lucie, plus elle vous connaît. Après 6 mois d'utilisation, migrer vers un concurrent signifie perdre tout ce contexte. C'est le même mécanisme que quitte Apple Photos après 10 ans de tri.

**2. L'intégration macOS profonde** — PyObjC donne accès aux APIs natives Apple que les apps Electron ne peuvent pas toucher. Notifications système, contrôle d'apps, Finder, Spotlight — Lucie fait partie du Mac.

**3. La communauté open-source** — Chaque contributeur qui crée un agent, améliore le code, ou écrit de la documentation rend Lucie plus difficile à remplacer. C'est le modèle Linux.

**4. Le réseau P2P** — Quand plusieurs Macs font tourner Lucie, ils peuvent collaborer. Plus il y a d'utilisateurs, plus le réseau est utile. Effet réseau classique.

---

## L'équipe

**Mathieu Bellot, 18 ans — Fondateur & Lead Developer**

Développeur autodidacte qui a construit Lucie seul en parallèle de ses études. Architecture multi-agents, brain bio-inspiré, 15+ agents, 168 tests, pipeline CI complet — le tout en solo.

La capacité à livrer un système de cette complexité seul démontre une vélocité de développement exceptionnelle et une compréhension profonde des systèmes distribués, de l'IA appliquée et de l'ingénierie logicielle.

---

## État technique actuel

- **Code** : ~70 fichiers Python, architecture modulaire propre
- **Qualité** : ruff 0 erreur, 168/176 tests passent, typage strict en cours
- **Agents opérationnels** : 15+ (fichiers, sécurité, planification, création, contrôle Mac, documents, rappels, recherche, traduction, résumé...)
- **Infrastructure** : EventBus async, FAISS vectoriel, SQLite WAL, CircuitBreaker, HUD natif Cocoa
- **Licence** : Open-source (à définir MIT ou AGPLv3)

---

## Ce que Lucie représente pour un acquéreur

**Pour un éditeur de logiciels Mac :** Une brique d'intelligence locale prête à intégrer, avec une architecture extensible et une communauté naissante.

**Pour une entreprise IA :** Un positionnement privacy-first unique, une architecture bio-inspirée brevetable, et un accès au marché macOS (100M+ utilisateurs actifs).

**Pour un fonds d'investissement :** Un projet early-stage avec un avantage technique réel, un marché en pleine expansion (IA on-device : 33 Mds USD en 2026, CAGR ~25%), et un fondateur qui a prouvé sa capacité d'exécution.

---

*Lucie n'est pas juste un chatbot local. C'est le début d'une couche d'intelligence personnelle pour le Mac — une IA qui vous appartient vraiment.*
