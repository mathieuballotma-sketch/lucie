<div align="center">

# ✦ AGENT LUCIE

<p>
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Platform-macOS-000000?style=flat-square&logo=apple&logoColor=white" />
  <img src="https://img.shields.io/badge/Ollama-local_LLM-FF6B35?style=flat-square" />
  <img src="https://img.shields.io/badge/License-MIT-22C55E?style=flat-square" />
  <img src="https://img.shields.io/badge/Status-Active_Development-8B5CF6?style=flat-square" />
  <img src="https://img.shields.io/badge/Asyncio-multi--agent-0EA5E9?style=flat-square" />
</p>

**Assistant IA local et autonome pour macOS.**  
Pipeline multi-agents asynchrone · Cortex adaptatif · Mémoire vectorielle · Système de sécurité intégré

</div>

---

## Vue d'ensemble

Agent Lucie est un assistant IA entièrement local conçu pour macOS. Il repose sur un cortex adaptatif à 9 chemins d'exécution, un pipeline multi-agents asynchrone, et un système de sécurité immunitaire inspiré de la biologie. Toutes les données restent sur la machine de l'utilisateur — aucun appel cloud, aucune dépendance externe à un service tiers.

Le projet est développé en solo, de zéro, avec un niveau de rigueur technique (typage strict, gestion d'erreurs exhaustive, métriques Prometheus) habituellement réservé aux équipes professionnelles.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     HUD natif macOS                          │
│              Interface verre translucide (PyObjC)            │
└─────────────────────────┬────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────┐
│                     FrontalCortex                            │
│                                                              │
│   ┌─────────────────────────────────────────────────────┐   │
│   │              Adaptive Router (9 chemins)            │   │
│   │  cache · nano · speed · balanced · quality ·        │   │
│   │  semantic · direct_action · multi_action · plan     │   │
│   └──────────────────────┬──────────────────────────────┘   │
│                          │                                   │
│   ┌──────────────┐  ┌────▼─────────┐  ┌───────────────┐    │
│   │ Circuit      │  │  EventBus    │  │ PromptCache   │    │
│   │ Breaker LLM  │  │ thread-safe  │  │ sémantique    │    │
│   └──────────────┘  └─────────────┘  └───────────────┘    │
└──────┬──────────────────┬──────────────────┬────────────────┘
       │                  │                  │
┌──────▼──────┐  ┌────────▼───────┐  ┌──────▼──────────────┐
│   Agents    │  │    Mémoire     │  │  Provider Layer     │
│             │  │                │  │                     │
│ • Planner   │  │ • Épisodique   │  │ • ModelRouter       │
│ • Creator   │  │   ChromaDB     │  │   (18 profils)      │
│ • FileAgent │  │   + SQLite     │  │ • OllamaEmbedder    │
│ • Computer  │  │ • Vectorielle  │  │   mxbai-embed-large │
│   Control   │  │   FAISS        │  │ • Retry + Backoff   │
│ • Reminder  │  │ • Working      │  │   exponentiel       │
│ • Document  │  │   Memory       │  └─────────────────────┘
│ • Knowledge │  └────────────────┘
│ • Deception │  ┌────────────────┐
│ • Cyber ◀───┼──► Sécurité      │
│ • Healer    │  │ • YARA rules   │
│ • Profile   │  │ • Quarantaine  │
│ • RAG       │  │ • Leurres      │
│ • P2P (WIP) │  └────────────────┘
└─────────────┘
```

---

## Fonctionnalités

### Cortex adaptatif

Le `FrontalCortex` sélectionne dynamiquement parmi 9 chemins d'exécution selon la nature et la complexité de chaque requête. Un learning router enregistre les latences et ajuste les priorités en temps réel.

```
Chemin           Déclencheur                       Modèle cible
─────────────────────────────────────────────────────────────────
cache_response   Hit sémantique > seuil            —
llm_nano         Confiance élevée, tâche simple    qwen2.5:0.5b
llm_speed        Requête courte standard           qwen2.5:3b
llm_balanced     Tâche intermédiaire               qwen2.5:7b
llm_quality      Raisonnement complexe             deepseek-r1:7b
semantic_parse   Intention structurée détectée     mistral
direct_action    Action système identifiée         —
multi_action     Pipeline multi-étapes             planner → agents
plan_generation  Tâche ouverte et ambiguë          qwen2.5:14b
```

### Router de modèles

Le `ModelRouter` mappe automatiquement chaque requête au modèle Ollama le plus adapté parmi 18 profils configurés. Le routage prend < 1 ms. Le fallback est garanti.

| Catégorie | Modèle principal | Fallback |
|-----------|-----------------|---------|
| Code | codestral | deepseek-coder:6.7b |
| Raisonnement | deepseek-r1:7b | qwen2.5:14b |
| Rédaction FR | gemma2:9b | mistral |
| Vision | llava:13b | moondream |
| Nano (< 2s) | qwen2.5:0.5b | qwen2.5:3b |
| Embeddings | mxbai-embed-large | nomic-embed-text |

### Mémoire vectorielle

Chaque échange est encodé via `mxbai-embed-large` et indexé dans FAISS. Lors des requêtes suivantes, les 3 souvenirs les plus proches par similarité cosinus sont injectés dans le contexte système.

```
Échange t₀ : "Mon framework préféré est FastAPI"
             → embedding 1024d → FAISS index

Échange t₁ : "Conseille-moi un outil pour mon API"
             → similarité 0.71 avec t₀
             → contexte enrichi automatiquement
             → réponse contextualisée sans répétition
```

Persistance cross-sessions via SQLite. Reconstruction d'index automatique au démarrage.

### Système immunitaire numérique

Deux agents dédiés à la sécurité fonctionnent en arrière-plan :

**CyberAgent** — détection d'anomalies comportementales sur le système de fichiers. Surveille les patterns suspects, émet des événements sur l'EventBus.

**HealerAgent** — réponse aux menaces détectées :
- Scan YARA sur les fichiers suspects
- Mise en quarantaine automatique
- Déploiement de leurres actifs (honeypot files)
- Restauration des fichiers sains

### Pipeline multi-agents

Le `PlannerAgent` décompose les tâches complexes en étapes séquentielles. Chaque résultat devient le contexte de l'étape suivante.

```python
"Analyse mes logs et génère un rapport sur le bureau"

→ PlannerAgent    décompose en 3 étapes
→ KnowledgeAgent  lit et analyse les logs
→ CreatorAgent    génère le contenu du rapport
→ FileAgent       crée le fichier sur ~/Desktop/
→ HUD             confirme avec le chemin du fichier
```

### Circuit Breaker LLM

Protection contre les timeouts et les surcharges Ollama. États : `CLOSED → OPEN → HALF_OPEN`. Récupération automatique avec backoff exponentiel. Timeout adaptatif par profil de modèle.

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Runtime | Python 3.11+, asyncio |
| LLM local | Ollama |
| Embeddings | mxbai-embed-large, nomic-embed-text |
| Index vectoriel | FAISS |
| Mémoire épisodique | ChromaDB + SQLite |
| Sécurité | YARA-python |
| Automatisation | PyAutoGUI, AppleScript |
| Interface | PyObjC (Cocoa natif macOS) |
| Métriques | Prometheus + aiohttp |
| Typage | Pyright strict (0 erreur) |
| Logging | Loguru |

---

## État des composants

| Composant | État | Notes |
|-----------|------|-------|
| HUD natif macOS | ✅ Stable | PyObjC, verre translucide |
| FrontalCortex | ✅ Stable | 9 chemins, learning router |
| ModelRouter | ✅ Stable | 18 profils, fallback garanti |
| RAG vectoriel | ✅ Stable | FAISS + mxbai-embed-large |
| Mémoire épisodique | ✅ Stable | SQLite + ChromaDB |
| Pipeline multi-agents | ✅ Stable | asyncio, EventBus |
| Onboarding personnalisé | ✅ Stable | Modèle `prenom-ia` auto-créé |
| CyberAgent | ✅ Stable | Détection anomalies |
| HealerAgent | ✅ Stable | YARA, quarantaine, leurres |
| Circuit Breaker | ✅ Stable | Retry + backoff exponentiel |
| Métriques Prometheus | ✅ Stable | Port 8000 |
| Réseau P2P | 🔄 En développement | Nœuds, TLS à implémenter |
| Tests automatisés | ⏳ Planifié | pytest, cible 80% couverture |

---

## Installation

### Prérequis

```bash
# macOS 12 Monterey minimum
# Python 3.11+
# Ollama — https://ollama.ai
```

### 1. Cloner le projet

```bash
git clone https://github.com/TON_USERNAME/agent-lucie
cd agent-lucie
```

### 2. Environnement virtuel

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Modèles Ollama recommandés

```bash
ollama pull qwen2.5:7b          # modèle par défaut
ollama pull mxbai-embed-large   # embeddings RAG
ollama pull mistral             # fallback général
ollama pull codestral           # tâches code
ollama pull deepseek-r1:7b      # raisonnement
```

### 4. Lancer Lucie

```bash
PYTHONPATH=. python3 main_hud.py
```

Premier lancement : Lucie crée automatiquement votre profil et votre modèle personnel.

### Vérification

```bash
PYTHONPATH=. python3 -c "
import asyncio
from app.core.config import Config
from app.core.engine import LucidEngine

async def test():
    config = Config.load()
    engine = LucidEngine(config)
    response, latency = await engine.process_async('Test de connexion')
    print(f'OK — {latency:.2f}s')

asyncio.run(test())
"
```

---

## Roadmap

### Court terme
- [ ] Suite de tests pytest (cible : 80% de couverture)
- [ ] Chiffrement AES-256 de la mémoire épisodique
- [ ] Benchmark automatisé des modèles au démarrage

### Moyen terme
- [ ] Réseau P2P chiffré (TLS, authentification mutuelle)
- [ ] Fine-tuning local automatique via Modelfile adaptatif
- [ ] Plugin système macOS (Spotlight, raccourcis globaux)
- [ ] Interface de configuration graphique

### Long terme
- [ ] Support Linux et Windows
- [ ] Fédération de nœuds Lucie (P2P distribué)
- [ ] Marketplace de plugins agents

---

## Structure du projet

```
agent-lucie/
├── app/
│   ├── agents/          # 13 agents spécialisés
│   ├── brain/
│   │   ├── cortex.py    # FrontalCortex, 9 chemins
│   │   └── synapses/    # EventBus, SynapseBus
│   ├── core/            # LucidEngine, Config, Executor
│   ├── memory/          # EpisodicMemory, WorkingMemory
│   ├── providers/       # ProviderManager, ModelRouter
│   ├── services/        # RAG, PromptCache, Onboarding
│   ├── ui/              # HUD PyObjC natif macOS
│   └── utils/           # CircuitBreaker, Logger, Metrics
├── main_hud.py
├── CLAUDE.md            # Contexte technique du projet
└── requirements.txt
```

---

## Auteur

**Mathieu Bellot** — 18 ans

Projet personnel open-source, développé en solo depuis zéro.  
Architecture multi-agents, intégration LLM local, interface native macOS.

> Ce projet est né d'une conviction : l'accès à une IA privée, performante et personnalisable ne devrait pas dépendre d'un abonnement mensuel.

---

## Contribuer

Les contributions sont bienvenues — code, documentation, nouveaux agents, règles YARA, modèles Ollama optimisés.

```bash
git checkout -b feature/nom-de-la-feature
# développement
git commit -m "feat: description claire"
git push origin feature/nom-de-la-feature
# ouvrir une Pull Request
```

Merci de respecter le style de code existant : type hints complets, docstrings, 0 erreur pyright.

---

## Licence

MIT — voir [LICENSE](LICENSE).

---

<div align="center">
<sub>Agent Lucie · Python 3.11 · macOS · Ollama · Open Source · Mathieu Bellot</sub>
</div>