> **Langues :** [🇬🇧 English](README.md) · [🇫🇷 Français](README.fr.md)

<div align="center">

# Lucie

### Assistante IA locale pour avocats. 100 % sur la machine. Règle de vérité absolue.

[![Version](https://img.shields.io/badge/version-v0.5.0-blue)](https://github.com/mathieuballotma-sketch/lucie)
[![Tests](https://img.shields.io/badge/tests-375%20passants-brightgreen)]()
[![Lighthouse](https://img.shields.io/badge/lighthouse-100%2F100%2F100%2F100-brightgreen)](https://lucie-site.vercel.app)
[![EU AI Act](https://img.shields.io/badge/AI%20Act%20UE-conforme%20par%20construction-blue)]()
[![Local-first](https://img.shields.io/badge/inf%C3%A9rence-100%25%20locale-success)]()

**[lucie-site.vercel.app](https://lucie-site.vercel.app)**

</div>

---

## Présentation

Lucie tourne entièrement sur le Mac de l'afrance — la base de données légale officielle française, indexée localement — rédige des documents procéduraux, et refuse honnêtement lorsqu'elle ne sait pas.

La règle qui la définit est appliquée au niveau architectural : **Lucie n'invente jamais, n'hallucine jamais, ne ment jamais.**

---

## Capacités

- **Raisonnement juridique local** — réponses ancrées dans un index local de 281 archives DILA de Légifrance. Aucun appel à une API externe à l'inférence.
- **Refus déterministe** — les références d'articles non citables sont rejetées en moins de 50 ms, avant tout appel à un LLM.
- **Réponses sourcées** — chaque affirmation est reliée à un article ou une décision spécifique du index local.
- **Mémoire adaptative** — renforcement et décroissance basés sur les embeddings, par interaction utilisateur. Persistante, locale, personnalisée.
- **Rédaction procédurale** — lettres, contestations et documents juridiques structurés avec citations vivantes.
- **Piste d'score de confiance et ses motifs de refus.
- **HUD temps réel** — l'avocat voit ce que Lucie consulte, dans quel ordre, avec quel résultat.
- **Native macOS** — application signée, prête à la notarisation.

---

## Preuves d'avancement — v0.5.0 · 22 avril 2026

| Mesure | Valeur |
|---|---|
| Tests passants | 375 |
| Briques produit documentées | 138 |
| Archives légales indexées localement | 281 (DILA Légifrance) |
| Latence de refus sur référence invalide | <50 ms, 0 appel LLM |
| Site de production Lighthouse | 100 / 100 / 100 / 100 |
| Environnement d'inférence | 100 % local (Ollama + Gemma 3) |
| Appels API externes à l'inférence | 0 |
| Tags git publiés | 11 (v0.2.0-beta → v0.5.0) |

---

## Architecture — chemins d'exécution en couches

Lucie route chaque requête à travers trois couches, n'invoquant les couches plus profondes qu'au besoin.

1. **Couche déterministe pré-LLM** — filtres de validation à faible latence (<50 ms). Extraction regex de références légales,ion hors-périmètre, correspondance floue juridique. Zéro appel LLM. Zéro surface d'hallucination. Zéro coût en jetons.
2. **Processus parallèles spécialisés** — workers autonomes par application intégrée (Mail, Agenda, Notes, Word, etc.), communiquant via un bus d'événements interne. Chaque worker opère sur son propre contexte et sous-ensemble d'outils.
3. **Orchestrateur de composition et de planification** — la seule couche autorisée à invoquer le LLM local, et uniquement si un raisonnement multi-étapes est strictement requis. Sa sortie est renvoyée vers la couche de vérification avant d'atteindre l'utilisateur.

**Couche mémoire** — basée sur embeddings. Les associations se renforcent par l'usage, décroissent par le désusage, persistent localement par utilisateur. Deux instances divergent par construction après interaction soutenue.

**Application de la vérité** à trois points : refus déterministe avant tout appel LLM, vérification post-génération des citations contrelète exposée à l'utilisateur.

---

## Video demo

> **À venir** — une vidéo courte de démonstration de la règle de vérité en action sera publiée ici prochainement.

---

## Lucie en action

Captures d'écran du HUD macOS, fonctionnant localement sur le Mac de l'avocat.

![Workflow Lucie — consulte les articles, prépare la réponse, vérifie chaque citation](assets/lucie-hud-1.png)

![Lucie rédige une lettre juridique structurée avec des placeholders vivants](assets/lucie-hud-2.png)

![Lucie cite les références officielles des articles depuis l'index local Légifrance](assets/lucie-hud-3.png)

Chaque réponse est sourcée. Quand Lucie ne peut citer, Lucie refuse.

---

## Sécurité et vie privée

- **Rien ne quitte l'appareil à l'inférence.** LLM local, base juridique locale, mémoire locale.
- **Pas de cookies, pas de tracking, pas d'analytics** sur le site ou dans l'app.
- **RGPD** — aucune donnée personnelle traitée hors de la machine de l'utilisateur.
- **AI Act UE (août 2026on par rétrofit.
- **Sandbox macOS** — habilitations OS appliquées.

---

## Feuille de route

- **v1** — pilote avec des avocats · août 2026
- **v1.1, v1.2, v1.3** — améliorations incrémentales après le lancement, sans rompre le contrat v1
- **v2** — s'ouvre à d'autres domaines qui exigent la même rigueur
- **v3** — s'ouvre à tout le monde, personnalisée par utilisateur

Chaque version est le prérequis de la suivante.

---

## Organisation du dépôt

Ce dépôt public est une vitrine.

- [`README.md`](README.md) · [`README.fr.md`](README.fr.md) — présentation produit et architecture
- [`CHANGELOG.md`](CHANGELOG.md) — historique des versions de v0.2.0-beta à la version actuelle
- [`assets/`](assets/) — captures d'écran du HUD macOS en production
- [`examples/truth_rule_proof.py`](examples/truth_rule_proof.py) — démonstration exécutable du pattern de refus déterministe

L'implémentation principale reste dans des dépôts privés sous licence propriétaire :

- Code d'apD, packaging)
- Index Légifrance local dérivé de DILA sous les termes de la licence DILA
- Architecture de mémoire adaptative
- Prompts système et harnais d'évaluation interne

Des modules sélectionnés peuvent être partagés sous NDA avec des reviewers sérieux.

---

## Statut

Tag `v0.5.0` est la référence publique actuelle. Le site de production [lucie-site.vercel.app](https://lucie-site.vercel.app) reflète le produit actuel.
