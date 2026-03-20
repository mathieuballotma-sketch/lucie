<div align="center">

```
██╗     ██╗   ██╗ ██████╗██╗███████╗
██║     ██║   ██║██╔════╝██║██╔════╝
██║     ██║   ██║██║     ██║█████╗  
██║     ██║   ██║██║     ██║██╔══╝  
███████╗╚██████╔╝╚██████╗██║███████╗
╚══════╝ ╚═════╝  ╚═════╝╚═╝╚══════╝
```

**Assistant IA 100% local pour macOS — zéro cloud, zéro compromis.**

[![License](https://img.shields.io/badge/license-BSL_1.1-amber?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11_|_3.13-blue?style=flat-square&logo=python)](https://python.org)
[![macOS](https://img.shields.io/badge/macOS-Apple_Silicon-black?style=flat-square&logo=apple)](https://apple.com)
[![Ollama](https://img.shields.io/badge/ollama-local_LLM-white?style=flat-square)](https://ollama.ai)
[![Tests](https://img.shields.io/badge/tests-57%2F57_passing-brightgreen?style=flat-square)]()
[![Made in France](https://img.shields.io/badge/made_in-France_🇫🇷-blue?style=flat-square)]()

<br/>

> *Coupe le WiFi. Lucie tourne toujours.*

<br/>

[**Démo**](#-démo) · [**Installation**](#-installation) · [**Architecture**](#-architecture) · [**Roadmap**](#-roadmap) · [**Contribuer**](#-contribuer)

</div>

---

## ⚡ Ce que Lucie fait

<table>
<tr>
<td width="50%">

**🧠 25 agents spécialisés**  
Chaque agent gère un domaine précis — email, calendrier, fichiers, code, web, vision — et collaborent via un bus d'événements bio-inspiré.

**🔒 100% local, 0% cloud**  
Aucune donnée ne quitte ton Mac. Jamais. Ollama tourne en local, la mémoire reste sur ton disque.

**⚡ Wake word en 0.57s**  
"Hey Jarvis" → réponse en moins d'une seconde, détection locale sans API externe.

</td>
<td width="50%">

**📧 SmartMailAgent**  
Rédige, trie et envoie des emails avec workflow de confirmation avant toute action.

**🗂️ Mémoire vectorielle FAISS**  
606 vecteurs persistants. Lucie se souvient de tes préférences, habitudes et contexte entre les sessions.

**🎙️ Voix premium Aurélie**  
Synthèse vocale française naturelle, entièrement locale via le moteur macOS.

</td>
</tr>
</table>

---

## 🎬 Démo

<div align="center">

```
[ GIF de démo à venir — enregistrement en cours ]
```

*Wake word → "Hey Jarvis, envoie un email à Marc pour reporter la réunion"*  
*→ Lucie analyse, rédige, demande confirmation, envoie. 0 cloud. 0 fuite.*

</div>

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        LUCIE CORE                           │
│                                                             │
│   ┌──────────┐    ┌──────────┐    ┌──────────────────┐    │
│   │  Cortex  │───▶│EventBus  │───▶│  25 Agents       │    │
│   │ 6 layers │    │SynapseBus│    │  spécialisés     │    │
│   └──────────┘    └──────────┘    └──────────────────┘    │
│         │                                  │               │
│   ┌─────▼──────┐              ┌────────────▼─────────┐    │
│   │   Ollama   │              │  FAISS Memory        │    │
│   │  19 models │              │  606 vectors         │    │
│   │  local LLM │              │  SQLite ActionTrace  │    │
│   └────────────┘              └──────────────────────┘    │
│                                                             │
│   MacBook M4 · 24GB RAM · 0 internet required              │
└─────────────────────────────────────────────────────────────┘
```

### Agents actifs

| Domaine | Agents |
|---|---|
| 🧠 Cerveau | Cortex, Thalamus, WaterFlow |
| 📬 Communication | SmartMailAgent, CalendarAgent |
| 💻 Système | ComputerControlAgent, FileAgent, WorkspaceAgent |
| 🔍 Recherche | SafariResearchWorkflow, RAGAgent |
| 🛡️ Sécurité | CyberAgent, PrivacyGateway |
| 🔧 Maintenance | HealerAgent, Fixer, Analyzer |
| + 12 autres | ... |

---

## 🚀 Installation

### Prérequis

- macOS 13+ (Apple Silicon recommandé)
- Python 3.11 ou 3.13
- [Ollama](https://ollama.ai) installé et lancé

### Démarrage rapide

```bash
# 1. Cloner le repo
git clone https://github.com/mathieuballotma-sketch/Agent-Lucie.git
cd Agent-Lucie

# 2. Créer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer
cp config.example.yaml config.yaml

# 5. Lancer Lucie
python main.py
```

> 💡 **Premier lancement ?** Lucie crée automatiquement sa mémoire locale dans `~/.lucie/`

---

## 🧪 Tests

```bash
python -m pytest tests/ -v
# Résultat attendu : 57/57 ✅
```

---

## 📍 Roadmap

- [x] Architecture multi-agents (25 agents)
- [x] Mémoire vectorielle FAISS
- [x] Wake word détection locale (0.57s)
- [x] SmartMailAgent + workflow confirmation
- [x] Brief du matin automatisé
- [ ] Interface visuelle type n8n (éditeur de flux)
- [ ] PrivacyGatewayAgent (audit données)
- [ ] Marketplace d'agents communautaires
- [ ] Distribution P2P (compute partagé)
- [ ] Build `.dmg` public

---

## 🤝 Contribuer

Les contributions sont les bienvenues ! Consulte [CONTRIBUTING.md](CONTRIBUTING.md) pour commencer.

---

## 📄 Licence

[Business Source License 1.1](LICENSE) — usage personnel et recherche libre, usage commercial sur accord.

---

<div align="center">

**Fait par [Mathieu Ballot](https://github.com/mathieuballotma-sketch) · 18 ans · France 🇫🇷**

*Commencé de zéro, sans formation, en février 2025.*

<br/>

⭐ **Une étoile aide Lucie à grandir** ⭐

</div>