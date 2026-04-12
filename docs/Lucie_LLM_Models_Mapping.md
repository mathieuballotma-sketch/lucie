# Lucie — Mapping LLM spécialisés par Agent

**Date** : 2026-03-26
**Contrainte** : 24 Go RAM (Mac Apple Silicon), lazy loading des agents

---

## Résumé exécutif

7 modèles Ollama couvrent les 13+ agents de Lucie, avec un pic RAM simultané de ~15 Go grâce au lazy loading.

---

## Mapping complet

### 1. FrontalCortex — Routage & Orchestration

| Modèle | `qwen3:8b` |
|---|---|
| RAM | ~5 Go |
| Pourquoi | Architecture MoE (Mixture of Experts), excellente en classification et routage rapide. Remplace qwen2.5:3b comme routeur principal avec une compréhension bien supérieure des intentions utilisateur. |
| Alternative | `qwen2.5:3b` (si RAM limitée, 2 Go) |

### 2. CodeDebugAgent + ComputerControlAgent + FileAgent + DocumentAgent — Code & Système

| Modèle | `qwen2.5-coder:7b` |
|---|---|
| RAM | ~5 Go |
| Pourquoi | Meilleur modèle code open-source dans sa catégorie. Surpasse DeepSeek-Coder 6.7b sur HumanEval, MBPP, et MultiPL-E. Excellente compréhension Python, shell, AppleScript. |
| Agents | CodeDebugAgent, ComputerControlAgent (AppleScript/shell), FileAgent (scripts fichiers), DocumentAgent (génération code pour docx/pdf/xlsx) |
| Alternative | `deepseek-coder-v2:6.7b` |

### 3. CreatorAgent + Summarizer + Safari Research — Génération & Synthèse

| Modèle | `mistral:7b` |
|---|---|
| RAM | ~5 Go |
| Pourquoi | Excellent ratio qualité/taille pour la génération de texte. Fluide en français et anglais. Très bon pour la synthèse, la reformulation et la création de contenu. |
| Agents | CreatorAgent (rédaction), Summarizer (résumés), SafariResearchWorkflow (synthèse de recherche web) |
| Alternative | `gemma2:9b` (meilleur mais +4 Go) |

### 4. Finance + DataAnalyst + Research — Raisonnement & Analyse

| Modèle | `phi4:14b` |
|---|---|
| RAM | ~10 Go |
| Pourquoi | Meilleur modèle de sa taille pour le raisonnement mathématique, l'analyse de données et la logique complexe. Benchmark MATH et GSM8K de premier plan. Parfait pour les analyses financières et les rapports de recherche approfondis. |
| Agents | Finance (calculs, projections), DataAnalyst (statistiques, patterns), Research (raisonnement multi-étapes) |
| Note | Modèle le plus lourd — chargé uniquement quand un agent finance/data/research est activé |
| Alternative | `qwen2.5:7b` (si 10 Go est trop) |

### 5. Translator — Multilingue

| Modèle | `gemma2:2b` |
|---|---|
| RAM | ~1.5 Go |
| Pourquoi | Excellent support multilingue dans un format ultra-compact (2B params). Google l'a entraîné sur 27 langues. Parfait pour les traductions rapides sans charger un gros modèle. |
| Agents | Translator |
| Alternative | `aya:8b` (meilleur multi-langue mais 5 Go) |

### 6. KnowledgeAgent — Embeddings

| Modèle | `mxbai-embed-large` (inchangé) |
|---|---|
| RAM | ~1.2 Go |
| Pourquoi | Déjà en place, excellent pour FAISS + RAG vectoriel. Pas besoin de changer. |
| Agents | KnowledgeAgent (embeddings), LocalSearchEngine, FAISS classifier |

### 7. KnowledgeAgent — Génération RAG

| Modèle | `qwen2.5:3b` (inchangé) |
|---|---|
| RAM | ~2 Go |
| Pourquoi | Léger, rapide, suffisant pour générer des réponses à partir du contexte RAG. Déjà utilisé pour la classification. |
| Agents | KnowledgeAgent (génération), classification de requêtes |

---

## Budget RAM

| Scénario | Modèles chargés | RAM utilisée |
|---|---|---|
| **Idle** | mxbai-embed-large + qwen2.5:3b | ~3.2 Go |
| **Tâche simple** (chat, recherche) | + qwen3:8b + mistral:7b | ~13.2 Go |
| **Tâche code** | + qwen3:8b + qwen2.5-coder:7b | ~13.2 Go |
| **Tâche finance/analyse** | + qwen3:8b + phi4:14b | ~18.2 Go |
| **Worst case** (tout actif) | 7 modèles | ~24.7 Go ⚠️ |

> **Note** : Le worst case ne devrait jamais arriver grâce au lazy loading.
> Ollama décharge automatiquement les modèles inactifs après quelques minutes.
> En pratique, max 3-4 modèles chargés simultanément = ~15 Go.

---

## Commandes d'installation Ollama

```bash
# Garder (déjà installés)
# mxbai-embed-large, qwen2.5:3b

# Mettre à jour / Ajouter
ollama pull qwen3:8b
ollama pull qwen2.5-coder:7b
ollama pull mistral:7b
ollama pull phi4:14b
ollama pull gemma2:2b

# Supprimer (remplacés)
ollama rm deepseek-coder:6.7b
ollama rm qwen2.5:7b  # remplacé par mistral:7b + qwen3:8b
```

---

## Intégration dans config.yaml

```yaml
models:
  router: "qwen3:8b"            # FrontalCortex, Thalamus
  code: "qwen2.5-coder:7b"      # CodeDebug, ComputerControl, File, Document
  generation: "mistral:7b"       # Creator, Summarizer, Safari Research
  reasoning: "phi4:14b"          # Finance, DataAnalyst, Research
  translation: "gemma2:2b"       # Translator
  embedding: "mxbai-embed-large" # FAISS, RAG
  lightweight: "qwen2.5:3b"     # KnowledgeAgent RAG gen, classification
```

---

## Prochaines étapes

1. [ ] Mettre à jour `app/core/config.py` pour supporter le mapping multi-modèles
2. [ ] Modifier `BaseAgent.ask_llm()` pour sélectionner le modèle selon le type d'agent
3. [ ] Mettre à jour `app/providers/provider_manager.py` pour le routage de modèles
4. [ ] Installer les nouveaux modèles via Ollama
5. [ ] Tester chaque agent avec son modèle spécialisé
6. [ ] Benchmark avant/après (qualité + vitesse)
