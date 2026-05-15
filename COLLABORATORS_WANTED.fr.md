# Beaume cherche des collaborateurs (pas des investisseurs)

*[Read in English](COLLABORATORS_WANTED.md)*

Beaume est un **assistant juridique IA 100% local pour les avocats
français**. Abonnement mensuel, pas de cloud, pas de télémétrie,
pas de facturation au token. Mathieu Bellot développe le projet en
solo, candidat Y Combinator Summer 2026. Cette page est un appel à
**collaborer** — pas à investir.

---

## Comment la collaboration fonctionne (truth rule)

Beaume est bootstrap solo, zéro VC, zéro pré-vente, zéro garantie
de salaire. Pas de rémunération fixe à ce stade. Le tier de
compensation — equity, revenue share, prestation contractée — se
discute au cas par cas, après avoir effectivement travaillé
ensemble sur quelque chose de concret. Si tu veux un salaire en
amont, ce n'est pas le bon moment pour nous.

Le repo est source-available sous
[Business Source License 1.1](LICENSE). L'architecture, les tests
et le pipeline cœur sont publics ; certains composants restent en
réserve compétitive jusqu'à la change date BSL (2030-04-17 → bascule
Apache 2.0).

---

## 🦉 Développeur·euse Swift / macOS natif

**Tu contribuerais à :** HUD natif, signature `.dmg` (Apple
Developer ID), animation bounce du wizard, hooks EventKit /
AppleScript (Sprint 9+ *Pieuvre*, quand activé).

**Profil :** 2-5 ans Swift / SwiftUI / AppKit, expérience packaging
Mac, sens du polish UX Apple.

**Pourquoi c'est intéressant :** code propre dans un produit qui
défend la vie privée par architecture — Beaume ne sera jamais un
SaaS.

---

## ⚖️ Avocat·e droit social français

**Tu contribuerais à :** validation de la KB juridique, design de
la batterie de tests, retours qualité sur les réponses réelles,
construction de scénarios edge-case crédibles.

**Profil :** 2-10 ans pratique du droit du travail, intérêt pour
l'outillage IA, à l'aise pour raisonner sur les cas limites
(procédure licenciement éco, calcul d'indemnités, jurisprudence
Chambre sociale).

**Pourquoi c'est intéressant :** façonner l'outil de demain pour ta
profession, avant qu'un acteur cloud l'impose depuis l'extérieur.

---

## ⚖️ Avocat·e secteur réglementé non-social

**Tu contribuerais à :** étendre les corpus Beaume Engine (pharma
ANSM, fiscal, IFRS, droit pénal, propriété intellectuelle…). Le
Sprint G-1 (mai 2026) a prouvé qu'ajouter un nouveau corpus prend
des heures, pas des semaines, une fois le pattern manifest en place.

**Profil :** 3-10 ans pratique d'un secteur réglementé précis,
intérêt pour structurer un corpus manifest-driven (articles +
patterns de citation + refus de scope).

**Pourquoi c'est intéressant :** tu construis le premier corpus de
référence dans ton domaine. Authorship direct, pas de comité.

---

## 🧠 ML engineer (Python, LLM local)

**Tu contribuerais à :** *BeaumeLM* distillé (Sprint 11, planifié),
runtime MLX / candle, fine-tuning LoRA, optimisation de Gemma 4 e4b
spécifiquement pour Apple Silicon (M2+).

**Profil :** stack Hugging Face, MLX / Metal, quantization,
distillation — capable de raisonner cold-start vs RAM.

**Pourquoi c'est intéressant :** le projet optimise pour Mac
M-series, pas pour cluster cloud. Tu livres pour un laptop, pas
pour une flotte.

---

## 🎨 Designer produit / motion designer

**Tu contribuerais à :** wizard 9 cartes, animations HUD, cohérence
d'identité visuelle, vibrancy Sequoia / intégration SF Symbols.

**Profil :** Figma + SwiftUI fluents + sens du motion design Apple.

**Pourquoi c'est intéressant :** la perception « montre suisse » du
produit dépend entièrement du polish UX. Le motion fait la moitié
de la confiance.

---

## 🔒 Ingénieur·e privacy / réseau

**Tu contribuerais à :** Sprint K-8 (sync KB privacy-preserving
Master DB + diffusion P2P), OHTTP, libp2p, preuves de Merkle.

**Profil :** expérience proxys anonymisants, cryptographie
appliquée, protocoles P2P.

**Pourquoi c'est intéressant :** levier structurel pour différencier
Beaume des concurrents cloud SaaS — la vie privée est le moat, pas
une feature.

---

## 📣 Growth / communauté avocats (priorité plus basse pour l'instant)

**Tu contribuerais à :** amener Beaume devant les premiers avocats
alpha (2 contactés à ce jour, 9 sur la waiting list). Surtout utile
une fois la phase pilote (12-18 mai 2026) terminée.

**Profil :** connaisseur·euse du monde juridique français, capable
de présenter sans bullshit, sans marketing-speak.

**Pourquoi c'est intéressant :** on cherche des avocats prêts à
expérimenter, pas de la couverture presse.

---

## Pas le bon profil mais tu veux quand même aider ?

Ouvre une issue GitHub en décrivant ce que tu apporterais, ou envoie
un email — mentionne le profil le plus proche (ou invente-en un).

---

## Comment me contacter

- Email : **mathieu.ballotma@gmail.com**
- GitHub : ouvre une issue sur ce repo, ou DM via profil

**Pas de pitch.** Dis-nous la plus petite chose concrète que tu
voudrais contribuer ce mois-ci, et on part de là. Un paragraphe vaut
mieux qu'un deck.

---

## Truth rule appliquée à cette page

Beaume est **bootstrap solo, sans garantie de salaire** à ce stade.
Les profils marqués « Sprint 9+ », « Sprint 11 » ou « planifié »
sont du travail futur, pas des livrables présents. On ne vend pas
d'equity hypothétique comme un salaire garanti, et on ne promet pas
un scope qui n'a pas encore été livré.

Si quoi que ce soit sur cette page sonne comme du oversell, ouvre
une issue — on corrigera.
