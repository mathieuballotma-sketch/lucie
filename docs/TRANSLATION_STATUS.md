# Translation Status — Beaume public docs

Convention: `XXX.md` is the English primary; `XXX.fr.md` is the
French mirror. Each file pair below must stay synchronized: a change
to one side requires a matching change to the other within the same
PR.

Convention : `XXX.md` = anglais (primaire) ; `XXX.fr.md` = miroir
français. Toute modification d'un côté impose la modification
équivalente de l'autre dans la même PR.

## Tracked pairs / Paires suivies

| EN file | FR file | Last sync | Owner | Notes |
|---|---|---|---|---|
| `README.md` | `README.fr.md` | 2026-05-13 | MB | banner + badges shared |
| `PRINCIPLES.md` | `PRINCIPLES.fr.md` | 2026-05-13 | MB | — |
| `SECURITY.md` | `SECURITY.fr.md` | 2026-05-13 | MB | title was EN / body FR pre-2026-05-13 |
| `CONTRIBUTING.md` | `CONTRIBUTING.fr.md` | 2026-05-13 | MB | — |
| `CHANGELOG.md` | `CHANGELOG.fr.md` | 2026-05-13 | MB | full historical entries translated EN |
| `KNOWN_ISSUES.md` | `KNOWN_ISSUES.fr.md` | 2026-05-13 | MB | — |
| `docs/architecture.md` | `docs/architecture.fr.md` | 2026-05-13 | MB | already bilingual pre-2026-05-13 |
| `docs/EVIDENCE.md` | `docs/EVIDENCE.fr.md` | 2026-05-13 | MB | fixed broken `ARCHITECTURE.md` link |
| `docs/REPRODUCE.md` | `docs/REPRODUCE.fr.md` | 2026-05-13 | MB | — |
| `docs/THREAT_MODEL.md` | `docs/THREAT_MODEL.fr.md` | 2026-05-13 | MB | — |
| `docs/sprints/SUMMARY.md` | `docs/sprints/SUMMARY.fr.md` | 2026-05-13 | MB | public summary; detail stays in `STASH_PRIVATE.md` |
| `bench/CHANGELOG.md` | `bench/CHANGELOG.fr.md` | 2026-05-13 | MB | scope = battery recalibrations |
| `bench/results/README.md` | `bench/results/README.fr.md` | 2026-05-13 | MB | — |
| `tests/README.md` | `tests/README.fr.md` | 2026-05-13 | MB | dev-facing; mislabeled EN in initial audit |

## Exempt files / Fichiers exemptés

- `LICENSE` — BSL 1.1, legal English only.
- `docs/CONTRIBUTING_INTERNAL.md` — internal, not in the public docs scope.
- `STASH_PRIVATE.md` — gitignored.
- `prompts_private/` — gitignored.

## Update protocol / Protocole de mise à jour

1. Edit both files (`XXX.md` and `XXX.fr.md`) in the same commit.
   Modifier les deux fichiers dans le même commit.
2. Bump the `Last sync` cell of the affected row in this file.
   Mettre à jour la cellule `Last sync` de la ligne concernée.
3. Run the post-checks (drift `<30%`, no broken link, "Beaume" in
   both, no `Ballotma` outside email/handle).
   Lancer les vérifications post (écart `<30%`, aucun lien cassé,
   « Beaume » présent dans les deux, aucun `Ballotma` hors
   email/handle).
