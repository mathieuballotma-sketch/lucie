<div align="center">

```
██╗     ██╗   ██╗ ██████╗██╗███████╗
██║     ██║   ██║██╔════╝██║██╔════╝
██║     ██║   ██║██║     ██║█████╗
██║     ██║   ██║██║     ██║██╔══╝
███████╗╚██████╔╝╚██████╗██║███████╗
╚══════╝ ╚═════╝  ╚═════╝╚═╝╚══════╝
```

**Confidential-First AI Assistant. 100% Local Multi-Agent System for macOS.**

[![Python](https://img.shields.io/badge/python-3.13-blue?style=flat-square&logo=python)](https://python.org)
[![macOS](https://img.shields.io/badge/macOS-Apple_Silicon_only-black?style=flat-square&logo=apple)](https://apple.com)
[![Local](https://img.shields.io/badge/cloud-0%25-brightgreen?style=flat-square)]()
[![Tests](https://img.shields.io/badge/tests-435_passed-brightgreen?style=flat-square)]()
[![License](https://img.shields.io/badge/license-BSL_1.1-amber?style=flat-square)](LICENSE)

<br/>

> **Kill your WiFi. Lucie still works.**

<br/>

[**The Problem**](#the-problem) · [**What Lucie Does**](#what-lucie-does) · [**Architecture**](#architecture) · [**Quick Start**](#quick-start) · [**Use Cases**](#use-cases) · [**Roadmap**](#roadmap)

</div>

---

## The Problem

Every AI assistant you use today — ChatGPT, Claude, Gemini — sends your data to a server you don't control.

That's a dealbreaker for:
- **Lawyers** — attorney-client privilege. Every prompt is a potential breach.
- **Accountants** — client financial data. CNOEC regulations require local processing.
- **Doctors** — patient records. CNIL + GDPR impose strict data residency.
- **Anyone who values privacy** — your conversations, files, and habits are your business.

**No existing solution combines:** local LLM + native macOS control + multi-agent orchestration + regulated-professional compliance.

Until now.

---

## The Solution

Lucie runs **100% on your Mac**. No API keys. No cloud calls. No data leaks. Ever.

- **30 specialized agents** — each powered by the right model for the job
- **Native macOS integration** — Mail, Calendar, Reminders, Safari, Finder, any app via Accessibility APIs
- **Bio-inspired orchestration** — adaptive routing, associative memory, intelligent signal prioritization
- **Compliant by design** — your data never leaves the machine. Legally defensible for regulated professionals.

---

## What Lucie Does

### Core Agents — Production-Stable

| Agent | Capability |
|-------|-----------|
| **SmartMailAgent** | Reads Apple Mail, classifies messages by urgency with LLM intelligence (4 levels), suggests contextual replies |
| **AccountingAgent** | Processes invoices in bulk — extracts structured data, auto-categorizes, reconciles with bank statements. No human in the loop. |
| **CalendarAgent** | Full read/write access to Calendar.app via natural language |
| **ReminderAgent** | Creates and manages reminders from conversational input |
| **FileAgent** | File CRUD, smart renaming, directory analysis, bulk operations |
| **DocumentAgent** | Reads PDF, Word, Excel — returns intelligent summaries and extracts |
| **SafariResearchWorkflow** | Autonomous multi-step web research via Safari, citation-aware |
| **ComputerControlAgent** | Controls any macOS application — clicks, types, reads UI state — without screen sharing |
| **WakeAgent** | Always-on wake word detection ("Hey Jarvis") + speech recognition + macOS text-to-speech, fully local |
| **KnowledgeAgent** | Semantic search across 600+ personal knowledge vectors via FAISS |
| **CodeDebugAgent** | Reads error traces, identifies root cause, suggests minimal fix |

### Experimental Agents — In Active Development

<details>
<summary>19 additional agents</summary>

| Agent | Domain |
|-------|--------|
| PlannerAgent | Multi-step task decomposition and sequencing |
| CreatorAgent | Long-form content generation and editing |
| ProfileAgent | User preference modeling, persistent across sessions |
| CyberAgent | Real-time security monitoring and anomaly detection |
| HealerAgent | Autonomous agent self-repair — detects and recovers from degraded state |
| DeceptionAgent | Honeypot infrastructure, unauthorized access detection |
| P2PNode | Distributed agent mesh networking |
| PrivacyGateway | Data flow auditing — blocks accidental external calls |
| WorkspaceAgent | macOS multi-window workspace orchestration |
| AnalyzerAgent | Log aggregation and pattern analysis |
| FixerAgent | Autonomous code correction workflows |
| RAGAgent | Context injection layer for any agent |
| VisionAgent | Screenshot interpretation and UI understanding |
| AudioAgent | Local audio transcription via Whisper |
| SchedulerAgent | Time-based task automation |
| WebSearchAgent | Intelligent web browsing via local browser instance |
| NotificationAgent | macOS Notification Center integration |
| ContactAgent | Contacts.app read/write access |
| LegalResearchAgent | Légifrance statutory search *(in progress)* |

</details>

---

## Architecture

```
User Input
     │
     ▼
FrontalCortex  ─────────────────────────────────────────┐
     │                                                   │
     ├── Adaptive Router     (5 execution paths)        │
     ├── Signal Thalamus     (priority filtering)       │
     ├── Memory Graph        (associative, persistent)  │
     └── Event Bus           (authenticated pub/sub)    │
                                                         │
                    30 Specialized Agents ───────────────┘
                         │
                         ▼
              Ollama  ·  FAISS  ·  SQLite
              (all local, all offline)
```

Multi-model architecture — different models handle different cognitive tasks. Seven models available, each assigned where it delivers the best performance-to-resource ratio.

---

## What Was Built

Lucie is the result of continuous engineering, not a weekend prototype.

**Recent milestones:**
- **157 bugs identified and resolved** in a systematic quality audit (ruff + mypy + pytest across 162 files)
- **SmartMailAgent** upgraded with zero-shot LLM classification — genuine intelligence, not keyword matching
- **AccountingAgent MVP** — end-to-end invoice processing pipeline with bank reconciliation
- **Multi-model architecture** — 7 Ollama models, each specialized for its domain
- **RAG pipeline** — FAISS vector store with Ollama embeddings, fully offline
- **435 tests** — full test suite passing, 0 failures
- **0 static errors** — ruff clean, mypy strict mode passing on all 162 source files
- **EventBus hardened** — HMAC-authenticated message passing between all agents
- **Stability pass** — every agent ships with graceful fallbacks, circuit breakers, and recovery logic

---

## Performance

| Metric | Value |
|--------|-------|
| Greeting (fast path) | 0ms |
| Agent routing | 0.05ms |
| Simple query | ~1s |
| Complex reasoning | 10–30s |
| Invoice extraction | <1s per document |
| Wake word detection | <100ms |
| Test suite | **435 passed, 0 failed** |
| Static analysis | **ruff 0 · mypy 0** across 162 files |

---

## Hardware Requirements

Apple Silicon required (M1 / M2 / M3 / M4).

| Config | RAM | Experience |
|--------|-----|------------|
| Minimum | 8 GB | Core agents, 2–3 models active |
| Recommended | 16 GB | Full multi-agent, all stable agents |
| Optimal | 24 GB+ | All 7 models, on-demand coding agent |

---

## Quick Start

```bash
git clone https://github.com/mathieuballotma-sketch/Agent-Lucie.git
cd Agent-Lucie
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
ollama pull qwen3.5:9b
PYTHONPATH=. python3 main_hud.py
```

> Lucie creates its local memory store at `~/.lucie/` on first run. No configuration required.

---

## Use Cases

**For Accountants**
Drop 200 invoices into a folder. Lucie processes each one — extracts vendor, amount, date, and VAT, categorizes by type, then reconciles against your bank export. Fully offline. No subscription. No upload. Compliant with CNOEC data handling requirements.

**For Lawyers**
Read case files, draft summaries, research applicable law — entirely on your machine. Attorney-client privilege preserved by architecture, not policy.

**For Anyone on a Mac**
Voice-activate any task. Triage your inbox intelligently. Run autonomous research. Manage your files. All of it without a single cloud call.

---

## Comparison

| Feature | Lucie | AgenticSeek | OpenInterpreter | ChatGPT |
|---------|:-----:|:-----------:|:---------------:|:-------:|
| 100% Local | ✅ | ✅ | ❌ | ❌ |
| Native macOS control | ✅ | ❌ | ❌ | ❌ |
| Multi-agent (30+) | ✅ | Basic | ❌ | ❌ |
| Multi-model (7+) | ✅ | ❌ | ❌ | ❌ |
| Mail + Calendar integration | ✅ | ❌ | ❌ | ❌ |
| Voice control | ✅ | ❌ | ❌ | ✅ (cloud) |
| Accounting automation | ✅ | ❌ | ❌ | ❌ |
| GDPR / CNIL compliant | ✅ | Partial | ❌ | ❌ |
| Cross-platform | macOS | ✅ | ✅ | ✅ |

---

## Validation

```bash
ruff check app/ --fix                                     # 0 errors
python -m mypy app/ --ignore-missing-imports --strict     # 0 errors
PYTHONPATH=. python -m pytest tests/ -x -q                # 435 passed
```

---

## Roadmap

- [x] 30 agents operational
- [x] Multi-model architecture (7 specialized models)
- [x] SmartMailAgent with LLM-based classification
- [x] AccountingAgent MVP — invoice extraction + bank reconciliation
- [x] 157 bugs resolved, 435 tests passing
- [x] ruff 0 · mypy 0 across 162 files
- [ ] LegalResearchAgent — Légifrance integration
- [ ] Demo video
- [ ] Beta release (.dmg installer)

---

## Built by

**Mathieu Bellot** — 18, France. Solo developer.

> *"I built Lucie because I believe AI should run where your data lives — on your machine."*

---

## License

[Business Source License 1.1](LICENSE) — free for personal use and research. Commercial use requires agreement.

---

<div align="center">

⭐ **Star this repo if you believe in local-first AI.**

</div>
