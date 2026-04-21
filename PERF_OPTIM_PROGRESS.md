# Perf Phase 1 — Carnet de reprise

**Branche** : `feat/perf-phase1-rag-optim`
**Démarrage** : 2026-04-21
**Cible** : pipeline 57s → <8s, premier token <3s
**Budget** : 2-3 jours

## Ordre d'exécution (10 optims)

| # | Optim | Priorité | Statut | Commit |
|---|---|---|---|---|
| P0 | Profilage pipeline | Bloquant | ✅ Done | 3fff5f1 |
| P1 | Streaming tokens Ollama (Python) | Absolue | ✅ Done | bcfe163 |
| P1b | Streaming HUD (append_token main thread) | Absolue | ⏳ Pending | — |
| P2 | `OLLAMA_KEEP_ALIVE=24h` | Critique | ✅ Done | — |
| P3 | Bench 3 modèles (Gemma/Qwen/Llama) | Critique | ✅ Done (pas de swap) | — |
| P4 | Hybride BM25+FAISS (RRF camembert) | Haute | ⏳ Pending | — |
| P5 | Cache LRU (TTLCache) | Haute | ✅ Done | — |
| P6 | Fusion Lecteur+Rédacteur N1/N2 | Moyenne | ⏳ Pending | — |
| P7 | Pré-router thèmes (filtre FAISS) | Basse | ⏳ Pending | — |
| P8 | Early validation articles (frozenset) | Conditionnelle | ⏳ Pending | — |
| P9 | Investigation MLX (read-only) | Optionnelle | ⏳ Pending | — |

## Décisions tech

- Embeddings : `dangvantuan/sentence-camembert-base` (dim 768, FR)
- FAISS : `IndexFlatIP` (exact cosine)
- Cache : `cachetools.TTLCache` + `asyncio.Lock`
- Structure : sous-dossiers par domaine (`perf/`, `cache/`, `validation/`, `routing/`)
- Streaming : markdown brut (pas JSON fusion) + citations regex post-hoc

## Baseline (P0) — 2026-04-21

Bench sur 5 requêtes réduites (`scripts/bench_queries.py --queries reduced`).
Rapport brut : `reports/baseline.md`.

### Résumé
- **p50** : 24 250 ms
- **moy** : 39 139 ms
- **max** : 90 345 ms (timeout Ollama)
- **n** : 5 requêtes

### Temps par étape (agrégé)
| Étape | n calls | Total (ms) | Moy/call (ms) | % total |
|---|---:|---:|---:|---:|
| level.search | 3 | 195 581 | 65 194 | 39.5% |
| llm.redacteur.search | 3 | 195 531 | 65 177 | 39.4% |
| ollama.gemma4:e4b | 2 | 104 619 | 52 309 | 21.1% |
| retriever.search | 3 | 26 | 9 | 0.0% |
| verificateur.search | 2 | 8 | 4 | 0.0% |

### Findings décisifs
1. **Retriever 0% du temps** (1-21ms) — FAISS n'apportera pas de gain temps, seulement qualité. À réévaluer critère P4.
2. **Verificateur 0% du temps** (0-8ms) — déjà programmatique, aucune optim nécessaire.
3. **LLM Rédacteur = 99% du temps.** Le goulot est unique : vitesse de génération Gemma 4 E4B + taille du prompt.
4. **Cold start Ollama** : 62s de `prompt_eval` sur le 1er call. Impact énorme du premier token.
5. **Eval speed** ≈ 22 tok/s sur gemma4:e4b — trop lent pour tenir <8s avec 450 tokens de sortie.
6. **Prompt tokens = 1180** sur N2 — Rédacteur reçoit un prompt gros (faits + sources). P6 Fusion peut réduire.
7. **Requête timeout 90s** confirme gemma4:e4b trop lent pour certaines requêtes.

### Réorientation priorités
- **P3 swap modèle** devient LE levier critique (plus que P1 streaming). Si qwen2.5:3b tourne à 60 tok/s → 450 tok/7.5s = objectif atteint.
- **P1 streaming** toujours critique UX (premier token perçu).
- **P4 FAISS** : réévaluer — gain temps nul, gain qualité incertain. **Critère d'abandon si le swap modèle règle déjà tout**.
- **P8 validation articles** : pas de cas piège dans le baseline → probablement à couper.

## P3 Bench modèles — 2026-04-21

Bench sur 5 requêtes N2 (`scripts/bench_models.py`). Rapport : `reports/bench_models.md`.

### Résultats
| Modèle | p50 pipeline | moy tok/s | score moy | erreurs |
|---|---:|---:|---:|---:|
| `gemma4:e4b` (baseline) | 43 743 ms | 17.6 | 0.40 | 0/5 |
| `qwen2.5:3b` | 35 063 ms | 11.9 | 0.40 | 0/5 |
| `llama3.2:3b` | **31 640 ms** | 11.9 | 0.40 | 0/5 |

### Décision : **pas de swap**
- Critère initial « ≥1.8× plus rapide + score ≥0.7 » non atteint : llama3.2:3b ne fait que 1.38× au p50.
- Score moy 0.40 pour les 3 modèles → **biais bench** : le retriever ne trouve pas de sources sur « Délai de préavis art. L1234-1 », « Conditions licenciement économique », « Comment saisir le CPH ? ». Les 3 LLM renvoient « Aucune source disponible » → verif = 0.
- Qualitativement équivalents quand le retriever trouve des sources (cf. N2 thématique).
- Variance gemma4:e4b plus élevée (7.3–25.8 tok/s) vs qwen/llama stables à ~12 tok/s → à garder en tête.

### Action
- On garde `gemma4:e4b` comme `SPEED_MODEL` par défaut.
- Re-bench à prévoir **après P4 FAISS hybride** (retriever améliorera la couverture de sources, donc la qualité devient discriminante).
- Flag `LUCIE_SPEED_MODEL=llama3.2:3b` utilisable pour test utilisateur.

## Optims retirées (règle de vérité)

_Section mise à jour quand un optim ne gagne rien et est retiré._

## Benchmark final

_À remplir en fin de chantier (10 requêtes, avant/après)._
