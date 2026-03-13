markdown<div align="center">

# ✦ LUCIE

### L'IA qui vous appartient vraiment.

[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-black.svg)](https://python.org)
[![macOS](https://img.shields.io/badge/macOS-native-black.svg)]()
[![Ollama](https://img.shields.io/badge/Ollama-local-black.svg)](https://ollama.ai)
[![Stars](https://img.shields.io/github/stars/TON_USERNAME/lucie?style=social)]()

**Zéro cloud. Zéro abonnement. Zéro compromis.**

[Démarrer →](#installation) · [Voir la démo](#démo) · [Rejoindre la communauté](#communauté)

---

*"La première IA locale qui agit vraiment — elle ne répond pas, elle fait."*

</div>

---

## Le problème que tout le monde ignore

ChatGPT, Claude, Gemini — vous payez chaque mois pour **prêter votre cerveau à quelqu'un d'autre**.

Vos conversations. Vos projets. Vos idées. Tout part sur leurs serveurs.

Et demain, si ils augmentent les prix ? Si ils ferment le service ? Si ils décident que votre usage ne correspond plus à leurs conditions ?

**Vous perdez tout.**

---

## Lucie est différente

Lucie tourne sur votre Mac. Dans votre RAM. Sur votre disque.

Personne d'autre n'y accède. Jamais.
```
Vous posez une question
        ↓
Lucie réfléchit sur votre machine
        ↓
Lucie agit — crée un fichier, cherche sur le web, 
             organise vos données, code, rédige
        ↓
Vous obtenez un résultat
        ↓
Rien n'a quitté votre ordinateur
```

---

## Ce que Lucie peut faire

### 🧠 Elle pense avec le bon cerveau

Lucie ne choisit pas un seul modèle — elle orchestre une flotte entière :

| Tâche | Modèle choisi automatiquement |
|-------|-------------------------------|
| Écrire du code | Codestral |
| Raisonner | DeepSeek-R1 |
| Rédiger en français | Gemma2 |
| Analyser une image | LLaVA |
| Question rapide | Qwen2.5 0.5b |
| Tâche complexe | Qwen2.5 14b |
| Vous connaître | *votre-prénom*-ia |

### 💾 Elle se souvient

Lucie indexe chaque conversation dans un moteur vectoriel FAISS.
```
Conversation 1 : "Mon langage préféré est Rust"
[3 jours plus tard]
Vous : "Quel outil me conseillerais-tu ?"
Lucie : "Étant donné que tu travailles en Rust..."
```

Pas de copier-coller. Pas de répétition. Elle sait.

### ⚡ Elle agit

Lucie ne répond pas — elle **fait**.
```
"Crée un résumé de mes capacités et 
 sauvegarde-le sur mon bureau"

→ PlannerAgent décompose la tâche
→ CreatorAgent rédige le contenu  
→ FileAgent sauvegarde le fichier
→ "Voilà, c'est fait."
```

### 🎭 Elle vous appartient

Au premier lancement, Lucie apprend votre prénom et crée automatiquement votre modèle personnel — `votre-prénom-ia` — entraîné sur votre contexte.

C'est votre IA. Littéralement.

---

## Architecture
```
┌─────────────────────────────────────────┐
│                   HUD                   │
│         Interface verre natif macOS     │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│              FrontalCortex              │
│    Router intelligent · Circuit Breaker │
│    Pipeline multi-agents · EventBus     │
└──────┬───────────┬────────────┬─────────┘
       │           │            │
  ┌────▼───┐  ┌────▼───┐  ┌────▼────┐
  │ Agents │  │ Memory │  │ Models  │
  │ 13+    │  │ FAISS  │  │ 18+     │
  │ async  │  │ SQLite │  │ Ollama  │
  └────────┘  └────────┘  └─────────┘
```

---

## Installation

### Prérequis
```bash
# macOS 12+ requis
# Python 3.11+
# Ollama installé → https://ollama.ai
```

### En 3 commandes
```bash
git clone https://github.com/TON_USERNAME/lucie
cd lucie
./setup.sh
```

Le script installe automatiquement les dépendances et télécharge les modèles essentiels.

### Premier lancement
```bash
python main_hud.py
```

Lucie vous accueille. Elle apprend votre prénom. Elle devient vôtre.

---

## Démo

> *GIF à venir — contribution bienvenue*

---

## Modèles supportés

Lucie fonctionne avec n'importe quel modèle Ollama. 
Les modèles recommandés sont téléchargés automatiquement.
```bash
ollama list  # voir vos modèles disponibles
```

---

## Roadmap

- [x] HUD natif macOS translucide
- [x] Router de modèles intelligent
- [x] Mémoire vectorielle FAISS
- [x] Pipeline multi-agents
- [x] Onboarding personnalisé
- [ ] P2P chiffré entre instances Lucie
- [ ] Fine-tuning local automatique
- [ ] Plugin système (Spotlight, raccourcis)
- [ ] Support Windows / Linux

---

## Contribuer

Lucie est open-source parce que l'IA privée devrait être accessible à tous — pas seulement à ceux qui peuvent payer 20€/mois indéfiniment.
```bash
# Fork → Clone → Branch → PR
git checkout -b feature/ma-feature
```

Toutes les contributions sont les bienvenues — 
code, documentation, modèles, idées.

---

## Communauté

> *Discord / discussions GitHub à venir*

---

## Licence

MIT — faites-en ce que vous voulez.

---

<div align="center">

**Lucie n'est pas un produit.**
**C'est un droit.**

*Le droit d'avoir une IA qui vous appartient vraiment.*

---

⭐ Si Lucie vous parle, une étoile aide énormément.

</div>