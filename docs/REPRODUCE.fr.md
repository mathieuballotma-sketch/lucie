# Reproduire les chiffres du README

*[Read in English](REPRODUCE.md)*

Cette recette explique comment lancer Beaume en local et reproduire
les métriques de fiabilité affichées dans le README (notamment la
batterie 16 questions multi-angles à 62,5 %, mesurée 2026-05-12).

---

## Prérequis matériel & logiciel

| Composant | Version / spec |
|-----------|----------------|
| Mac Apple Silicon | M2 avec 16 Go ou plus, tous les M3, tous les M4, tous les M5 |
| RAM | 16 Go minimum, 24 Go recommandé pour `gemma4:e4b` |
| Disque libre | ~10 Go (modèle Ollama + KB Légifrance compactée) |
| macOS | 13 Ventura ou supérieur |
| Python | 3.11 ou supérieur |
| Ollama | dernière version stable (`brew install ollama`) |

---

## Installation

```bash
# 1. Récupérer le code
git clone https://github.com/mathieuballotma-sketch/lucie.git beaume
cd beaume

# 2. Lancer Ollama et tirer le modèle
ollama serve &
ollama pull gemma4:e4b

# 3. Environnement Python — Python 3.11 explicite obligatoire
#    (le python3 système macOS est en 3.9 par défaut et échouera)
python3.11 -m venv venv
source venv/bin/activate

# 4. Installer les dépendances avec --no-deps
#    Raison : requirements.txt a des pins trop contraints
#    (transformers==5.2.0 entre en conflit avec sentence-transformers 3.3.1
#    qui exige transformers<5.0.0). --no-deps installe chaque version pinnée
#    telle quelle en bypassant le resolver pip. Workaround temporaire connu ;
#    un repin propre est dans le backlog.
pip install -r requirements.txt --no-deps

# 5. (Optionnel) installer la KB Légifrance locale
# Le fichier SQLite 4,6 Go n'est PAS dans le repo (ignoré par .gitignore).
# Voir lucie_v1_standalone/knowledge_legifrance/README pour la procédure
# de génération à partir des archives DILA publiques.
# Beaume tourne sans : fallback sur la KB curatée locale 80 Ko
# (lucie_v1_standalone/knowledge/droit_social/), et le mode corpus
# (`--corpus fr_pharma_ansm --no-llm`) est 100% offline déterministe.
```

---

## Lancer le HUD

```bash
PYTHONPATH=. python3 main_hud.py
```

Une fenêtre native macOS s'ouvre. Tapez une question de droit social
français — par exemple : *« Quel est le délai d'envoi de la lettre de
licenciement économique après l'entretien préalable ? »*.

---

## Reproduire la batterie 16q (62,5 %)

```bash
# Flags Sprint 6 P2a activés
export BEAUME_RETRIEVER_DEBRIDE=1
export BEAUME_VERIFICATEUR_NORMALISE=1

# Batterie ciblée (10 questions de catégorie lic_eco)
python3 bench/run_legal_traps.py \
  --prompts bench/swiss_watch_50.json \
  --filter SW-LECO \
  --json bench/results/_repro_16q.json
```

Le script imprime un récapitulatif PASS/FAIL et écrit un JSON détaillé
(`verifier_score`, citations validées, citations invalidées, refus
déterministes).

Comparer avec [`bench/results/2026-05-12_battery_16q_post_p2a.md`](../bench/results/2026-05-12_battery_16q_post_p2a.md).
Un écart de quelques % par run est normal — le LLM Gemma 4 e4b n'est
pas déterministe (température > 0). Sur 5 runs successifs, la
fiabilité reste typiquement dans une plage de ±5 %.

---

## Reproduire la batterie 50q

```bash
export BEAUME_RETRIEVER_DEBRIDE=1
export BEAUME_VERIFICATEUR_NORMALISE=1

python3 bench/run_legal_traps.py \
  --prompts bench/swiss_watch_50.json \
  --json bench/results/_repro_50q.json
```

Note : la mesure 50q clean est en cours de stabilisation au moment où
ce fichier est écrit. Voir
[`bench/results/2026-05-12_battery_50q_post_p2a.md`](../bench/results/2026-05-12_battery_50q_post_p2a.md)
pour le statut courant.

---

## Lancer les tests unitaires

```bash
pytest tests/ -v --ignore=tests/integration --ignore=tests/llm
```

Voir [`tests/README.fr.md`](../tests/README.fr.md) pour la couverture par
dossier et les options de filtrage.

---

## Si quelque chose ne reproduit pas

1. Vérifier que `ollama serve` tourne bien (`curl http://127.0.0.1:11434/api/tags`).
2. Vérifier la version du modèle (`ollama list`) — un Gemma plus
   ancien ou un autre quant donnera des chiffres différents.
3. Vérifier les flags d'environnement (`env | grep BEAUME_`).
4. Ouvrir une issue GitHub avec le contenu de `bench/results/_repro_*.json`.

La transparence radicale impose qu'un écart non explicable soit
documenté plutôt qu'ignoré.
