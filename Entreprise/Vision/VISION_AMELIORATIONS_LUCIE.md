# VISION & AMÉLIORATIONS LUCIE
**Dernière mise à jour : 2026-03-20**
**Objectif : Faire de Lucie le meilleur agent local au monde**

---

## 🔴 CRITIQUES — À faire AVANT la bêta

### 1. Merger les worktrees + fixes critiques
- wizardly-almeida → sécurité P2P (HMAC, subprocess_exec)
- quirky-spence → uvloop + SQLite WAL dans rag.py
- lucid-dubinsky → LICENCES_MODELES.md + model_router
- Fix pydantic.v1 violation dans command_api.py
- P2P exposé sur 0.0.0.0 → passer à 127.0.0.1
- Nettoyer les 29 worktrees orphelins
- Supprimer les 40 fichiers .bak

### 2. ActionGate — Contrôle d'exécution centralisé (PRIORITÉ HAUTE)
- **Principe** : Aucun agent ne touche au système directement. Tout passe par ActionGate.
- **Architecture** : ActionGate est un PAIR de FrontalCortex, pas un subordonné. FrontalCortex = réflexion, ActionGate = exécution.
- **3 niveaux de risque** :
  - Niveau 1 : exécute + logge + notifie (actions safe, undo possible)
  - Niveau 2 : preview + attente validation utilisateur + exécute + logge
  - Niveau 3 : preview + double confirmation + exécute + logge (irréversible)
- **Interface standardisée** ActionRequest pour TOUS les agents :
  ```json
  {"agent": "EmailAgent", "action_type": "send_email", "risk_level": 2, "preview": {...}, "reversible": false}
  ```
- **Fonctionnalités** :
  - Registre de risques par type d'action (fichier, email, système, réseau)
  - File d'attente des actions en attente de validation
  - Historique complet consultable ("relevé bancaire" de Lucie)
  - Système d'undo pour actions niveau 1
  - Score de confiance par catégorie (semi-auto après 100 validations consécutives)
- **Règle absolue** : AUCUNE exception, AUCUN fast-track. Même les actions internes (réorg mémoire) passent par ActionGate en mode logging.
- **Implémenter AVANT les prochains agents.** Brancher en premier sur FileAgent, ComputerControlAgent, CreatorAgent (risque fichiers = valeur démo max).
- **Pourquoi maintenant** : Si on attend, il faudra reprendre 40 agents un par un → semaines de refactoring. C'est la "constitution" du système.

### 3. Plugin/Skill System extensible
- OpenClaw a 3000+ skills communautaires
- Format : YAML/JSON par agent avec schema, description, déclencheurs, code Python
- Builder no-code (comme AnythingLLM)
- Priorité : sans plugins, Lucie est un produit fermé

### 3. API OpenAI-compatible sur localhost
- LocalAI et Jan.ai exposent /v1/chat/completions
- Standard pour apps tierces
- Session non réalisée — À coder

### 4. UI minimale fonctionnelle
- Menu bar macOS + historique conversations + status agents
- Msty = référence Apple-quality
- HUD Cocoa actuel = insuffisant pour le grand public

### 5. Installation en 1 commande
```bash
brew install lucie
# ou
curl -fsSL https://lucie.ai/install | sh
```
- Si > 2 minutes d'install → perte de 80% des curieux

### 6. Spécialisation des modèles LLM par agent
- Chaque agent utilise le modèle le plus adapté à sa tâche
- Recherche à faire : quel modèle pour quel agent
- Supprimer les modèles inutiles, garder ceux qui correspondent

### 7. Conformité RGPD complète
- Module app/compliance/ à créer
- Templates métier à créer (app/templates/)
- Vérifier chaque point RGPD pour être livrable

### 8. Protection IP / Brevets
- Étude FTO sur brevets critiques (US12111859B2, US12481517, US20250259042A1)
- Si revendications couvrent orchestration cloud → Lucie (locale) hors scope
- Licence BSL 1.1 à vérifier

---

## 🟡 IMPORTANTS — Dans les 3 mois post-lancement

### 9. Automation workflows IFTTT-like local
- "Quand je reçois un mail de [X], résume-le et crée une tâche dans Rappels"
- Format : triggers + conditions + actions en langage naturel
- Rivaliser avec n8n/Make/Zapier mais en 100% local

### 10. Multi-modal complet
- Vision écran ✅ déjà là
- Analyse images/documents via LLaVA local
- Transcription audio Whisper.cpp
- Génération images Stable Diffusion (optionnel)

### 11. Mémoire persistante structurée
- FAISS ✅ déjà là
- Mémoire épisodique SQLite ✅ déjà là
- À améliorer : MemoryGraph Hebbien (dans worktree, pas mergé)

### 12. Dashboard de monitoring
- Quels agents tournent, latence, RAM/CPU, logs
- Utile debug + impressionne les techniques

### 13. Intégration Shortcuts macOS
- Shortcuts Apple → déclencher agents Lucie
- Interopérabilité avec écosystème Apple existant

---

## 🟢 NICE-TO-HAVE — 6 mois+

### 14. Mode collaboratif local multi-utilisateur
- Plusieurs users sur même réseau local → même Lucie

### 15. Marketplace d'agents communautaires
- Comme Agenthub LocalAI / skills OpenClaw
- Commission 0% les 6 premiers mois → 15% ensuite

### 16. Voice control (déprioritisé par Mathieu)
- Wake word "Hey Lucie" → code fait (worktree)
- TTS Kokoro → recherche faite, pas codé
- Mettre en option, pas en feature principale

### 17. Support multi-plateforme (Windows + Linux)
- Choix stratégique actuel : macOS only (profondeur > largeur)
- À envisager post-succès macOS

### 18. DocAgent — Documentation automatique
- Chaque fonction codée → doc brute en vrac → agent transforme en README.md, tutoriels propres
- Réduit le temps de documentation de 80%
- Priorité : intégrer au workflow de dev dès la stabilisation

### 19. FAQ intelligent local sur le site
- Bot de recherche basé sur la doc Lucie (RAG local)
- 80% des questions utilisateurs résolues sans intervention humaine
- Réduit le support, améliore l'onboarding
- Implémentation : RAG existant + interface web simple

---

## 📊 POSITIONNEMENT STRATÉGIQUE

### Faiblesses concurrents à exploiter
- GPT4All : pas d'agents, juste chat
- Jan.ai : pas d'automation, juste inférence
- LM Studio : pas de contrôle système, juste playground
- AnythingLLM : RAG only, pas multi-agent
- OpenClaw : cloud-first, pas local-first
- n8n/Make : pas d'IA locale intégrée

### Avantage unique Lucie
- SEUL à combiner : multi-agent + contrôle macOS natif + 100% local + automation workflows + mémoire persistante
- Aucun concurrent ne fait tout ça ensemble en local

### Stratégie lancement
- Show HN : "28 AI agents that control your Mac natively, 100% offline"
- r/LocalLLaMA : benchmarks + architecture technique
- Twitter thread viral : vidéo 45s de démo
- Product Hunt : 1 semaine après HN
- Discord communautaire dès le lancement
- Build in public : 1 tweet/jour pendant 30 jours

### Risques à surveiller
- Latence Ollama vs LM Studio MLX (LM Studio plus rapide sur Apple Silicon)
- UI/UX en retard vs Msty (présenté par Apple)
- Communauté à construire de zéro (GPT4All : 70K stars)
- Documentation/onboarding doit être parfait

---

## 🧪 RECHERCHES À LANCER

- [ ] Benchmark performance Lucie vs LM Studio vs Jan.ai vs GPT4All (latence, RAM, qualité)
- [ ] Quel modèle pour quel agent (spécialisation LLM)
- [ ] Optimisation latence avec lois physiques/math (moindre action, entropie)
- [ ] Besoins marché : qu'est-ce qui intéresse les gens en agent IA/automatisation
- [ ] FTO brevets détaillée (3 brevets critiques)
- [ ] Anthropic best practices pour productivité Claude Code
- [ ] Comment battre tous les modèles locaux en performance

---

## 🔍 FINDINGS AUDIT 2026-03-20 (Score 5.2/10)

### CRITIQUES identifiés par l'audit
- config.yaml ABSENT du disque (supprimé !) → restaurer depuis .bak3
- requirements.txt déclare sentence-transformers==5.2.3 (devrait être 3.3.1)
- 39 worktrees avec travail NON COMMITTÉ → un `git worktree remove` détruirait tout
- pickle dans prompt_cache.py (6 usages) et executor.py (2 usages) → migrer json
- md5 au lieu de blake2b dans 4 endroits (prompt_cache.py, search_manager.py)
- BaseAgent.ask_llm() sans CircuitBreaker → affecte 15+ agents
- 6 agents jamais instanciés : Feedback, Deception, Wake, ImageDescriber, UIElement, ActionBroker
- StrategistAgent pas de token EventBus, ProfileAgent pas d'event_bus
- 4 agents orphelins sans BaseAgent : Fixer, Analyzer, Writer, Consolidator
- ~20 fichiers Python jamais importés (code mort) : soul/, cyber/, bridges/, demo/
- engine.py modifié dans 8 worktrees, cortex.py dans 6 → conflits merge garantis
- Tests : 9/35 passent (26%), 26 en échec/erreur
- ruff non installé sur la machine

### Ordre de merge recommandé par l'audit
1. wizardly-almeida (sécurité P2P)
2. recursing-cori (CI/CD) + relaxed-lumiere (Build) + quirky-spence (uvloop+WAL)
3. lucid-lederberg (event_bus) + amazing-knuth (engine) + lucid-dubinsky (model_router)
4. romantic-lamport + hungry-heyrovsky + fervent-chebyshev + upbeat-carson (agents)
5. naughty-jennings (HUD) + nervous-shaw (onboarding)
6. charming-hofstadter + suspicious-euclid (tests)

---

## 💡 DÉCOUVERTES EN COURS DE ROUTE
*(Section alimentée automatiquement pendant le travail)*

- sentence-transformers non installé → cache vectoriel désactivé
- Conflit dylib cv2/av → risque crashes sporadiques
- 40 fichiers .bak à nettoyer
- uvloop absent de main → gain perf ~30% sur async
- SQLite WAL absent de rag.py (présent dans episodic_memory et action_broker)
- config.yaml supprimé du disque → backups .bak2 et .bak3 valides
- Modules entiers jamais importés : soul/, cyber/, bridges/, demo/
- WriterAgent sans BaseAgent → agent orphelin
- ProviderManager.generate() sans CircuitBreaker
