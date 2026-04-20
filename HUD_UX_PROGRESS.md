# Carnet de reprise — HUD UX polish v0.2.1

**Hash de reprise** : `hud-ux-polish-v0.2.1-2026-04-20`
**Date début** : 2026-04-20
**Branche** : `feat/hud-ux-proposition-buttons-save`
**Plan de référence** : `/Users/mathieu/.claude/plans/ton-r-le-ing-nieur-keen-curry.md`

---

## État global

🔄 **En cours** — Phase 9 (commits atomiques + merge)

Objectif : 3 améliorations UX sur le HUD natif Lucie avant pilotes août.

1. Proposer avant créer un document (ProposalCard + 2 boutons)
2. Boutons Oui/Non génériques sur questions fermées (suggested_replies)
3. DraggableFileCard refondue (shadow, double-clic NSSavePanel, icône + métadonnées)

## Phases

- ✅ Phase 0 — Exploration + plan validé
- ✅ Phase 1 — Setup (carnet + branche)
- ✅ Phase 2 — Lecture approfondie fichiers clés
- ✅ Phase 3 — Chantier 1 : extension pipeline (PipelineResponse, routing décision, propose/dispose)
- ✅ Phase 4 — Chantier 2 : document_writer.py (markdown → DOCX)
- ✅ Phase 5 — Chantier 3a : ProposalCardView
- ✅ Phase 6 — Chantier 3b : renderer suggested_replies générique
- ✅ Phase 7 — Chantier 3c : refonte DraggableFileCard
- ✅ Phase 8 — Tests unitaires (166 passed, 0 failed) ; tests manuels HUD en attente
- 🔄 Phase 9 — Commits atomiques + merge + tag v0.2.1
- ⏳ Phase 10 — Rapport final

## Décisions (append-only)

- **2026-04-20** Détection « proposer » via marqueur `produces_document` dans PipelineResponse (pas heuristique frontend). Couplage propre pipeline→HUD.
- **2026-04-20** Format fichier DOCX via python-docx, écrit dans `./Lucid_Docs/`. Pas de markdown en parallèle.
- **2026-04-20** NSSavePanel déclenché par double-clic sur la carte. Drag simple préservé (zéro conflit).
- **2026-04-20** DialogueManager reste non branché (dette acceptée, v1.1).
- **2026-04-20** Pas de tests automatisés HUD (PyObjC difficile à mocker) — tests manuels + screenshots font foi.
- **2026-04-20** Décision flow sans DialogueManager → marqueur query-préfixé `__decision__:<value>|original=<query>`, 1 tour, stateless.
- **2026-04-20** Test `test_explicit_order_triggers_action_mode` remplacé par paire propose-then-execute (changement volontaire du contrat documenté dans le plan).
- **2026-04-20** Priorité affichage post-stream dans HUD : (1) document_path → DraggableFileCard, (2) produces_document → ProposalCard, (3) suggested_replies → ProposalCard générique, (4) rien. Plus jamais de `.md` auto.

## Blocages

_Aucun — tests verts, prêt pour commits._

## Instructions pour reprendre

Si la session s'interrompt :
1. `cd /Users/mathieu/Desktop/mon-agence-ia/.claude/worktrees/gifted-euler-4a3d0e`
2. `git status` + `git log --oneline -5` pour voir où ça s'est arrêté
3. Relire ce carnet : dernière phase ✅ → continuer la phase 🔄
4. Plan de référence : `/Users/mathieu/.claude/plans/ton-r-le-ing-nieur-keen-curry.md`
5. Si tests rouges : NE PAS merger, fix d'abord
