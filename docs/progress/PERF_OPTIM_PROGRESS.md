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
| P1b | Streaming HUD (append_token main thread) | Absolue | ✅ Done | — |
| P2 | `OLLAMA_KEEP_ALIVE=24h` | Critique | ✅ Done | — |
| P3 | Bench 3 modèles (Gemma/Qwen/Llama) | Critique | ✅ Done (pas de swap) | — |
| P4 | Hybride BM25+FAISS (RRF camembert) | Haute | ⏸ Reporté Phase 1bis | — |
| P5 | Cache LRU (TTLCache) | Haute | ✅ Done | — |
| P6 | Fusion Lecteur+Rédacteur N1/N2 | Moyenne | 🚫 Retiré (déjà fait par archi) | — |
| P7 | Pré-router thèmes (filtre FAISS) | Basse | ⏸ Reporté (dépend P4) | — |
| P8 | Early validation articles (frozenset) | Conditionnelle | 🚫 Retiré (baseline sans cas piège) | — |
| P9 | Investigation MLX (read-only) | Optionnelle | ⏸ Reporté Phase 2 | — |

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

### P6 — Fusion Lecteur+Rédacteur N1/N2 (retiré)
**Constat baseline** : N1/N2 ne font **qu'un seul appel LLM** (Rédacteur). Lecteur ne s'exécute que sur N3 (document). « Fusion » n'a aucun sens sur N1/N2 puisqu'il n'y a déjà qu'un seul LLM à lui seul. L'architecture actuelle est déjà optimale sur ce point — le plan initial reposait sur un diagnostic erroné (« 4-5 LLM séquentiels »).

### P8 — Early validation articles (retiré)
**Constat baseline** : aucune des 5 requêtes benchmark ne cite un article inexistant. Le gain attendu (<1s sur cas piège) ne se matérialise que si des utilisateurs tapent volontairement des refs invalides — comportement marginal en usage pro. À garder en backlog si le feedback utilisateur remonte ce cas.

### P4 — Hybride BM25+FAISS (reporté Phase 1bis)
**Constat baseline** : retriever = 0% du temps total (1-21 ms/call). FAISS + RRF améliorerait la *qualité* de retrieval (P3 bench a montré que le retriever renvoie 0 source sur plusieurs requêtes raisonnables), mais n'apporte **aucun gain temps** — le goulot est le LLM (99%).

La qualité de retrieval mérite un chantier dédié (pas perf), avec :
- Build index FAISS camembert-base (~2-3h one-shot)
- Évaluation qualité avec dataset d'évaluation réel
- Critère d'acceptation mesurable (recall@5 sur questions connues)

Reporté en Phase 1bis pour ne pas mélanger perf et qualité.

### P7 — Pré-router thèmes (reporté)
Dépend de P4 (filtre post-FAISS). Reporté avec P4.

### P9 — Investigation MLX (reporté Phase 2)
Tâche d'exploration, pas de code Phase 1. À mener en mode prototype séparé avec qwen2.5:3b vs Ollama. Reporté en Phase 2 pour garder la branche perf focalisée.

## Benchmark final

_À remplir en fin de chantier (10 requêtes, avant/après)._

---

## S1 Speed-Optimizer (2026-04-27) — TTFT before/after

**Branche** : `feat/speed-s1-ttft` (3 commits) · **Tests** : 388 verts (375 baseline + 13 nouveaux R1+R2+R3) · **ADR** : aucun nouveau (R1/R2/R3 dans le cadre des ADR existants).

### Briques livrées

| Brique | Hash | Fichiers touchés |
|--------|------|------------------|
| R2 — Warm-up keep_alive | `8558c67` | `main_hud.py` + `tests/test_warmup.py` |
| R1 — Config Gemma 4 sur mesure (DIRECT) | `5e830ef` | `lucie_v1_standalone/config.py` + `lucie_v1_standalone/tests/test_direct_params.py` |
| R3 — Streaming TTFT < 1s (instrumentation + bench) | `1068aa5` | `lucie_v1_standalone/ollama_client.py`, `lucie_v1_standalone/pipeline.py`, `scripts/bench_queries.py`, `lucie_v1_standalone/tests/test_ttft_instrumentation.py` |

### Mesures bench (5 prompts `reduced`, gemma4:e4b, 2026-04-27)

> Chiffres bruts mesurés via le nouveau harness instrumenté `scripts/bench_queries.py --queries reduced`. Pas de baseline avant-S1 disponible (le harness ne mesurait pas TTFT auparavant — c'est précisément l'objet de R3).

**Pass 1 — `--wait-warmup` (post-cold-start)** — `reports/s1_speed_after.md`
- Warm-up : **61.4 s** (cold-start mesuré, gemma4:e4b absent du cache GPU au démarrage)
- TTFT pipeline médiane (n=3 prompts qui streament) : **26 926 ms**
- TTFT pipeline min/max : 24 513 / 70 888 ms
- TTFT ollama médiane : 26 878 ms (≈ pipeline.ttft → overhead pipeline ~50 ms, négligeable)

**Pass 2 — sans warmup, KV cache chaud** — `reports/s1_speed_after_pass2.md`
- TTFT pipeline médiane : **18 167 ms**
- TTFT pipeline min/max : 14 293 / 22 470 ms
- N1 SMALL_TALK (pas de LLM) : 1 ms (cible <1s ✓)
- N2 hors-scope (refus router pré-LLM) : 0 ms (cible <1s ✓)

### Verdict honnête sur la cible TTFT < 1 s

**Cible NON ATTEINTE sur les chemins N1 direct + N2 search** (les vrais chemins LLM). Médiane ~18-27 s vs cible 1 s.

**Cible ATTEINTE** sur les chemins sans LLM (SMALL_TALK + refus hors-scope router) : <100 ms. Mais ce n'est pas l'esprit de la cible.

### Diagnostic

L'instrumentation R3 a révélé deux choses non visibles auparavant :

1. **Le pipeline overhead est négligeable** (50 ms entre pipeline.ttft et ollama.ttft). Le retriever BM25 + scope/router ne sont PAS le bottleneck.

2. **Le bottleneck est dans Ollama**, mais NON dans `prompt_eval_ms` (mesuré 2-5 s pour ~1180 tokens prompt = 230-590 t/s, normal). La quasi-totalité du TTFT est dans `eval_ms` AVANT que le 1er chunk arrive côté Python. Hypothèse forte : **buffering interne httpx ou Ollama** qui retient les premiers tokens jusqu'à un flush par batch. À investiguer.

3. **Le prompt Redacteur est gros** (~1180 tokens). Le sweep 2026-04-25 mesurait sur des prompts directs (~200-400 tokens), donc le TTFT 1478 ms du sweep n'est pas reproductible dans le pipeline complet où le Redacteur empile faits + sources + system prompt.

### Pistes pour Speed-Optimizer S2/S3 (handoff)

- **Investiguer le buffering streaming** httpx ↔ Ollama : ajouter un test bench raw-Ollama (sans pipeline) pour comparer TTFT raw vs TTFT pipeline. Si raw aussi ~18s → c'est Ollama. Si raw ~1s → c'est httpx. (R3 future : peut-être migrer vers Ollama Python SDK natif).
- **R5 cache LRU** (S3) : sur intent répété, court-circuiter Ollama → TTFT 0ms.
- **R4 routing speed/quality** (S3) : router agressif vers gemma4:e4b uniquement pour réflexes courts, garder gemma4:26b en async pour les analyses.
- **Compression prompt Redacteur** (hors brique S1, à proposer) : passer de 1180 tokens à <400 tokens en raccourcissant le system prompt et en sérialisant les sources plus densément. Gain attendu : prompt_eval -3s + eval debut plus tôt.
- **R7 migration llama-cpp** (S4) : peut résoudre le buffering streaming nativement.

