cat > README.md << 'READMEEOF'
# 🧠 Agent Lucie

> Assistant IA local, souverain et multi-agents — 100% hors-ligne sur macOS.
> Doté d'un système immunitaire numérique intégré.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-13+-000000?style=flat-square&logo=apple&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-local-74aa9c?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)
![Status](https://img.shields.io/badge/Status-En%20développement%20actif-brightgreen?style=flat-square)

---

## 🎯 En bref

Agent Lucie est un assistant IA personnel qui tourne **entièrement sur votre Mac**, sans envoyer la moindre donnée sur internet. Il contrôle votre ordinateur, génère des documents, se souvient de vos conversations — et protège activement votre système contre les menaces.

---

## ✨ Fonctionnalités

### 🤖 Cerveau décisionnel
- **Cortex adaptatif** — 9 chemins d'exécution, choisit automatiquement le plus rapide
- **Apprentissage continu** — s'améliore à chaque requête
- **Fallback intelligent** — si un chemin échoue, le suivant est tenté automatiquement

### 🖥️ Contrôle de l'ordinateur
- Ouvre des applications — Notes, Word, Mail, Safari... en moins de 0.5s
- Tape du texte, clique, déplace la souris, capture l'écran
- Organise les fenêtres (côte à côte, grille 2×2)
- Crée des rappels et gère le calendrier

### 📝 Génération de documents
- Crée des fichiers Word automatiquement avec résumés
- Génère des synthèses à partir de contenus existants

### 🛡️ Système immunitaire numérique
- **CyberAgent** — surveille les erreurs, détecte les anomalies, met en quarantaine les outils défaillants
- **HealerAgent** — scanne les fichiers suspects (hash + règles YARA), les isole et crée des leurres
- **Mémoire immunitaire** — apprend de chaque menace pour détecter plus vite la prochaine
- **Leurres actifs** — les fichiers malveillants sont remplacés par des pièges traçables

### 🧠 Mémoire & contexte
- Mémoire épisodique (ChromaDB) — se souvient des conversations passées
- Profil utilisateur — apprend vos préférences au fil du temps

---

## 🏗️ Architecture
```
Agent Lucie
├── 🧠 Cortex              — orchestrateur (9 chemins, learning router)
├── 🤖 Agents              — Computer, Document, Cyber, Healer, Reminder, Planner...
├── 💾 Mémoire             — working memory + épisodique (ChromaDB)
├── ⚡ Event Bus           — communication inter-agents (thread-safe)
├── 🛡️ Système immunitaire — CyberAgent + HealerAgent
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
ollama pull qwen2.5:14b  # optionnel — nécessite 24GB RAM

# 4. Lancer l'agent
python main.py
```

### ⚙️ Autorisation macOS requise

Dans **Réglages Système > Confidentialité** :
- ✅ Accessibilité → autoriser Terminal
- ✅ Automatisation → autoriser Terminal
- ✅ Enregistrement d'écran → si vous utilisez les captures

---

## 🎥 Démonstration

> 🎬 Vidéo de démonstration en préparation.

Le dossier `demos/` contient des documents Word générés automatiquement par Agent Lucie.

---

## 🛠️ Stack technique

| Composant | Technologie |
|---|---|
| LLM local | Ollama (qwen2.5 0.5B → 14B) |
| Mémoire vectorielle | ChromaDB |
| Embeddings | sentence-transformers |
| Contrôle macOS | PyAutoGUI + AppleScript |
| Détection malwares | YARA |
| Métriques | Prometheus |
| I/O asynchrone | asyncio + aiofiles + aiosqlite |

---

## 👨‍💻 Auteur

**Mathieu Bellot** — projet personnel open-source
Construit avec passion pour démocratiser l'IA locale et souveraine.

---

## ⚠️ Disclaimer

Ce projet manipule des applications et fichiers de votre Mac.
Utilisez-le à vos propres risques — l'auteur n'est pas responsable des actions effectuées par l'agent.
READMEEOF