# Licences des modèles LLM — Agent Lucide

> Audit du 2026-03-20. À réviser à chaque ajout de modèle.

---

## ⚠️ ALERTES LÉGALES — Usage commercial incompatible

| Modèle | Licence | Problème | Alternative recommandée |
|--------|---------|----------|------------------------|
| `codestral:latest` | **MNPL** (Mistral Non-Production License) | Interdit en production / usage commercial | `deepseek-coder:6.7b` (Apache 2.0) ou `qwen2.5-coder` (Apache 2.0) |
| `llava:latest` | **CC BY-NC** (Creative Commons Non-Commercial) | Interdit tout usage commercial | `moondream:latest` (Apache 2.0) — déjà présent comme fallback |

### Utilisation dans le code

- **`codestral:latest`** : présent uniquement dans `MODEL_CATALOG` de `app/providers/model_router.py` (catégorie `code`, priorité 10). Sélectionné automatiquement pour les requêtes code si disponible sur Ollama. Aucun agent ne le référence directement par son nom.
- **`llava:latest`** : présent uniquement dans `MODEL_CATALOG` de `app/providers/model_router.py` (catégorie `vision`, priorité 10). Sélectionné automatiquement pour les requêtes vision si disponible sur Ollama. `moondream:latest` (Apache 2.0, priorité 5) est déjà le fallback.

### Recommandations immédiates

1. Ne pas installer `codestral:latest` sur les déploiements commerciaux. Utiliser `deepseek-coder:6.7b` (Apache 2.0) ou `qwen2.5-coder:7b` (Apache 2.0) comme modèle code principal.
2. Ne pas installer `llava:latest` sur les déploiements commerciaux. `moondream:latest` (Apache 2.0) est déjà disponible comme fallback vision.
3. Lors d'un usage non-commercial (recherche, usage personnel), ces modèles restent utilisables.

---

## ✅ Modèles compatibles usage commercial (Apache 2.0 / MIT)

| Modèle | Catégorie | Licence |
|--------|-----------|---------|
| `qwen3:14b` | quality | Apache 2.0 |
| `qwen2.5:14b` | quality (fallback) | Apache 2.0 |
| `qwen2.5:7b` | balanced | Apache 2.0 |
| `qwen2.5:3b` | speed | Apache 2.0 |
| `qwen2.5:0.5b` | speed (nano) | Apache 2.0 |
| `deepseek-r1:14b` | deep | MIT |
| `deepseek-r1:7b` | reasoning | MIT |
| `deepseek-coder:6.7b` | code (alt. Apache 2.0) | Apache 2.0 |
| `moondream:latest` | vision (fallback) | Apache 2.0 |
| `mistral:latest` | balanced (fallback) | Apache 2.0 |
| `mxbai-embed-large:latest` | embedding | Apache 2.0 |
| `nomic-embed-text:latest` | embedding | Apache 2.0 |

---

## ⚡ Modèles à licence conditionnelle (usage commercial sous conditions)

| Modèle | Catégorie | Licence | Condition |
|--------|-----------|---------|-----------|
| `gemma2:9b` | writing | Gemma Terms of Service (Google) | Interdit si > 2 milliards d'utilisateurs actifs mensuels |
| `llama3:latest` | balanced (fallback) | Meta LLaMA 3 Community License | Interdit si > 700 millions d'utilisateurs actifs mensuels |

> Pour Agent Lucide (outil local individuel), ces seuils sont inapplicables — usage autorisé.

---

## ❓ Modèles à vérifier

| Modèle | Catégorie | Statut |
|--------|-----------|--------|
| `gpt-oss:20b` | quality (fallback) | Modèle inconnu — licence à identifier avant déploiement |
| `mathieu-ia:latest` | mathieu | Fine-tune personnalisé — licence héritée du modèle de base à vérifier |

---

## Politique projet

- Tout nouveau modèle ajouté au `MODEL_CATALOG` **doit** avoir sa licence documentée ici.
- Les modèles avec licence non-commerciale (MNPL, CC BY-NC, etc.) doivent avoir `priority ≤ 3` pour ne jamais être sélectionnés en priorité, ou être retirés des catalogues de production.
- Fichier de référence Ollama : `ollama show <modèle>` pour afficher la licence déclarée.
