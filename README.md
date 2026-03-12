🧠 Agent Lucie

Assistant IA local, souverain et multi-agents — fonctionne 100% hors-ligne sur macOS.
Système immunitaire intégré : détecte, neutralise et apprend des menaces.
https://img.shields.io/badge/Python-3.11+-blue
https://img.shields.io/badge/macOS-13+-black
https://img.shields.io/badge/Ollama-local-green
https://img.shields.io/badge/License-MIT-yellow

✨ Fonctionnalités actuelles

🤖 Cœur intelligent

🧠 Cortex décisionnel – 9 chemins d’exécution adaptatifs (direct, LLM, cache, planification…)
📈 Apprentissage automatique – le routeur choisit le chemin le plus rapide et fiable en fonction de l’expérience
🔁 Fallback intelligent – si un chemin échoue, le suivant est automatiquement tenté
🖥️ Contrôle de l’ordinateur

🚀 Ouvre des applications – Notes, Word, Mail, Safari, etc. (vérification instantanée, plus de timeout)
📝 Tape du texte – avec support spécial pour Notes (nouvelle note automatique)
🖱️ Clique, déplace la souris, prend des captures d’écran
📐 Organise les fenêtres – côte à côte, grille 2×2
🛡️ Système immunitaire numérique

🔍 CyberAgent – surveille les erreurs, détecte les anomalies, met en quarantaine les outils défaillants
🩺 HealerAgent – scanne les fichiers suspects (hash, règles YARA), les isole et crée des leurres inoffensifs
🧬 Mémoire immunitaire – conserve les signatures des menaces pour une détection plus rapide
🎭 Leurres – les fichiers malveillants sont remplacés par des leurres qui tracent toute tentative d’accès
🧹 Nettoyage automatique – les leurres trop vieux sont supprimés
🧠 Mémoire et contexte

💾 Mémoire épisodique – se souvient des conversations passées
🔗 Memory Manager – combine mémoire courte et longue pour enrichir les requêtes
👤 Profil utilisateur – apprend vos préférences
⚡ Performance & robustesse

🚦 Timeouts réduits – une application inexistante est détectée en < 0,5 s (plus d’attente de 10 s)
🔁 Circuit breaker – protège contre les appels LLM défaillants
📊 Métriques Prometheus – pour superviser le système
🔌 Technologies utilisées

Ollama – modèles LLM locaux (0.5B à 14B)
ChromaDB – mémoire vectorielle
sentence-transformers – embeddings sémantiques
PyAutoGUI + AppleScript – contrôle macOS
YARA – détection de malwares par règles
aiosqlite / aiofiles – tout est asynchrone
🏗️ Architecture

text
Agent Lucie
├── 🧠 Cortex              – orchestrateur principal (9 chemins, learning router)
├── 🤖 Agents              – Computer, Document, Knowledge, Cyber, Healer, Reminder, Planner...
├── 💾 Mémoire             – working memory + épisodique (ChromaDB) + Memory Manager
├── ⚡ Event Bus           – communication inter-agents (synchrone, thread‑safe)
├── 🛡️ Système immunitaire – CyberAgent (détection) + HealerAgent (guérison)
└── 🔌 Providers           – Ollama (local)
🚀 Installation

1. Cloner le projet

bash
git clone https://github.com/mathieuballotma-sketch/Agent-Lucie.git
cd Agent-Lucie
2. Installer les dépendances

bash
pip install -r requirements.txt
Si vous utilisez pip, le fichier requirements.txt contient notamment :

text
aiofiles
aiosqlite
yara-python
aiohttp
joblib
numpy
torch
scikit-learn
sentence-transformers
chromadb
pyautogui
pydantic
pyobjc
psutil
prometheus_client
pyyaml
croniter
3. Installer Ollama

Téléchargez et installez Ollama, puis récupérez les modèles :

bash
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b   # optionnel
4. Préparer l’environnement de quarantaine (optionnel)

bash
mkdir -p ~/AgentLucide/{quarantine,lures}
echo "4e759e4a97b455eefc133845fd61610539e448a2a3e809b03808a641f71e917e" >> ~/.agent_lucide/malicious_hashes.txt
5. Lancer l’agent

bash
python main.py
⚙️ Prérequis macOS

Important – Autoriser l’accès dans Réglages Système :

Confidentialité > Accessibilité → autoriser Terminal (ou votre émulateur)
Confidentialité > Automatisation → autoriser Terminal
(optionnel) Pour le contrôle de l’écran, autoriser l’enregistrement d’écran si nécessaire
🎥 Démonstration

🎬 Une vidéo de démonstration est en préparation. Elle montrera :

L’ouverture instantanée d’applications
La détection d’un fichier malveillant
La mise en quarantaine et la création d’un leurre
Le système immunitaire en action
📁 Dossiers importants

~/AgentLucide/quarantine/ – fichiers malveillants isolés
~/AgentLucide/lures/ – leurres créés (traçables)
./data/ – mémoire épisodique, cache, index RAG
./Lucid_Docs/ – documents générés
🛠️ Stack technique détaillée

Python 3.11+ – asyncio, threading
Ollama – modèles LLM locaux
ChromaDB – mémoire vectorielle
sentence-transformers – embeddings sémantiques
PyAutoGUI + AppleScript – contrôle macOS
YARA – détection de malwares
Prometheus – métriques
aiohttp – serveur P2P intégré
aiosqlite / aiofiles – I/O non bloquante
🤝 Contribution

Les contributions sont les bienvenues !
Consultez le fichier CONTRIBUTING.md pour plus de détails.

👨‍💻 Auteur

Mathieu Bellot – projet personnel open-source
GitHub

⚠️ Disclaimer

Ce projet manipule des applications, fichiers et réglages de votre Mac.
Il est fourni en l’état, sans garantie. L’auteur n’est pas responsable des actions effectuées par l’agent (emails envoyés, fichiers modifiés, rappels créés, etc.). Utilisez-le à vos propres risques.

