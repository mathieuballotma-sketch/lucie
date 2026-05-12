# Lucie F9 — Baseline legal traps (default)

Date : 2026-05-12 21:09:38
Total cas : **10**

**Global** : 4/10 PASS (40.0%) · 6 FAIL · 0 ERROR

## Résumé par catégorie

| Catégorie | n | PASS | FAIL | ERROR |
|---|---:|---:|---:|---:|
| lic_eco | 10 | 4 | 6 | 0 |

## Détail par cas

### SW-LECO-001 — **PASS** (50838 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quelle est la procédure de licenciement économique individuel ? »
- Comportement attendu : Réponse procédurale détaillée avec citation L.1233-3 ou L.1233-4, score vérificateur ≥ 70%.
- Réponse (preview 200c) : « Lorsqu'un employeur procède à un licenciement individuel pour motif économique, plusieurs étapes procédurales sont encadrées.  Concernant le choix du salarié concerné, l'employeur doit prendre en comp »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-LECO-002 — **PASS** (51771 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Comment fonctionne le licenciement économique collectif de moins de 10 salariés sur 30 jours ? »
- Comportement attendu : Distinction <10 vs ≥10 expliquée, citation articles compétents.
- Réponse (preview 200c) : « L'article L1233-28 ne prévoit pas de disposition spécifique concernant un licenciement collectif inférieur à dix salariés sur une période de trente jours. Il dispose, en revanche, que l'employeur qui  »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-LECO-003 — **FAIL** (85416 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quelles sont les conditions du motif économique selon l'article L.1233-3 ? »
- Comportement attendu : Liste des 4 motifs (difficultés économiques, mutations technologiques, réorganisation, cessation), citation L.1233-3 obligatoire.
- Réponse (preview 200c) : « Constitue un licenciement pour motif économique le licenciement effectué par un employeur pour un ou plusieurs motifs qui ne sont pas inhérents à la personne du salarié [L1233-3]. Ces motifs doivent r »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=85415.9599999839`

### SW-LECO-004 — **FAIL** (61722 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quels sont les critères d'ordre des licenciements économiques ? »
- Comportement attendu : Charges familiales, ancienneté, situation sociale, qualités professionnelles — citation L.1233-5.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `verifier_score gte 0.7 → actual=0.0`
  - `citations_total gte 1 → actual=0`
  - `_wall_clock_ms lte 60000 → actual=61722.49695798382`

### SW-LECO-005 — **FAIL** (74897 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quelle est l'obligation de reclassement de l'employeur en cas de licenciement économique ? »
- Comportement attendu : Périmètre groupe France, postes équivalents/inférieurs, citation L.1233-4.
- Réponse (preview 200c) : « L'obligation de reclassement est abordée dans les sources principalement sous l'angle des modalités de mise en œuvre du congé de reclassement. Lorsque l'employeur établit un plan de sauvegarde de l'em »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=74897.35220800503`

### SW-LECO-006 — **FAIL** (54578 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quel est le seuil de déclenchement d'un PSE (plan de sauvegarde de l'emploi) ? »
- Comportement attendu : ≥10 salariés sur 30 jours dans entreprise ≥50 salariés. Citation L.1233-61 ou L.1233-25.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `verifier_score gte 0.7 → actual=0.0`
  - `citations_total gte 1 → actual=0`

### SW-LECO-007 — **FAIL** (74403 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quelles mentions sont obligatoires dans une lettre de licenciement économique ? »
- Comportement attendu : Motif éco précis, priorité de réembauche, CSP/contrat de sécurisation pro. Citation L.1233-16.
- Réponse (preview 200c) : « La lettre de licenciement économique doit impérativement comporter l'énoncé des motifs économiques invoqués par l'employeur [L1233-9]. En effet, l'énoncé précis et circonstancié de ce motif économique »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=74402.56729201064`

### SW-LECO-008 — **PASS** (47296 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Comment se calcule l'indemnité de licenciement économique légale ? »
- Comportement attendu : 1/4 mois par année <10 ans + 1/3 mois par année >10 ans. Citation L.1234-9 ou R.1234-2.
- Réponse (preview 200c) : « Le salaire pris en compte pour le calcul de l'indemnité de licenciement doit être déterminé selon la formule la plus avantageuse pour le salarié [R1234-4]. Cette base de calcul est soit la moyenne men »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-LECO-009 — **PASS** (52205 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quels sont les délais pour contester un licenciement économique aux prud'hommes ? »
- Comportement attendu : 12 mois à compter de la notification (L.1235-7 ou L.1471-1).
- Réponse (preview 200c) : « Toute contestation relative à un licenciement pour motif économique se prescrit par douze mois à compter de la dernière réunion du comité social et économique [L1235-7]. Ce délai s'applique également  »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-LECO-010 — **FAIL** (72118 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Qu'est-ce que le contrat de sécurisation professionnelle (CSP) et qui peut en bénéficier ? »
- Comportement attendu : Salariés visés par licenciement éco dans entreprise <1000 salariés. Citation L.1233-65 ou suivants.
- Réponse (preview 200c) : « L'adhésion au contrat de sécurisation professionnelle (CSP) entraîne la rupture du contrat de travail [L1233-67]. Les modalités de mise en œuvre de ce contrat sont définies par un accord qui doit être »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=72117.66029201681`
