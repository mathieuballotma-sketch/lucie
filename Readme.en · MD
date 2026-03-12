# 🧠 Agent Lucie

> **Local, sovereign, multi-agent AI assistant — 100% offline on macOS.**
> Built-in digital immune system that detects, neutralizes and learns from threats.

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/macOS-13+-000000?style=for-the-badge&logo=apple&logoColor=white"/>
  <img src="https://img.shields.io/badge/Ollama-local-74aa9c?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Status-Active%20Development-orange?style=for-the-badge"/>
</p>

<p align="center">
  <a href="README.md">🇫🇷 Français</a> •
  <a href="README.en.md">🇬🇧 English</a> •
  <a href="README.zh.md">🇨🇳 中文</a> •
  <a href="README.es.md">🇪🇸 Español</a>
</p>

---

## 🚧 Important notice — work in progress

> Agent Lucie is a **personal project**, developed and maintained by **a single person**.
> I handle everything alone — development, testing, bug fixes and architecture — all at the same time.

- ✅ The **decision-making brain** (Cortex, routing, fallback) works well
- ✅ The **immune system** (CyberAgent, HealerAgent) is fully operational
- ⚠️ **Computer control** is under active development — some actions may not work or behave unexpectedly
- ⚠️ **Document generation** works but may produce imperfect results
- 🔄 Fixes and improvements are made **every day**

I prefer to be **completely honest** rather than oversell something unfinished.
Feel free to open an issue if you run into a problem! 🙏

---

## 🎯 What is Agent Lucie?

Agent Lucie is an AI assistant that runs **entirely on your Mac**, without sending any data to the internet. No subscription, no cloud, no dependency on OpenAI or Google.

---

## ✨ Features

### 🤖 Decision-making brain
| Feature | Status |
|---|---|
| Adaptive Cortex — 9 execution paths | ✅ Stable |
| Automatic routing learning | ✅ Stable |
| Intelligent fallback between paths | ✅ Stable |
| LLM circuit breaker | ✅ Stable |

### 🏗️ Agent structure — the first brick *(in development)*

> **What you see here is just the beginning.**

Access to Notes, Mail, Safari, Word and other applications is not an end in itself — it's the **foundation**. Each integrated application becomes an anchor point for a specialized agent capable, ultimately, of acting **in a fully autonomous way**, without human intervention.

The final goal: you say what you want, and Agent Lucie handles it entirely — drafting and sending an email, creating a full report, organizing your day, monitoring your files — **while you do something else**.

| Feature | Status | Vision |
|---|---|---|
| Open applications (Notes, Mail, Safari...) | ⚠️ In progress | 1st brick — access established |
| Type text | ⚠️ In progress | Foundation for automated input |
| Click, move mouse, take screenshots | ⚠️ In progress | Foundation for hands-free navigation |
| Organize windows | ⚠️ In progress | Foundation for workspace management |
| Create reminders | ⚠️ In progress | Foundation for autonomous time management |
| **Full automation without intervention** | 🔮 Coming soon | The final goal |

### 🛡️ Digital immune system
| Feature | Status |
|---|---|
| CyberAgent — anomaly detection | ✅ Stable |
| HealerAgent — YARA scan + quarantine | ✅ Stable |
| Active decoys | ✅ Stable |
| Immune memory | ✅ Stable |

### 🧠 Memory & context
| Feature | Status |
|---|---|
| Episodic memory (ChromaDB) | ✅ Stable |
| User profile | ✅ Stable |
| Memory Manager | ✅ Stable |

---

## 🛡️ Digital immune system

### 🔍 CyberAgent
Continuously monitors internal system events. When a tool fails repeatedly, it calculates a severity score, triggers an alert, and can temporarily **quarantine** the failing tool.

### 🩺 HealerAgent
Watches newly created or modified files. Uses a **malicious hash database** and **YARA rules** to detect threats. When a threat is detected:
- The file is moved to `~/AgentLucide/quarantine/`
- A **harmless decoy** is created in its place
- Any access attempt to the decoy is tracked and reported

---

## 🏗️ Architecture

```
Agent Lucie
├── 🧠 Cortex              — main orchestrator (9 paths, learning router)
├── 🤖 Agents              — Computer, Document, Knowledge, Cyber, Healer, Reminder, Planner...
├── 💾 Memory              — working memory + episodic (ChromaDB) + Memory Manager
├── ⚡ Event Bus           — inter-agent communication (synchronous, thread-safe)
├── 🛡️ Immune system       — CyberAgent (detection) + HealerAgent (healing)
└── 🔌 Providers           — Ollama (100% local)
```

---

## 🚀 Installation

```bash
# 1. Clone the project
git clone https://github.com/mathieuballotma-sketch/Agent-Lucie.git
cd Agent-Lucie

# 2. Install dependencies
pip install -r requirements.txt

# 3. Download LLM models
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b  # optional — requires 24 GB RAM

# 4. Launch the agent
python main.py
```

### ⚙️ Required macOS permissions
- ✅ Accessibility → allow Terminal
- ✅ Automation → allow Terminal
- ✅ Screen Recording → for screenshots

---

## 🛠️ Tech stack

| Component | Technology |
|---|---|
| Local LLM | Ollama — qwen2.5 (0.5B → 14B) |
| Vector memory | ChromaDB |
| Embeddings | sentence-transformers |
| macOS control | PyAutoGUI + AppleScript + NSWorkspace |
| Malware detection | YARA + hash signatures |
| Metrics | Prometheus |
| Async I/O | asyncio + aiofiles + aiosqlite |

---

## 👨‍💻 Author

**Mathieu Bellot** — independent developer, 100% personal open-source project.
Building Agent Lucie alone, with the conviction that AI should be **local, sovereign and accessible to everyone**.

---

## ⚠️ Disclaimer

This project manipulates applications, files and settings on your Mac.
Provided **as is**, without warranty of any kind.
**Use at your own risk.**