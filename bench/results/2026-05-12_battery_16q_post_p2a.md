# Batterie 16 questions multi-angles — post Sprint 6 P2a

**Date** : 2026-05-12
**Contexte** : post-merge Sprint 6 P2a sur `main` (commit `315719b`)
**Flags actifs** : `BEAUME_RETRIEVER_DEBRIDE=1`, `BEAUME_VERIFICATEUR_NORMALISE=1`
**Modèle** : Gemma 4 e4b (via Ollama, `keep_alive=24h`)

---

## Résultat global

| Métrique | Valeur |
|----------|--------|
| Questions exécutées | 16 |
| Questions PASS (verifier_score ≥ 0.70) | **10** |
| Questions FAIL | 6 |
| **Fiabilité globale** | **62,5 %** |

---

## Décomposition par angle

La batterie 16q multi-angles teste 4 catégories × 4 questions par catégorie :

| Angle | Description | PASS | Total | Taux |
|-------|-------------|------|-------|------|
| Procédure | délais légaux, motifs licenciement éco, lettre, entretien préalable | 3 | 4 | 75 % |
| Indemnités | indemnité légale, supplémentaire CSP, plafond CDI | 3 | 4 | 75 % |
| Reclassement | obligation, périmètre groupe, refus salarié | 2 | 4 | 50 % |
| Contestation | délais Conseil de prud'hommes, motifs nullité, charge preuve | 2 | 4 | 50 % |

**Lecture** : la procédure et les indemnités (zones les plus codifiées du Code du travail) tiennent à 75 %. Reclassement et contestation, plus dépendants de la jurisprudence et des cas d'espèce, tombent à 50 %. Sprint 7 (lecture dossier client) doit améliorer le reclassement contextualisé.

---

## Méthode

```bash
# Reproductible depuis le repo
git clone https://github.com/mathieuballotma-sketch/lucie.git beaume
cd beaume
make install
BEAUME_RETRIEVER_DEBRIDE=1 BEAUME_VERIFICATEUR_NORMALISE=1 \
  python3 bench/run_legal_traps.py \
    --prompts bench/swiss_watch_50.json \
    --filter SW-LECO \
    --json bench/results/_latest.json
```

Le seuil `verifier_score ≥ 0.70` est calibré dans [`bench/swiss_watch_50.json`](../swiss_watch_50.json) (champ `pass_criteria.verifier_score_min`). Justification : voir [`bench/CHANGELOG.md`](../CHANGELOG.md) — la normalisation des citations Sprint 6 P2a a éliminé un biais qui surévaluait l'ancien seuil de 0.85.

---

## Limites de cette mesure

- **Multi-angles ≠ exhaustif**. 16 questions sont un échantillon ciblé sur 4 axes. La batterie 50q (cœur licenciement économique) donnera une mesure plus représentative — clean run en cours.
- **Gemma 4 e4b spécifique**. Un autre modèle (Llama, Mistral, Qwen) donnerait des chiffres différents. Le pipeline Vérificateur est modèle-agnostique mais le LLM lui-même n'est pas interchangeable sans recalibration.
- **`verifier_score ≥ 0.70` n'est pas "correct"** au sens juridique strict. C'est "≥ 70 % des citations sont dans la KB Légifrance et n'ont pas été inventées par le LLM". Une réponse peut être vérifiée et néanmoins juridiquement inappropriée — c'est précisément pourquoi un avocat reste l'utilisateur final, pas un assistant qui prend des décisions.

---

## Rapport sprint détaillé

Pour le contexte complet (problèmes B-5/B-6, choix de design, métriques avant/après), voir
[`sprint_6_p2a_full_report.md`](sprint_6_p2a_full_report.md).
