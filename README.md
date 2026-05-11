<div align="center">

# 🧠 Beaume

**L'IA locale qui respecte vos données.**

Assistant multi-agents pour macOS — conçu pour les experts-comptables et professions réglementées.

[![Version](https://img.shields.io/badge/version-1.0.0-blue?style=flat-square)](https://github.com/mathieuballotma-sketch/Agent-Lucie/releases)
[![Tests](https://img.shields.io/badge/tests-512_passed-brightgreen?style=flat-square)]()
[![Python](https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![macOS](https://img.shields.io/badge/macOS-Apple_Silicon-black?style=flat-square&logo=apple)](https://apple.com)
[![License](https://img.shields.io/badge/license-BSL_1.1-orange?style=flat-square)](LICENSE)

<br/>

[Pourquoi Beaume ?](#-pourquoi-beaume) · [Architecture](#-architecture) · [Installation](#-installation) · [Fonctionnalités](#-fonctionnalités) · [Sécurité](#-sécurité) · [Roadmap](#-roadmap)

</div>

---

## 🔥 Pourquoi Beaume ?

Chaque assistant IA envoie vos données sur un serveur que vous ne contrôlez pas.
Pour un expert-comptable, un avocat ou un médecin, c'est un problème réglementaire. Pour tout le monde, c'est un problème de confiance.

Beaume est différente :

🔒 **100% local** — vos données ne quittent jamais votre Mac. Zéro cloud, zéro API externe.

🧠 **30 agents spécialisés** — comptabilité, sécurité, planning, mail, code, crypto, recherche web, et plus.

📊 **Export FEC conforme DGFiP** — traitement de factures, catégorisation, rapprochement bancaire automatisé.

⚡ **Fonctionne avec Ollama** — 7 modèles locaux, chacun optimisé pour sa tâche. Aucun abonnement requis.

🛡️ **Local-first par design** — vos données ne quittent jamais votre machine. Chiffrement AES-256 au repos, sandbox macOS natif, filtrage de données sensibles.

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

# 3. Lancer Beaume
PYTHONPATH=. python3 main_hud.py
```

> Beaume crée son stockage local dans `~/.lucie/` au premier lancement (chemin runtime préservé pour compat). Aucune configuration requise.

### Configuration matérielle

| Config | RAM | Expérience |
|--------|-----|------------|
| Minimum | 8 Go | Agents de base, 2-3 modèles actifs |
| Recommandé | 16 Go | Multi-agents complet |
| Optimal | 24 Go+ | 7 modèles simultanés, tous les agents |

---

## ⚡ Performance

Beaume v1 optimise la latence des réponses juridiques via plusieurs leviers activables par variables d'environnement.

### Variables d'environnement

> **Sprint 1ter (2026-05-08)** : les variables d'env sont préfixées `BEAUME_*`.
> Les anciennes `LUCIE_*` restent acceptées en alias deprecated (un `DeprecationWarning`
> et un log WARNING sont émis au premier usage). Migration recommandée — pas de
> breaking change pour les configs existantes.

| Flag | Défaut | Effet |
|------|--------|-------|
| `BEAUME_STREAM` | `1` | Streaming des tokens Ollama → HUD en temps réel (premier token <3s) |
| `BEAUME_PROFILE` | `0` | Active le profilage par étape (logs `lucie.profiling`) |
| `BEAUME_OLLAMA_KEEP_ALIVE` | `24h` | Durée avant déchargement du modèle Ollama (évite le reload ~2-3s entre calls) |
| `BEAUME_SPEED_MODEL` | `gemma4:e4b` | Modèle « rapide » utilisé pour les niveaux 1 et 2 |

### `OLLAMA_KEEP_ALIVE=24h` (défaut)

Par défaut, Ollama décharge chaque modèle ~5 minutes après le dernier appel. Sur un pipeline multi-LLM comme Beaume, ce comportement provoque un reload de ~2-3s par appel (soit ~6-9s cumulés sur un niveau 3).

Beaume force `keep_alive=24h` sur chaque requête `/api/generate` pour garder le modèle en RAM toute la journée.

**Impact mémoire** : `gemma4:e4b` mobilise ~4-5 Go de RAM en continu. Recommandé : M-series 16 Go+. Si RAM limitée, abaisser le flag :

```bash
# Décharger le modèle après 5 minutes d'inactivité
export BEAUME_OLLAMA_KEEP_ALIVE=5m

# Décharger immédiatement après chaque call (comportement historique)
export BEAUME_OLLAMA_KEEP_ALIVE=0s
```

Valeur passée telle quelle à Ollama — supporte tous les formats documentés (`30m`, `2h`, `-1` pour persistant illimité).

---

## ✨ Fonctionnalités

| Fonctionnalité | Statut | Description |
|----------------|--------|-------------|
| **AccountingAgent + FEC** | ✅ | Traitement de factures en lot, export FEC conforme DGFiP |
| **SmartMailAgent** | ✅ | Classification intelligente des mails (4 niveaux d'urgence) via LLM |
| **QuantumRouter** | ✅ | Routage adaptatif avec fusion et superposition quantique |
| **CryptoInvestorAgent** | ✅ | Suivi de portefeuille crypto, analyse de risque, reporting fiscal |
| **Sandboxing agents** | ✅ | Sous-processus isolés via `sandbox-exec` macOS + IPC chiffré AES-256-GCM |
| **Chiffrement au repos** | ✅ | AES-256 pour toutes les données persistées |
| **Commande vocale** | ✅ | Wake word local ("Hey Jarvis") + Whisper |
| **RAG local** | ✅ | FAISS + embeddings Ollama, 100% offline |
| **EventBus authentifié** | ✅ | Communication inter-agents sécurisée |
| **CircuitBreaker** | ✅ | Résilience automatique avec fallback gracieux |
| **Contrôle macOS natif** | ✅ | Clic, frappe, lecture d'UI via Accessibility APIs |
| **Export FacturX** | 🚧 | Factures électroniques au format FacturX |
| **LegalResearchAgent** | ✅ | Base juridique Légifrance live, sync auto 48h ([détails](#-base-juridique-légifrance)) |
| **Installeur .dmg** | 🚧 | Distribution native macOS |

---

## 📚 Base juridique Légifrance

Beaume embarque une **base Légifrance locale** alimentée par le dump officiel DILA (`echanges.dila.gouv.fr/OPENDATA/LEGI/`, Licence Ouverte Etalab). Zéro API externe, zéro clé, 100% local — cohérent avec la promesse du projet : **sources vérifiables, jamais d'hallucination.**

### Ce que ça couvre

6 éditions juridiques mappées dans `lucie_v1_standalone/knowledge_legifrance/theme_mapping.yaml` :

| Édition | Code(s) source | Filtres |
|---------|---------------|---------|
| Droit Social | Code du travail | L1000–L1999, R1000–R1999 |
| Baux Commerciaux | Code de commerce | L145-*, R145-* |
| Divorce & Famille | Code civil | 212-515-7 |
| Sociétés | Code de commerce | L210-*, L225-*, L227-* |
| Prud'hommes | Code du travail + CPC | R/L 1411-*, + référé |
| Expert-Comptable | CGI | * |

Ajouter une édition = éditer le YAML, relancer `legifrance_sync.py --force`. Pas de re-sync complet.

### Installation (première fois, full dump ≈ 1,1 Go)

```bash
# Activer la base Légifrance (off par défaut)
export BEAUME_LEGIFRANCE=1

# Optionnel : override du répertoire (défaut : ~/Library/Application Support/Beaume/legifrance/)
export BEAUME_LEGIFRANCE_DIR=/chemin/custom

# Premier sync (full + incrémentaux depuis la publication initiale, 20-40 min)
python scripts/legifrance_sync.py --first-run

# Mode rapide dev/CI avec tarball fixture (≤10 KB, 6 articles canoniques)
python scripts/legifrance_sync.py --first-run --sample tests/fixtures/sample.tar.gz

# Status
python scripts/legifrance_sync.py --status
```

### Sync automatique toutes les 48h (macOS)

```bash
# Installer l'agent launchd (écrit ~/Library/LaunchAgents/com.beaume.legifrance.sync.plist)
bash scripts/install_launchd.sh

# Vérifier
launchctl list | grep com.beaume.legifrance

# Désinstaller
bash scripts/uninstall_launchd.sh

# Migration depuis un ancien job com.lucie.legifrance.sync (Sprint 1ter, à lancer une fois) :
bash scripts/migrate_launchd_lucie_to_beaume.sh
```

L'agent `launchd` réveille `legifrance_sync.py --incremental` toutes les 172 800 s (48 h). `RunAtLoad=false` pour ne jamais bloquer le démarrage. Logs : `~/Library/Logs/Beaume/legifrance_sync.{out,err}.log`.

### Audit & traçabilité

Chaque sync écrit une entrée `legifrance_sync` signée HMAC-SHA256 dans l'`AuditTrail` (`~/.lucie/audit.db`) : liste des archives appliquées, SHA256 de la DB finale, diff human-readable (articles ajoutés / modifiés / abrogés, max 50 lignes).

### Coût disque

| Élément | Taille typique |
|---------|----------------|
| DB SQLite (`legi.sqlite`) | ~3 Go (full LEGI) |
| Tarballs (conservés 7 jours) | ~50 Mo / semaine incrémental |
| Total steady-state | ~3,1 Go |

### Rollback

```bash
# Dry-run
bash scripts/legifrance_rollback.sh --dry-run

# Exécution (retire DB, tarballs, agent launchd)
bash scripts/legifrance_rollback.sh --yes
```

En cas de rollback, Beaume retombe automatiquement sur la base curatée `knowledge/droit_social/licenciement_economique/` (feature flag OFF). Zéro régression pipeline.

---

## 🛡 Sécurité

### Le vrai argument sécurité : local-first

La garantie principale de Beaume est architecturale : **vos données ne quittent jamais votre machine.** Aucun cloud, aucune API externe, aucune possibilité d'exfiltration vers des serveurs tiers. Pour un professionnel réglementé, c'est la seule garantie qui vaille vraiment.

### Ce qui est sécurisé au niveau système

| Module | Code | Ce que ça fait réellement |
|--------|------|--------------------------|
| **Agent Sandboxing** | SEC-01 | `sandbox-exec` macOS — chaque agent tourne dans un sous-processus isolé avec profil `.sb` restrictif (filesystem, réseau, syscalls limités). IPC via socket Unix + AES-256-GCM. |
| **Chiffrement au repos** | SEC-02 | AES-256 via `cryptography` (backed by OpenSSL/C) — toutes les données de `~/.lucie/` sont chiffrées au repos. |
| **Protection mémoire clés** | SEC-03 | Clés cryptographiques dans des buffers `ctypes` verrouillés en RAM via `mlock` (prévient le swap sur disque). Secrets scannés et redactés avant tout traitement LLM. |
| **Intégrité des agents** | SEC-04 | Hachage SHA-256 des fichiers agents au démarrage — détecte toute modification non autorisée. |

### Garde-fous applicatifs (Python, pas OS-level)

Ces modules apportent une valeur réelle, mais sont implémentés en Python : un attaquant avec accès système peut les contourner. Ce sont des **garde-fous applicatifs**, pas des protections système :

| Module | Code | Ce que ça fait |
|--------|------|----------------|
| **Security Response** | SEC-05 | Réponse automatisée aux événements internes — termine les agents anormaux, publie des alertes via EventBus. |
| **Content Filter** | SEC-06 | Heuristiques réseau (psutil) sur les connexions sortantes + filtrage regex de données sensibles (NIR, IBAN, CB, clés API). Alerte — ne bloque pas au niveau OS. |

> **Sur `sandbox-exec`** : utilisé par Beaume pour l'isolation inter-processus, `sandbox-exec` est officiellement déprécié depuis macOS 13 mais continue de fonctionner. Il sera remplacé par le vrai **macOS App Sandbox** lors de la distribution en `.dmg` — c'est là que résidera l'isolation système certifiée Apple.

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

> *« J'ai créé Beaume parce que l'IA devrait tourner là où vivent vos données — sur votre machine. »*

---

<div align="center">

⭐ **Star ce repo si vous croyez en l'IA locale.**

*Beaume v0.2.0-beta — données 100% locales, chiffrées, souveraines.*

</div>
