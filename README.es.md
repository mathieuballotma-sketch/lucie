# 🧠 Agent Lucie

> **Asistente de IA local, soberano y multi-agente — 100% sin conexión en macOS.**
> Sistema inmunológico digital integrado que detecta, neutraliza y aprende de las amenazas.

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/macOS-13+-000000?style=for-the-badge&logo=apple&logoColor=white"/>
  <img src="https://img.shields.io/badge/Ollama-local-74aa9c?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Licencia-MIT-yellow?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Estado-En%20desarrollo-orange?style=for-the-badge"/>
</p>

<p align="center">
  <a href="README.md">🇫🇷 Français</a> •
  <a href="README.en.md">🇬🇧 English</a> •
  <a href="README.zh.md">🇨🇳 中文</a> •
  <a href="README.es.md">🇪🇸 Español</a>
</p>

---

## 🚧 Aviso importante — proyecto en desarrollo

> Agent Lucie es un **proyecto personal**, desarrollado y mantenido por **una sola persona**.
> Me encargo de todo solo — desarrollo, pruebas, corrección de errores y arquitectura — todo al mismo tiempo.

Lo que esto significa en la práctica:

- ✅ El **cerebro de decisión** (Cortex, enrutamiento, fallback) funciona bien
- ✅ El **sistema inmunológico** (CyberAgent, HealerAgent) está completamente operativo
- ⚠️ El **control del ordenador** (abrir apps, escribir texto, organizar ventanas) está **en desarrollo activo** — algunas acciones pueden no funcionar o comportarse de forma inesperada
- ⚠️ La **generación de documentos** funciona pero puede producir resultados imperfectos
- 🔄 Se realizan correcciones y mejoras **cada día**

Prefiero ser **completamente honesto** antes que vender algo inacabado.
¡Gracias por su comprensión — no dude en abrir un issue si encuentra algún problema! 🙏

---

## 🎯 ¿Qué es Agent Lucie?

Agent Lucie es un asistente de IA que funciona **completamente en tu Mac**, sin enviar ningún dato a internet. Sin suscripción, sin nube, sin dependencia de OpenAI o Google.

Es capaz de:
- Controlar tu ordenador mediante texto o voz
- Generar documentos Word automáticamente
- Recordar tus conversaciones pasadas
- **Proteger activamente tu sistema** contra archivos maliciosos

---

## ✨ Funcionalidades

### 🤖 Cerebro de decisión
| Funcionalidad | Estado |
|---|---|
| Cortex adaptativo — 9 rutas de ejecución | ✅ Estable |
| Aprendizaje automático de enrutamiento | ✅ Estable |
| Fallback inteligente entre rutas | ✅ Estable |
| Circuit breaker LLM | ✅ Estable |

### 🖥️ Control del ordenador *(en desarrollo)*
| Funcionalidad | Estado |
|---|---|
| Abrir aplicaciones (Notes, Mail, Safari...) | ⚠️ En progreso |
| Escribir texto | ⚠️ En progreso |
| Clic, mover ratón, capturas de pantalla | ⚠️ En progreso |
| Organizar ventanas (lado a lado, cuadrícula) | ⚠️ En progreso |
| Crear recordatorios | ⚠️ En progreso |

### 🛡️ Sistema inmunológico digital
| Funcionalidad | Estado |
|---|---|
| CyberAgent — detección de anomalías | ✅ Estable |
| HealerAgent — escaneo YARA + cuarentena | ✅ Estable |
| Señuelos activos | ✅ Estable |
| Memoria inmunológica | ✅ Estable |

### 🧠 Memoria y contexto
| Funcionalidad | Estado |
|---|---|
| Memoria episódica (ChromaDB) | ✅ Estable |
| Perfil de usuario | ✅ Estable |
| Memory Manager | ✅ Estable |

---

## 🛡️ Sistema inmunológico digital

Esta es la característica más original de Agent Lucie — un **verdadero sistema inmunológico** integrado de forma nativa en el asistente.

### 🔍 CyberAgent
Monitorea continuamente los eventos internos del sistema. Cuando una herramienta falla repetidamente, calcula una puntuación de gravedad, activa una alerta y puede poner en **cuarentena temporal** la herramienta defectuosa.

### 🩺 HealerAgent
Vigila los archivos recién creados o modificados. Usa una **base de hash maliciosos** y **reglas YARA** para detectar amenazas. Cuando se detecta una amenaza:
- El archivo se mueve a `~/AgentLucide/quarantine/`
- Se crea un **señuelo inofensivo** en su lugar
- Cualquier intento de acceso al señuelo es rastreado y reportado

---

## 🏗️ Arquitectura

```
Agent Lucie
├── 🧠 Cortex              — orquestador principal (9 rutas, learning router)
├── 🤖 Agentes             — Computer, Document, Knowledge, Cyber, Healer, Reminder, Planner...
├── 💾 Memoria             — working memory + episódica (ChromaDB) + Memory Manager
├── ⚡ Event Bus           — comunicación entre agentes (sincrónico, thread-safe)
├── 🛡️ Sistema inmune      — CyberAgent (detección) + HealerAgent (curación)
└── 🔌 Proveedores         — Ollama (100% local)
```

---

## 🚀 Instalación

```bash
# 1. Clonar el proyecto
git clone https://github.com/mathieuballotma-sketch/Agent-Lucie.git
cd Agent-Lucie

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Descargar modelos LLM
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b  # opcional — requiere 24 GB de RAM

# 4. Iniciar el agente
python main.py
```

---

## 🛠️ Stack tecnológico

| Componente | Tecnología |
|---|---|
| LLM local | Ollama — qwen2.5 (0.5B → 14B) |
| Memoria vectorial | ChromaDB |
| Embeddings | sentence-transformers |
| Control macOS | PyAutoGUI + AppleScript + NSWorkspace |
| Detección de malware | YARA + firmas hash |
| Métricas | Prometheus |
| I/O asíncrona | asyncio + aiofiles + aiosqlite |

---

## 👨‍💻 Autor

**Mathieu Bellot** — desarrollador independiente, proyecto personal 100% open-source.

Construyo Agent Lucie solo, con la convicción de que la IA debe ser **local, soberana y accesible para todos**.

---

## ⚠️ Aviso legal

Este proyecto manipula aplicaciones, archivos y configuraciones de tu Mac.
Se proporciona **tal cual**, sin garantía de ningún tipo.
El autor no es responsable de las acciones realizadas por el agente.
**Úsalo bajo tu propia responsabilidad.**