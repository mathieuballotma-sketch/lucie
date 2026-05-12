# Batterie 50 questions cœur licenciement économique — post Sprint 6 P2a

**Date** : 2026-05-12
**Statut** : **EN RECALIBRAGE** — clean run en cours, ce fichier sera mis à jour quand la mesure stabilisée sera livrée.

---

## Pourquoi pas de chiffre définitif ?

La batterie 50q (`bench/swiss_watch_50.json`) couvre l'ensemble de l'arborescence licenciement économique — pas seulement les 16 angles testés dans la batterie courte. Avant Sprint 6 P2a :

- Le Vérificateur double-comptait les citations dupliquées (`[L1233-3]` × 6 = score 1.00 artificiel).
- Le retriever appliquait une stop-list trop agressive sur les termes courts (`L.`, `CDI`, `loi`) qui rejetait des chunks valides.

Sprint 6 P2a corrige les deux causes ([commits `8dbfd95` + `a1c36c4`](../../docs/sprints/2026-05-12_sprint_6_p2a_retriever_verificateur.md)). Mais le calibrage des seuils sur les 50 questions complètes n'est pas encore stabilisé : un agent dédié exécute la batterie clean, et le résultat final sera publié ici dès qu'il sort.

---

## Ce que l'on sait déjà (résultats partiels)

Sur les 10 premières questions de catégorie `lic_eco` exécutées avec les flags P2a :
- Score moyen `verifier_score` : ~0.78
- Citations validées (dédupliquées canoniquement) : ~3 par réponse
- Refus déterministes (zéro LLM call) : ~15 % des questions hors périmètre

Ces chiffres seront **remplacés** par le run clean — ne pas les citer comme mesure de fiabilité tant que ce fichier reste à l'état "en recalibrage".

---

## Méthode prévue (pour reproduction)

```bash
BEAUME_RETRIEVER_DEBRIDE=1 BEAUME_VERIFICATEUR_NORMALISE=1 \
  python3 bench/run_legal_traps.py \
    --prompts bench/swiss_watch_50.json \
    --json bench/results/2026-05-12_battery_50q_post_p2a.json
```

---

## Truth rule

Plutôt que de publier un chiffre approximatif (par exemple "19/50 = 38 %" qui circule en interne), ce fichier reste **explicitement en attente**. La transparence radicale impose d'attendre la mesure stabilisée. Mieux vaut "en cours" que faux.
