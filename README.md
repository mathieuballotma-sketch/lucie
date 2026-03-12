# 🧠 Agent Lucie

> **Assistant IA local, souverain et multi-agents — 100% hors-ligne sur macOS.**
> Doté d'un système immunitaire numérique intégré qui détecte, neutralise et apprend des menaces.

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/macOS-13+-000000?style=for-the-badge&logo=apple&logoColor=white"/>
  <img src="https://img.shields.io/badge/Ollama-local-74aa9c?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Status-En%20développement-orange?style=for-the-badge"/>
</p>

<p align="center">
  <a href="README.md">🇫🇷 Français</a> •
  <a href="README.en.md">🇬🇧 English</a> •
  <a href="README.zh.md">🇨🇳 中文</a> •
  <a href="README.es.md">🇪🇸 Español</a>
</p>

---

## 🚧 Avertissement important — projet en développement actif

> Agent Lucie est un projet **personnel**, développé et maintenu par **une seule personne**.
> Je travaille dessus seul, en gérant à la fois le développement, les tests, les corrections de bugs et l'architecture — tout en même temps.

Ce que ça signifie concrètement :

- ✅ Le **cerveau décisionnel** (Cortex, routing, fallback) fonctionne bien
- ✅ Le **système immunitaire** (CyberAgent, HealerAgent) est opérationnel
- ⚠️ Le **contrôle de l'ordinateur** est en cours de développement — certaines actions peuvent ne pas fonctionner ou se comporter de manière inattendue
- ⚠️ La **génération de documents** fonctionne mais peut produire des résultats imparfaits
- 🔄 Des corrections et améliorations sont apportées **chaque jour**

Je préfère être **totalement honnête** plutôt que de survendre quelque chose d'inachevé.
Merci pour votre compréhension — n'hésitez pas à ouvrir une issue si vous rencontrez un problème ! 🙏

---

## 🎯 C'est quoi Agent Lucie ?

Agent Lucie est un assistant IA qui tourne **entièrement sur votre Mac**, sans envoyer la moindre donnée sur internet. Pas d'abonnement, pas de cloud, pas de dépendance à OpenAI ou Google.

Il est capable de :
- Contrôler votre ordinateur par la voix ou le texte
- Générer des documents Word automatiquement
- Se souvenir de vos conversations
- **Protéger activement votre système** contre les fichiers malveillants

---

## ✨ Fonctionnalités

### 🤖 Cerveau décisionnel
| Fonctionnalité | État |
|---|---|
| Cortex adaptatif — 9 chemins d'exécution | ✅ Stable |
| Apprentissage automatique du routage | ✅ Stable |
| Fallback intelligent entre chemins | ✅ Stable |
| Circuit breaker LLM | ✅ Stable |

### 🏗️ Structure des agents — la première brique *(en développement)*

> **Ce que vous voyez ici n'est que le début.**

L'accès à Notes, Mail, Safari, Word et aux autres applications n'est pas une fin en soi — c'est la **fondation**. Chaque application intégrée devient un point d'ancrage pour un agent spécialisé capable, à terme, d'agir **de façon totalement autonome**, sans intervention humaine.

L'objectif final : vous dites ce que vous voulez, et Agent Lucie s'en occupe entièrement — rédiger et envoyer un email, créer un rapport complet, organiser votre journée, surveiller vos fichiers — **pendant que vous faites autre chose**.

| Fonctionnalité | État | Vision |
|---|---|---|
| Ouvrir des applications (Notes, Mail, Safari...) | ⚠️ En cours | 1ère brique — accès établi |
| Taper du texte | ⚠️ En cours | Base pour automatiser la saisie |
| Clic, déplacement souris, capture d'écran | ⚠️ En cours | Base pour naviguer sans intervention |
| Organiser les fenêtres | ⚠️ En cours | Base pour gérer l'espace de travail |
| Créer des rappels | ⚠️ En cours | Base pour la gestion autonome du temps |
| **Automatisation complète sans intervention** | 🔮 À venir | L'objectif final |

### 🛡️ Système immunitaire numérique
| Fonctionnalité | État |
|---|---|
| CyberAgent — détection d'anomalies | ✅ Stable |
| HealerAgent — scan YARA + quarantaine | ✅ Stable |
| Leurres actifs | ✅ Stable |
| Mémoire immunitaire | ✅ Stable |

### 🧠 Mémoire & contexte
| Fonctionnalité | État |
|---|---|
| Mémoire épisodique (ChromaDB) | ✅ Stable |
| Profil utilisateur | ✅ Stable |
| Memory Manager | ✅ Stable |

---

## 🛡️ Système immunitaire numérique

C'est la fonctionnalité la plus originale d'Agent Lucie — un **vrai système immunitaire** intégré nativement dans l'assistant.

### 🔍 CyberAgent
Surveille en permanence les événements internes du système. Lorsqu'un outil échoue de façon répétée, il calcule une sévérité, déclenche une alerte et peut mettre l'outil défaillant en **quarantaine temporaire** — évitant ainsi les cascades d'erreurs.

### 🩺 HealerAgent
Scrute les nouveaux fichiers créés ou modifiés. Utilise une base de **hash malveillants** et des **règles YARA** pour détecter les menaces. En cas de détection :
- Le fichier est déplacé vers `~/AgentLucide/quarantine/`
- Un **leurre inoffensif** est créé à sa place
- Toute tentative d'accès au leurre est tracée et signalée

Ces deux agents communiquent via l'**Event Bus** pour une orchestration complète de la défense.

---

## 🏗️ Architecture

```
Agent Lucie
├── 🧠 Cortex              — orchestrateur principal (9 chemins, learning router)
├── 🤖 Agents              — Computer, Document, Knowledge, Cyber, Healer, Reminder, Planner...
├── 💾 Mémoire             — working memory + épisodique (ChromaDB) + Memory Manager
├── ⚡ Event Bus           — communication inter-agents (synchrone, thread-safe)
├── 🛡️ Système immunitaire — CyberAgent (détection) + HealerAgent (guérison)
└── 🔌 Providers           — Ollama (100% local)
```

---

## 🚀 Installation

### Prérequis
- macOS 13+
- Python 3.11+
- [Ollama](https://ollama.com) installé

### Étapes

```bash
# 1. Cloner le projet
git clone https://github.com/mathieuballotma-sketch/Agent-Lucie.git
cd Agent-Lucie

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Télécharger les modèles LLM
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b  # optionnel — nécessite 24 GB de RAM

# 4. Lancer l'agent
python main.py
```

### ⚙️ Autorisations macOS requises

Dans **Réglages Système > Confidentialité** :
- ✅ Accessibilité → autoriser Terminal
- ✅ Automatisation → autoriser Terminal
- ✅ Enregistrement d'écran → pour les captures d'écran

---

## 🎥 Démonstration

> 🎬 Une vidéo de démonstration est en préparation.

Le dossier `demos/` contient des **documents Word générés automatiquement** par Agent Lucie — preuve concrète que le système fonctionne.

---

## 🛠️ Stack technique

| Composant | Technologie |
|---|---|
| LLM local | Ollama — qwen2.5 (0.5B → 14B) |
| Mémoire vectorielle | ChromaDB |
| Embeddings | sentence-transformers |
| Contrôle macOS | PyAutoGUI + AppleScript + NSWorkspace |
| Détection malwares | YARA + hash signatures |
| Métriques | Prometheus |
| I/O asynchrone | asyncio + aiofiles + aiosqlite |
| Réseau P2P | aiohttp |

---

## 👨‍💻 Auteur

**Mathieu Bellot** — développeur indépendant, projet 100% personnel et open-source.

Je construis Agent Lucie seul, avec la conviction que l'IA doit être **locale, souveraine et accessible à tous** — sans abonnement, sans cloud, sans compromis sur la vie privée.

---

## ⚠️ Disclaimer

Ce projet manipule des applications, fichiers et réglages de votre Mac.
Il est fourni **en l'état**, sans garantie d'aucune sorte.
L'auteur n'est pas responsable des actions effectuées par l'agent (emails envoyés, fichiers modifiés, rappels créés, etc.).
**Utilisez-le à vos propres risques.**