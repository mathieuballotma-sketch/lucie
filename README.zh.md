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

- ✅ El **cerebro de decisión** funciona bien
- ✅ El **sistema inmunológico** está completamente operativo
- ⚠️ El **control del ordenador** está en desarrollo activo — algunas acciones pueden no funcionar
- 🔄 Se realizan correcciones y mejoras **cada día**

¡Gracias por su comprensión! 🙏

---

## 🎯 ¿Qué es Agent Lucie?

Un asistente de IA que funciona **completamente en tu Mac**, sin enviar ningún dato a internet. Sin suscripción, sin nube, sin dependencia de OpenAI o Google.

---

## ✨ Funcionalidades

### 🤖 Cerebro de decisión
| Funcionalidad | Estado |
|---|---|
| Cortex adaptativo — 9 rutas de ejecución | ✅ Estable |
| Aprendizaje automático de enrutamiento | ✅ Estable |
| Fallback inteligente | ✅ Estable |
| Circuit breaker LLM | ✅ Estable |

### 🏗️ Estructura de agentes — el primer ladrillo *(en desarrollo)*

> **Lo que ves aquí es solo el comienzo.**

El acceso a Notes, Mail, Safari, Word y otras aplicaciones no es un fin en sí mismo — es la **base**. Cada aplicación integrada se convierte en un punto de anclaje para un agente especializado capaz, en última instancia, de actuar **de forma totalmente autónoma**, sin intervención humana.

El objetivo final: dices lo que quieres, y Agent Lucie lo gestiona completamente — redactar y enviar un email, crear un informe completo, organizar tu día — **mientras haces otra cosa**.

| Funcionalidad | Estado | Visión |
|---|---|---|
| Abrir aplicaciones (Notes, Mail, Safari...) | ⚠️ En progreso | 1er ladrillo — acceso establecido |
| Escribir texto | ⚠️ En progreso | Base para entrada automatizada |
| Clic, ratón, capturas de pantalla | ⚠️ En progreso | Base para navegación autónoma |
| Organizar ventanas | ⚠️ En progreso | Base para gestión del espacio de trabajo |
| Crear recordatorios | ⚠️ En progreso | Base para gestión autónoma del tiempo |
| **Automatización completa sin intervención** | 🔮 Próximamente | El objetivo final |

### 🛡️ Sistema inmunológico digital
| Funcionalidad | Estado |
|---|---|
| CyberAgent — detección de anomalías | ✅ Estable |
| HealerAgent — escaneo YARA + cuarentena | ✅ Estable |
| Señuelos activos | ✅ Estable |
| Memoria inmunológica | ✅ Estable |

---

## 🏗️ Arquitectura

```
Agent Lucie
├── 🧠 Cortex              — orquestador principal (9 rutas, learning router)
├── 🤖 Agentes             — Computer, Document, Knowledge, Cyber, Healer, Reminder, Planner...
├── 💾 Memoria             — working memory + episódica (ChromaDB) + Memory Manager
├── ⚡ Event Bus           — comunicación entre agentes (sincrónico, thread-safe)
├── 🛡️ Sistema inmune      — CyberAgent + HealerAgent
└── 🔌 Proveedores         — Ollama (100% local)
```

---

## 🚀 Instalación

```bash
git clone https://github.com/mathieuballotma-sketch/Agent-Lucie.git
cd Agent-Lucie
pip install -r requirements.txt
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:3b
python main.py
```

---

## 👨‍💻 Autor

**Mathieu Bellot** — desarrollador independiente, proyecto personal 100% open-source.
Construyendo Agent Lucie solo, con la convicción de que la IA debe ser **local, soberana y accesible para todos**.

---

## ⚠️ Aviso legal

Proporcionado **tal cual**, sin garantía. **Úsalo bajo tu propia responsabilidad.**