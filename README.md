# Beaume

**Assistant juridique 100 % local pour avocats français, spécialisé droit social (v1).**

Beaume répond aux questions de droit social — licenciement économique d'abord — en citant le Code du travail, sans envoyer la moindre donnée client à un serveur tiers. Pensé pour les avocats solo et les petits cabinets qui ne peuvent pas faire transiter des dossiers sur ChatGPT, Mistral hébergé, ou un LLM SaaS.

[![License](https://img.shields.io/badge/license-BSL_1.1-orange?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![macOS](https://img.shields.io/badge/macOS-Apple_Silicon-black?style=flat-square&logo=apple)](https://apple.com)
[![Status](https://img.shields.io/badge/status-beta_pilote-yellow?style=flat-square)]()

---

## Aperçu

![HUD Beaume — réponse droit social](assets/lucie-hud-1.png)
![HUD Beaume — citation Légifrance vérifiée](assets/lucie-hud-2.png)
![HUD Beaume — verdict structuré](assets/lucie-hud-3.png)

---

## Statut actuel (mai 2026)

Mesures honnêtes, pas de marketing.

| Métrique | Valeur | Mesuré le |
|----------|--------|-----------|
| Fiabilité batterie 16 questions multi-angles (licenciement éco) | **62,5 %** | 2026-05-12, post-Sprint 6 P2a |
| Fiabilité batterie 50 questions cœur licenciement éco | en recalibrage | Sprint 7 — bench v2 |
| Architecture « 3 cerveaux » | en cours d'implémentation | — |
| KB Légifrance compactée | 4,6 Go (SQLite indexé) | locale uniquement |
| Tests | 23 fichiers `test_*.py` | passe sur CI locale |
| Stack runtime | Gemma 4 e4b via Ollama, PyObjC HUD macOS, SQLite FTS5 | — |

**Beaume n'est pas production-ready.** Le pilote avocat (semaine 12-18 mai 2026) sert exactement à mesurer cet écart.

---

## Pourquoi 100 % local

Un avocat ne peut pas faire transiter un dossier client par un LLM cloud sans entrer en conflit avec :

- **Le secret professionnel** (art. 226-13 du Code pénal, art. 66-5 de la loi de 1971)
- **Le RGPD** — minimisation, finalité, transferts hors UE pour les modèles US
- **L'audit interne** des cabinets et des compagnies d'assurance professionnelle
- **Le fonctionnement offline** (audience, train, déplacement client)

Beaume tourne entièrement sur le Mac de l'avocat. Aucun appel sortant. Aucune télémétrie. La KB Légifrance est livrée avec l'application.

---

## Comment ça marche (high level)

```
                     ┌─────────────────┐
                     │   Avocat         │
                     │ (HUD natif macOS)│
                     └────────┬────────┘
                              │
                ┌─────────────▼─────────────┐
                │  Routeur d'intention      │
                │  (catégorise la requête)  │
                └─────────────┬─────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   ┌────▼─────┐          ┌────▼─────┐          ┌────▼─────┐
   │ Cerveau  │          │ Cerveau  │          │ Cerveau  │
   │ Humain   │          │ Oiseaux  │          │ Pieuvre  │
   │ (LLM)    │          │ (déter.) │          │ (multi-  │
   │          │          │          │          │  agents) │
   └────┬─────┘          └────┬─────┘          └────┬─────┘
        └─────────────────────┼─────────────────────┘
                              │
                ┌─────────────▼─────────────┐
                │  Vérificateur déterministe│
                │  (citation Légifrance     │
                │   vérifiée, truth rule)   │
                └─────────────┬─────────────┘
                              │
                     ┌────────▼────────┐
                     │  Réponse + badge │
                     │  verifier_score  │
                     └─────────────────┘
```

Les trois cerveaux sont complémentaires :

- **Cerveau Humain** — un LLM (Gemma 4) qui formule la réponse en langage naturel
- **Cerveau Oiseaux** — un module déterministe qui filtre les bornes numériques d'articles, les pluriels, les ambiguïtés de routage
- **Cerveau Pieuvre** — orchestration multi-agents pour les requêtes composites (en cours)

En aval, le **Vérificateur** rejette toute réponse qui cite un article que la KB Légifrance ne contient pas, ou dont le numéro est incohérent. C'est la « truth rule » du projet : **on préfère refuser de répondre que halluciner une citation**.

---

## Installation

**Prérequis** : macOS Apple Silicon (M1/M2/M3/M4), Python 3.11+, [Ollama](https://ollama.com).

```bash
brew install ollama
ollama pull gemma2:9b
git clone https://github.com/mathieuballotma-sketch/lucie.git beaume
cd beaume
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python3 main_hud.py
```

Un build `.dmg` signé Developer ID est en cours de préparation (Sprint packaging). En attendant, la voie ligne de commande est la seule officielle.

> Note historique : l'URL du dépôt est `mathieuballotma-sketch/lucie` (le produit s'appelait Lucie avant le pivot droit social du 2 mai 2026). Le rebrand côté code est complet ; seul le slug GitHub reste pour préserver l'historique des commits.

---

## Roadmap publique

Ce qui est annoncé, livré ou en cours :

| Étape | Contenu | Cible |
|-------|---------|-------|
| Sprint 6 P2a | Retriever débridé + Vérificateur normalisé | livré 2026-05-12 |
| **Sprint 7** | Lecture dossier client PDF/docx (extraction + analyse) | 2026-05 |
| **Sprint 8** | Cerveau Déterministe — logique math des lois (calcul d'indemnités, délais, plafonds) | 2026-06 |
| **Sprint 9-10** | Architecture 3 cerveaux complète (Pieuvre opérationnel) | 2026-07 |
| Alpha | Test alpha élargi avocats français | Q3 2026 |
| Multi-pays | Sélection langue/droit au premier lancement, KB Belgique + Suisse | Q1 2027 |

D'autres modules sont en réserve et ne sont pas listés ici — c'est volontaire.

---

## Statut du projet

- **Solo bootstrap**, financé sur fonds propres (zéro VC, zéro pré-vente)
- Mathieu Bellot, 18 ans, candidature **YC Summer 2026** déposée
- Pas de team, pas de communication payante, pas de blog post auto-promo
- Code publié sous **Business Source License 1.1** (change date 2030-04-17 → Apache 2.0) : lisible et étudiable publiquement, pas réutilisable en production commerciale sans licence

Pour les avocats partenaires intéressés par le pilote : [mathieu.ballotma@gmail.com](mailto:mathieu.ballotma@gmail.com).

---

## Liens

- Site : [lucie-site.vercel.app](https://lucie-site.vercel.app) (site produit, sera renommé)
- Contact : [mathieu.ballotma@gmail.com](mailto:mathieu.ballotma@gmail.com)
- Changelog : [CHANGELOG.md](CHANGELOG.md)
- Issues connues : [KNOWN_ISSUES.md](KNOWN_ISSUES.md)
- Architecture interne : [docs/architecture.md](docs/architecture.md)
- Contribuer (limité, voir CONTRIBUTING) : [CONTRIBUTING.md](CONTRIBUTING.md)
