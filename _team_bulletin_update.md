# Bulletin d'équipe — Mise à jour spec Lucie v1
**Date :** 2026-04-10  
**Fichier mis à jour :** `19_Lucie_v1_Aout_2026_Specification.md` (v2.4)  
**Auteur :** Mathieu Bellot

---

## Ce qui a changé (toutes versions du 10 avril 2026)

La spec v1 (architecture orchestrale complexe) a été entièrement réécrite en cinq rounds de simplification et de précision le même jour.

---

## Les 5 non-features assumées

| Non-feature | Justification courte |
|---|---|
| Pas d'orchestration multi-agents distribuée | Dev solo, 4 mois, impossible à débugger |
| Pas de multi-LLM thématiques simultanés | Budget RAM incompatible Mac 16 Go client |
| Pas d'audit LLM-sur-LLM | Limite structurelle — ne détecte pas les hallucinations subtiles |
| Pas de recherche web ouverte en runtime | Whitelist stricte + consentement explicite — pas d'accès internet libre |
| Pas de bulletin inter-agents | Process séquentiel, journal.md suffit |

---

## L'architecture en un schéma

```
Utilisateur → HUD macOS
     │ (Mode 1 : session, zéro réseau)
     ▼
Routeur déterministe (code)
     │
     ├──► Lecteur (E2B) ──── extrait documents
     ├──► Retriever (E2B) ── lookup base locale → si no_source_found : propose Mode 3
     ├──► Rédacteur (E4B) ── rédige depuis sources
     └──► Vérificateur (E2B) ─ vérifie vs sources déterministes
     │
     ▼
Journal dossier (journal.md)
     │
     ▼
Utilisateur

Mode 2 (nuit, inactivité) :
     launchd → Navigateur headless WebKit → whitelist → base curatée mise à jour

Mode 3 (session, consentement) :
     Routeur → [consentement utilisateur] → Navigateur headless WebKit → whitelist → source ajoutée
```

---

## Les vérificateurs externes branchés

| Domaine | Vérificateur | Mode |
|---|---|---|
| Textes de loi | Légifrance API + base curatée | Local first, online Mode 2/3 |
| Jurisprudence | JuriCA + base curatée | Local first, online Mode 2/3 |
| Comptabilité | PCG + CRC + BOFiP (index local) | Index local |
| Code sécurité | bandit + semgrep | subprocess local |
| Code exécution | Sandbox Python isolée | subprocess local |

---

## Comportement d'aveu honnête (nouvelle caractéristique produit)

Quand Lucie ne peut pas vérifier une source (hors ligne + source manquante) :
- Elle refuse de rédiger à l'aveugle
- Elle propose trois options : noter le manque, continuer avec trou explicite, fournir la source manuellement
- Phrase produit : "Lucie ne hallucine pas pour faire plaisir. Elle préfère admettre un manque."

---

## Whitelist de domaines de confiance (safety rail anti-injection)

Domaines autorisés pour le navigateur headless, codés en dur :
- legifrance.gouv.fr, courdecassation.fr, conseil-etat.fr, justice.gouv.fr
- bofip.impots.gouv.fr, impots.gouv.fr, urssaf.fr, anc.gouv.fr, insee.fr
- (sous abonnement, v2) : doctrine.fr, lexbase.fr, lexis360.fr, dalloz.fr

---

## Décisions en attente

| Décision | Avant quoi |
|---|---|
| Playwright WebKit vs pyobjc + WKWebView | Jalon 2 |
| Option A vs B chargement modèles (bench) | Jalon 1 |
| Gemma 4 E2B/E4B dispo Ollama ou fallback Qwen3:8B | Jalon 1 |
| 8-10 intersections prioritaires (avec pilotes) | Jalon 2 |
| Sources transverses : index vs symlinks | Jalon 2 |
| Classification Retriever : code vs E2B | Jalon 2 |
| Schéma journal.md figé | Jalon 2 |
| Format JSON entrées base curatée | Jalon 2 |
| Légifrance PISTE API : compte utilisateur ou clé partagée | Jalon 2 |
| Seuil inactivité Mode 2 (minutes + détection wifi) | Jalon 2 |
| UX dialogue consentement Mode 3 (notification vs HUD) | Jalon 3 |
| Seuils taux out_of_scope (alerte / blocage) | Jalon 3 |
| Format tests de régression prompts | Jalon 3 |

---

## Prochaines étapes concrètes

1. **Immédiat :** confirmer disponibilité Gemma 4 E2B + E4B sur Ollama  
2. **Immédiat :** vérifier disponibilité gratuite sources JuriCA/Légifrance pour PoC prudhommes  
3. **Semaine suivante :** bench hardware (latences, RAM, décision Option A/B)  
4. **Fin avril :** schéma journal.md + format JSON + choix 8-10 intersections avec pilotes  
5. **Mai :** Jalon 1 — Routeur + HUD + bench + preuve de concept Playwright vs WKWebView  

---

_Bulletin mis à jour le 2026-04-10 — document de référence : `19_Lucie_v1_Aout_2026_Specification.md` v2.4_
