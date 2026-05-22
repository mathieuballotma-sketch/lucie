# Verdict bench recall@10 Sprint K-1 — 2026-05-21

**Verdict : NO-GO publication GitHub.**

Recall@10 mesuré sur full corpus VIGUEUR (672 009 articles, 50 questions swiss_watch) :
**44.44 %** (4 hits / 9 questions matchables) — très loin du seuil de 90 %.
Aucune mise à jour des docs publiques (README, CHANGELOG) n'est faite.

---

## 1. Métriques mesurées (run × 2 sur la même machine, même seed=42)

| Métrique | Run 1 | Run 2 |
|---|---|---|
| `recall_at_10` | **44.44 %** (4/9) | **44.44 %** (4/9) |
| `n_questions_total` | 50 | 50 |
| `n_questions_matchable` | **9** | **9** |
| `n_questions_hit` | 4 | 4 |
| `pass_threshold` (90 %) | ✗ | ✗ |
| `wall_clock_seconds` | 130.1 s | 24.3 s |
| latence `p50` retrieval | 219.1 ms | 186.6 ms |
| latence `p95` retrieval | 13 205.5 ms | 5 521.6 ms |
| latence `mean` retrieval | 2 626.2 ms | 1 173.8 ms |
| `n_samples_latency` | 9 | 9 |
| RAM peak (maximum resident set size) | 1 799 487 488 octets (1.79 Go) | 2 199 273 472 octets (2.20 Go) |
| Peak memory footprint | 5 256 956 424 octets (5.26 Go) | 5 072 013 856 octets (5.07 Go) |

**Note latence** : le p95 élevé inclut le cold start du modèle BGE-M3 (premier embed après chargement HF). Le p50 (≈ 200 ms) reflète mieux la latence d'une requête warm.

**Note wall_clock** : la différence run1/run2 (130 s vs 24 s) vient probablement du cache OS du modèle (run 1 charge depuis HF cache disque, run 2 depuis cache OS).

## 2. Déterminisme

- `recall_at_10` strictement identique entre run 1 et run 2 → ✅
- `n_questions_hit` strictement identique → ✅
- **`top10_rows` identiques pour les 50 questions** (vérification par comparaison position par position) → ✅

→ **Déterminisme MPS Apple Silicon confirmé** sur ce pipeline (signatures binaires quantize 1024-bit absorbent les micro-variations float MPS).

## 3. Pourquoi NO-GO selon la table de décision

| Recall mesuré | Verdict | Statut |
|---|---|---|
| ≥ 90 % et déterminisme OK | GO | n/a |
| 80–89 % ou déterminisme KO | MITIGÉ | n/a |
| **< 80 %** | **NO-GO** | ✅ s'applique (44.44 %) |

Bonus disqualifiant : `n_questions_matchable = 9 < 30` → intervalle de confiance trop large même si le recall avait été élevé.

## 4. Diagnostic (cause primaire et secondaire)

### 4.1 Cause primaire — Parser `refs_extractor` capture seulement 18 % des questions

**40 / 50 questions** (80 %) sont skippées avec la raison `no_expected_refs_in_behavior`.

Le parser `lucie_v1_standalone/knowledge_legifrance/refs_extractor.py` ne capture que les patterns `[LRD]\.\d{3,4}-\d+` (ex. `L.1233-1`, `R.4624-12`). Il ignore systématiquement :

- les références aux conventions collectives,
- les décrets nommés (« décret du 22 juin 2024 »),
- la jurisprudence (« Cass. soc. 2022 »),
- les références à des articles sans numéro complet (« article du Code du travail »),
- et tout `expected_behavior` qui décrit un comportement sans citer d'article précis.

Conséquence : le bench est aveugle à 82 % de son corpus. **Sans correction de ce parser, AUCUN bench K-1 n'est statistiquement crédible**, indépendamment de la qualité réelle du retriever binaire.

### 4.2 Cause secondaire — Biais catégoriel `lic_eco` (licenciement économique)

Sur les 9 questions matchables :
- 5 sont des `lic_eco`, et **les 5 sont MISS** (recall 0 % sur LECO)
- les 4 hits sont sur les autres catégories

`qid` MISS : `SW-LECO-001`, `SW-LECO-003`, `SW-LECO-006`, `SW-LECO-008`, `SW-LECO-010`.
Échantillon : `SW-LECO-001` attendait 6 articles ; aucun n'est dans le top-10.

Hypothèse : les articles LECO ont des formulations procédurales abstraites (PSE, ordre des licenciements, périmètres économiques) mal capturées par BGE-M3 multilingue généraliste après quantize binaire 1024-bit. La granularité sémantique fine entre, par exemple, `L.1233-3` (motif éco) et `L.1233-61` (PSE obligatoire) se perd au moment du quantize.

## 5. Pistes de remédiation chiffrées (par ordre de priorité)

### Piste 1 (BLOQUANTE pour tout futur bench) — Élargir `refs_extractor`

- **Coût estimé** : 1–2 jours dev
- **Modifications** : ajouter patterns pour conventions collectives, décrets nommés, jurisprudence
- **Impact attendu** : `n_questions_matchable` 9 → 30+ (bench statistiquement valide)
- **Risque** : faux positifs si patterns trop larges ; mitigé par tests unitaires sur `swiss_watch_50.json`
- **Sans cette piste, aucune autre mesure ne sera crédible.**

### Piste 2 — Hybride BM25 + binary (déjà documentée dans le script bench)

- **Coût estimé** : 2–3 jours dev
- **Modifications** : nouveau script `scripts/bench_recall_at_10_hybrid.py`, indexation BM25 du corpus
- **Impact attendu** : +20–40 % recall sur les questions juridiques courtes ; particulièrement efficace sur les noms d'articles cités (« L.1233-3 »)
- **Risque** : ajoute coût de stockage (index BM25 ≈ 20–50 Mo selon tokenizer), latence retrieval +20–50 ms

### Piste 3 — Re-rank top-100 par PageRank (déjà documentée dans le script bench)

- **Coût estimé** : 1 jour dev (additif au bench existant)
- **Modifications** : changer top_k brute force = 100, re-trier par PageRank descendant, prendre top-10
- **Impact attendu** : marginal sur LECO (articles centraux pas forcément les bons) ; utile sur questions générales
- **Risque** : faible

### Piste 4 — Matryoshka 2048-bit (déjà documentée dans le script bench)

- **Coût estimé** : ~60–100 h re-build pipeline (vs 58 h actuel), patcher `LONG_BITS` dans `constants.py` puis ré-embed
- **Modifications** : `LONG_BITS = 2048` + re-build de `sigs_mrl.bin` (qui passerait à ~170 Mo) ; mettre à jour le bench si LONG_BITS y est référencé
- **Impact attendu** : variable. Plus de bits = plus de granularité, mais ne corrige pas un problème de modèle inadapté
- **Risque** : si la cause vraie est BGE-M3 généraliste (cause 4.2), Matryoshka 2048 n'apporte rien

### Piste 5 — Diagnostic ciblé sur LECO avant tout fix

- **Coût estimé** : 1 jour
- **Méthode** : encoder manuellement les 5 questions LECO MISS + leurs articles attendus, calculer la cosine similarity AVANT quantize, puis après quantize, puis ranks Hamming
- **Objectif** : isoler si le problème vient de (a) BGE-M3 embed, (b) quantize 1024-bit, ou (c) brute force Hamming
- **Sans ça, le choix entre pistes 3 et 4 est aveugle.**

## 6. Ce qui est committé localement

Sur la branche `bench/sprint-k1-bge-m3-recall-2026-05-15` :

- `kb_artifacts/recall_at_10_report_run1.json`
- `kb_artifacts/recall_at_10_report_run2.json`
- `kb_artifacts/bench_verdict_2026-05-21.md` (ce fichier)
- `scripts/bench_recall_at_10.py` (patch additif latence p50/p95/mean/n_samples)

**Aucune modification de `README.md`, `README.fr.md`, `CHANGELOG.md`, `CHANGELOG.fr.md`** — truth rule respectée.

## 7. Suite recommandée

1. **Décision Mathieu** : si l'objectif est de communiquer sur K-1 publiquement, il faut d'abord exécuter la piste 1 (parser élargi) + ré-exécuter le bench pour avoir une mesure crédible. Tant que `n_questions_matchable = 9`, aucun chiffre n'est défendable, même un bon chiffre.
2. **Si l'objectif est de débloquer Beaume retrieval avant le pilote avocat de mai 2026** : exécuter pistes 5 → 1 → 2 dans cet ordre, mesurer après chacune. Ne pas re-build le pipeline (piste 4) sans avoir épuisé pistes 1-3.
3. **Ne PAS pousser cette branche sur `main` sans nouvelle discussion** : la branche peut être conservée sur GitHub pour traçabilité (push de la branche, pas de PR ouverte), mais ne doit pas être mergée dans `main` tant que le verdict reste NO-GO.

## 8. Annexes

### 8.1 Chemins logs

- `/tmp/bench_recall_run1.log` — log run 1 complet + sortie `/usr/bin/time -l`
- `/tmp/bench_recall_run2.log` — idem run 2
- `kb_artifacts/recall_at_10_report_run1.json` — report JSON détaillé (questions, top10_rows, expected_rows)
- `kb_artifacts/recall_at_10_report_run2.json` — idem run 2

### 8.2 SHA des 4 artefacts K-1 (depuis `kb_artifacts/manifest.json`)

Voir `kb_artifacts/manifest.json` — non recopiés ici pour ne pas dupliquer la source de vérité.

### 8.3 Caveat fondamental

La métrique mesurée (brute force NumPy XOR + popcount sur 672 009 × 128 octets) est une **borne supérieure** par rapport au retriever HNSW qui serait câblé en production. Le retriever HNSW approximé donnerait un recall ≤ 44.44 %, jamais supérieur. Donc le verdict NO-GO est conservateur — la situation réelle en prod est probablement pire.

### 8.4 Discordance `n_articles`

Le contexte initial mentionnait 672 352 articles ; le `manifest.json` indique 672 009. Écart de 343 articles probablement dû au filtrage `n_articles_empty_text = 162` (selon `build_report.json`) + dédup. À traiter comme un détail factuel, pas comme un bug.
