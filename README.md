<div align="center">

# 🧠 Lucie

**L'IA locale qui respecte vos données.**

Assistant multi-agents pour macOS — conçu pour les experts-comptables et professions réglementées.

[![Version](https://img.shields.io/badge/version-0.2.0--beta-blue?style=flat-square)](https://github.com/mathieuballotma-sketch/Agent-Lucie/releases)
[![Tests](https://img.shields.io/badge/tests-642_passed-brightgreen?style=flat-square)]()
[![Python](https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![macOS](https://img.shields.io/badge/macOS-Apple_Silicon-black?style=flat-square&logo=apple)](https://apple.com)
[![License](https://img.shields.io/badge/license-BSL_1.1-orange?style=flat-square)](LICENSE)

<br/>

[Pourquoi Lucie ?](#-pourquoi-lucie) · [Architecture](#-architecture) · [Installation](#-installation) · [Fonctionnalités](#-fonctionnalités) · [Sécurité](#-sécurité) · [Roadmap](#-roadmap)

</div>

---

## 🔥 Pourquoi Lucie ?

Chaque assistant IA envoie vos données sur un serveur que vous ne contrôlez pas.
Pour un expert-comptable, un avocat ou un médecin, c'est un problème réglementaire. Pour tout le monde, c'est un problème de confiance.

Lucie est différente :

🔒 **100% local** — vos données ne quittent jamais votre Mac. Zéro cloud, zéro API externe.

🧠 **30 agents spécialisés** — comptabilité, sécurité, planning, mail, code, crypto, recherche web, et plus.

📊 **Export FEC conforme DGFiP** — traitement de factures, catégorisation, rapprochement bancaire automatisé.

⚡ **Fonctionne avec Ollama** — 7 modèles locaux, chacun optimisé pour sa tâche. Aucun abonnement requis.

🛡️ **Sécurité en profondeur** — sandboxing des agents, chiffrement au repos, détection d'exfiltration, protection mémoire.

---

## 📸 Démo

> *Capture d'écran / GIF à venir — le HUD natif macOS est en cours de polish.*

---

## 🏗 Architecture

```
                        ┌─────────────────────┐
                        │     Utilisateur      │
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
                        │    HUD (AppKit)      │
                        │  Interface native    │
                        └──────────┬──────────┘
                                   │
              ┌────────────────────▼────────────────────┐
              │            FrontalCortex                 │
              │                                          │
              │  QuantumRouter ─── Classifier             │
              │  Thalamus ─────── EventBus               │
              │  ContextWave ──── MemoryGraph             │
              └──────────┬───────────────────┬───────────┘
                         │                   │
            ┌────────────▼──┐          ┌─────▼────────────┐
            │  30 Agents    │          │  Security Layer   │
            │               │          │                   │
            │ Accounting    │          │ Sandbox Manager   │
            │ SmartMail     │          │ Encryption (AES)  │
            │ Calendar      │          │ Memory Protection │
            │ CryptoInvest  │          │ Exfiltration Det. │
            │ CodeDebug     │          │ Integrity Monitor │
            │ ...           │          │ Threat Intel      │
            └───────┬───────┘          └──────────────────┘
                    │
         ┌──────────▼──────────┐
         │  Ollama · FAISS ·   │
         │  SQLite · Whisper   │
         │  (tout local)       │
         └─────────────────────┘
```

### Les 30 agents

| Catégorie | Agents | Description |
|-----------|--------|-------------|
| **Productivité** | SmartMail, Calendar, Reminder, File, Document, Workspace | Intégration native macOS — Mail, Calendrier, Rappels, Finder |
| **Comptabilité** | Accounting, FEC Export | Extraction factures, catégorisation, export FEC conforme DGFiP |
| **Intelligence** | Knowledge, Safari Research, Creator, Planner, Strategist | Recherche sémantique FAISS, recherche web, création de contenu |
| **Développement** | CodeDebug, Fixer, Analyzer | Diagnostic d'erreurs, correction automatique, analyse de logs |
| **Finance** | CryptoInvestor, MiningMonitor, RiskGuard, TaxReporter | Suivi crypto, analyse de risque, reporting fiscal |
| **Sécurité** | Cyber, Deception, Watch | Monitoring temps réel, honeypots, surveillance |
| **Système** | ComputerControl, Wake, Apple Ecosystem, Clipboard, Notification | Contrôle macOS via Accessibility, commande vocale, notifications |
| **Meta** | Healer, Profile, Feedback, Soul, TeamLeader, Consolidator | Auto-réparation, profil utilisateur, coordination inter-agents |

---

## 🚀 Installation

### Prérequis

- macOS avec Apple Silicon (M1/M2/M3/M4)
- Python 3.11+
- [Ollama](https://ollama.com) installé

### Démarrage rapide

```bash
# 1. Installer Ollama et tirer un modèle
brew install ollama
ollama pull qwen2.5:3b

# 2. Cloner et installer
git clone https://github.com/mathieuballotma-sketch/Agent-Lucie.git
cd Agent-Lucie
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Lancer Lucie
PYTHONPATH=. python3 main_hud.py
```

> Lucie crée son stockage local dans `~/.lucie/` au premier lancement. Aucune configuration requise.

### Configuration matérielle

| Config | RAM | Expérience |
|--------|-----|------------|
| Minimum | 8 Go | Agents de base, 2-3 modèles actifs |
| Recommandé | 16 Go | Multi-agents complet |
| Optimal | 24 Go+ | 7 modèles simultanés, tous les agents |

---

## ✨ Fonctionnalités

| Fonctionnalité | Statut | Description |
|----------------|--------|-------------|
| **AccountingAgent + FEC** | ✅ | Traitement de factures en lot, export FEC conforme DGFiP |
| **SmartMailAgent** | ✅ | Classification intelligente des mails (4 niveaux d'urgence) via LLM |
| **QuantumRouter** | ✅ | Routage adaptatif avec fusion et superposition quantique |
| **CryptoInvestorAgent** | ✅ | Suivi de portefeuille crypto, analyse de risque, reporting fiscal |
| **Sandboxing agents** | ✅ | Isolation des agents avec IPC chiffré |
| **Chiffrement au repos** | ✅ | AES-256 pour toutes les données persistées |
| **Commande vocale** | ✅ | Wake word local ("Hey Jarvis") + Whisper |
| **RAG local** | ✅ | FAISS + embeddings Ollama, 100% offline |
| **EventBus authentifié** | ✅ | Communication inter-agents sécurisée |
| **CircuitBreaker** | ✅ | Résilience automatique avec fallback gracieux |
| **Contrôle macOS natif** | ✅ | Clic, frappe, lecture d'UI via Accessibility APIs |
| **Export FacturX** | 🚧 | Factures électroniques au format FacturX |
| **LegalResearchAgent** | 🚧 | Recherche Légifrance |
| **Installeur .dmg** | 🚧 | Distribution native macOS |

---

## 🛡 Sécurité

Lucie intègre 6 couches de sécurité, toutes exécutées localement :

| Module | Code | Description |
|--------|------|-------------|
| **Agent Sandboxing** | SEC-01 | Chaque agent tourne dans un sandbox isolé avec IPC chiffré |
| **Chiffrement au repos** | SEC-02 | AES-256 via `cryptography` — données, mémoire, logs |
| **Protection mémoire** | SEC-03 | Isolation de la mémoire inter-agents, nettoyage automatique |
| **Integrity Monitor** | SEC-04 | Détection de modification non autorisée des fichiers agents |
| **Security Response** | SEC-05 | Réponse automatisée aux incidents détectés |
| **Content Filter** | SEC-06 | Détection d'exfiltration, filtrage de contenu, threat intelligence |

**Pipeline de sanitisation** : chaque entrée (mail, document, prompt) passe par `TextSanitizer` (HTML, base64, unicode) puis `PromptInjectionDetector` (scoring + analyse LLM). Verdicts : `SAFE`, `SUSPICIOUS`, `MALICIOUS`.

**Audit** : toutes les actions suspectes sont logées dans SQLite (`~/.lucie/sandbox_memory.db`), consultable pour audit.

---

## 🔧 Stack technique

| Composant | Technologie |
|-----------|-------------|
| Langage | Python 3.11+ |
| LLM | Ollama (7 modèles locaux) |
| Embeddings | FAISS + Ollama embeddings |
| Interface | PyObjC / AppKit (HUD natif macOS) |
| Validation | Pydantic |
| Async | asyncio |
| Chiffrement | `cryptography` (AES-256, Fernet) |
| Audio | faster-whisper (STT local) |
| Base de données | SQLite |
| Recherche web | DuckDuckGo (via duckduckgo_search) |

**Patterns d'architecture** : EventBus authentifié, CircuitBreaker, AuditTrail, Saga, Resilience Policy, QuantumRouter (routage adaptatif multi-critères).

---

## 🧪 Validation

```bash
# Tests
PYTHONPATH=. python -m pytest tests/ -x -q          # 642 passed

# Analyse statique
ruff check app/ --fix                                # 0 errors
python -m mypy app/ --ignore-missing-imports         # strict mode
```

---

## 🗺 Roadmap

- [x] 30 agents opérationnels (productivité, comptabilité, finance, sécurité, système)
- [x] Architecture multi-modèles (7 modèles spécialisés Ollama)
- [x] AccountingAgent + export FEC conforme DGFiP
- [x] QuantumRouter v2 avec fusion et superposition
- [x] 6 modules de sécurité (SEC-01 à SEC-06)
- [x] 642 tests, ruff clean, mypy strict
- [ ] LegalResearchAgent — intégration Légifrance
- [ ] Installeur .dmg natif macOS
- [ ] Vidéo de démonstration
- [ ] Mode multi-utilisateurs (cabinet comptable)
- [ ] Plugin Notion / Obsidian

---

## 📄 Licence

[Business Source License 1.1](LICENSE) — usage personnel et recherche autorisés. Usage commercial sur accord.

---

## 👤 Contact

**Mathieu Bellot** — développeur, 18 ans, France.

> *« J'ai créé Lucie parce que l'IA devrait tourner là où vivent vos données — sur votre machine. »*

---

<div align="center">

⭐ **Star ce repo si vous croyez en l'IA locale.**

*Lucie v0.2.0-beta — données 100% locales, chiffrées, souveraines.*

</div>
