# Lucie F9 — Baseline legal traps (default)

Date : 2026-05-12 20:57:03
Total cas : **50**

**Global** : 33/50 PASS (66.0%) · 17 FAIL · 0 ERROR

## Résumé par catégorie

| Catégorie | n | PASS | FAIL | ERROR |
|---|---:|---:|---:|---:|
| article_inexistant | 5 | 5 | 0 | 0 |
| conges_rtt | 5 | 2 | 3 | 0 |
| dem_rupture_conv | 5 | 3 | 2 | 0 |
| hors_scope | 5 | 5 | 0 | 0 |
| lic_eco | 10 | 1 | 9 | 0 |
| lic_perso | 10 | 9 | 1 | 0 |
| petites_taches | 5 | 5 | 0 | 0 |
| pieges | 5 | 3 | 2 | 0 |

## Détail par cas

### SW-LECO-001 — **FAIL** (73515 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quelle est la procédure de licenciement économique individuel ? »
- Comportement attendu : Réponse procédurale détaillée avec citation L.1233-3 ou L.1233-4, score vérificateur ≥ 70%.
- Réponse (preview 200c) : « Lorsqu'un employeur procède à un licenciement individuel pour motif économique, il doit prendre en compte, dans le choix du salarié concerné, les critères prévus à l'article L. 1233-5 du Code du trava »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=73514.96370800305`

### SW-LECO-002 — **FAIL** (69129 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Comment fonctionne le licenciement économique collectif de moins de 10 salariés sur 30 jours ? »
- Comportement attendu : Distinction <10 vs ≥10 expliquée, citation articles compétents.
- Réponse (preview 200c) : « L'employeur qui envisage de procéder à un licenciement collectif pour motif économique d'au moins dix salariés dans une même période de trente jours est tenu de réunir et de consulter le comité social »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=69128.53958300548`

### SW-LECO-003 — **FAIL** (71284 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quelles sont les conditions du motif économique selon l'article L.1233-3 ? »
- Comportement attendu : Liste des 4 motifs (difficultés économiques, mutations technologiques, réorganisation, cessation), citation L.1233-3 obligatoire.
- Réponse (preview 200c) : « Constitue un motif économique le licenciement prononcé par un employeur pour un ou plusieurs motifs qui ne sont pas inhérents à la personne du salarié [L1233-3]. Ces motifs résultent soit d'une suppre »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=71284.10874999827`

### SW-LECO-004 — **FAIL** (90820 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quels sont les critères d'ordre des licenciements économiques ? »
- Comportement attendu : Charges familiales, ancienneté, situation sociale, qualités professionnelles — citation L.1233-5.
- Réponse (preview 200c) : « Les sources fournies détaillent les obligations d'information de l'employeur envers les représentants du personnel concernant le projet de licenciement collectif. L'employeur doit adresser ces renseig »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=90819.880791998`

### SW-LECO-005 — **FAIL** (89294 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quelle est l'obligation de reclassement de l'employeur en cas de licenciement économique ? »
- Comportement attendu : Périmètre groupe France, postes équivalents/inférieurs, citation L.1233-4.
- Réponse (preview 200c) : « L'obligation de l'employeur en matière de reclassement est encadrée par des procédures d'information et de consultation concernant le congé de reclassement.  Lorsque l'employeur établit un plan de sau »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=89294.06470799586`

### SW-LECO-006 — **FAIL** (65167 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quel est le seuil de déclenchement d'un PSE (plan de sauvegarde de l'emploi) ? »
- Comportement attendu : ≥10 salariés sur 30 jours dans entreprise ≥50 salariés. Citation L.1233-61 ou L.1233-25.
- Réponse (preview 200c) : « Le déclenchement d'un Plan de Sauvegarde de l'Emploi (PSE) est un sujet abordé par les sources fournies sous l'angle de ses modalités d'élaboration et de mise en œuvre.  En l'absence de seuil précis d »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=65167.28562499338`

### SW-LECO-007 — **FAIL** (66272 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quelles mentions sont obligatoires dans une lettre de licenciement économique ? »
- Comportement attendu : Motif éco précis, priorité de réembauche, CSP/contrat de sécurisation pro. Citation L.1233-16.
- Réponse (preview 200c) : « La lettre de licenciement doit impérativement comporter l'énoncé des motifs économiques invoqués par l'employeur [L1233-9]. En effet, l'énoncé précis et circonstancié de ce motif économique constitue  »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=66271.67250000639`

### SW-LECO-008 — **PASS** (49508 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Comment se calcule l'indemnité de licenciement économique légale ? »
- Comportement attendu : 1/4 mois par année <10 ans + 1/3 mois par année >10 ans. Citation L.1234-9 ou R.1234-2.
- Réponse (preview 200c) : « Le salaire servant de base au calcul de l'indemnité de licenciement doit être déterminé selon la formule la plus avantageuse pour le salarié [R1234-4]. Cette base de calcul est soit la moyenne mensuel »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-LECO-009 — **FAIL** (60683 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quels sont les délais pour contester un licenciement économique aux prud'hommes ? »
- Comportement attendu : 12 mois à compter de la notification (L.1235-7 ou L.1471-1).
- Réponse (preview 200c) : « Toute contestation relative à un licenciement pour motif économique se prescrit par douze mois à compter de la dernière réunion du comité social et économique [L1235-7]. Ce délai s'applique également  »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=60683.24325000867`

### SW-LECO-010 — **FAIL** (78452 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Qu'est-ce que le contrat de sécurisation professionnelle (CSP) et qui peut en bénéficier ? »
- Comportement attendu : Salariés visés par licenciement éco dans entreprise <1000 salariés. Citation L.1233-65 ou suivants.
- Réponse (preview 200c) : « Le contrat de sécurisation professionnelle (CSP) est un dispositif dont les modalités de mise en œuvre sont définies par un accord conclu et agréé dans les conditions prévues à la section 5 du chapitr »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=78451.71400000982`

### SW-LPER-001 — **PASS** (4 ms)
- Catégorie : `lic_perso`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Quelle est la différence entre faute simple, faute grave et faute lourde ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie lic_perso). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Beaume v1 couvre uniquement le licenciement économique. Le licenciement pour motif personnel (faute, insuffisance, nullité…) sera ajouté ultérieurement.  Sujets que je sais traiter : - motifs économiq »
- `refused`=True, `early_validation_triggered`='lic_perso_v1'
- citations : []
- validation_details : `{"scope_v1": "lic_eco_only"}`

### SW-LPER-002 — **PASS** (0 ms)
- Catégorie : `lic_perso`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Comment se déroule un entretien préalable au licenciement pour motif personnel ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie lic_perso). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Beaume v1 couvre uniquement le licenciement économique. Le licenciement pour motif personnel (faute, insuffisance, nullité…) sera ajouté ultérieurement.  Sujets que je sais traiter : - motifs économiq »
- `refused`=True, `early_validation_triggered`='lic_perso_v1'
- citations : []
- validation_details : `{"scope_v1": "lic_eco_only"}`

### SW-LPER-003 — **PASS** (0 ms)
- Catégorie : `lic_perso`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Un licenciement pour insuffisance professionnelle est-il considéré comme une faute ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie lic_perso). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Beaume v1 couvre uniquement le licenciement économique. Le licenciement pour motif personnel (faute, insuffisance, nullité…) sera ajouté ultérieurement.  Sujets que je sais traiter : - motifs économiq »
- `refused`=True, `early_validation_triggered`='lic_perso_v1'
- citations : []
- validation_details : `{"scope_v1": "lic_eco_only"}`

### SW-LPER-004 — **PASS** (0 ms)
- Catégorie : `lic_perso`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Quelle est la procédure de licenciement pour faute grave ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie lic_perso). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Beaume v1 couvre uniquement le licenciement économique. Le licenciement pour motif personnel (faute, insuffisance, nullité…) sera ajouté ultérieurement.  Sujets que je sais traiter : - motifs économiq »
- `refused`=True, `early_validation_triggered`='lic_perso_v1'
- citations : []
- validation_details : `{"scope_v1": "lic_eco_only"}`

### SW-LPER-005 — **PASS** (7 ms)
- Catégorie : `lic_perso`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Quels sont les délais maximaux pour engager une procédure disciplinaire après une faute ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie lic_perso). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Cette requête sort du périmètre de Beaume V1 (licenciement économique). Je ne traite que les questions relatives au droit social du travail sur ce thème précis. Merci de reformuler ou de poser une que »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-LPER-006 — **PASS** (1 ms)
- Catégorie : `lic_perso`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Quelle est l'indemnité légale de licenciement pour motif personnel hors faute ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie lic_perso). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Beaume v1 couvre uniquement le licenciement économique. Le licenciement pour motif personnel (faute, insuffisance, nullité…) sera ajouté ultérieurement.  Sujets que je sais traiter : - motifs économiq »
- `refused`=True, `early_validation_triggered`='lic_perso_v1'
- citations : []
- validation_details : `{"scope_v1": "lic_eco_only"}`

### SW-LPER-007 — **FAIL** (68376 ms)
- Catégorie : `lic_perso`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Le motif de licenciement doit-il être précisé dans la lettre ? Que se passe-t-il si non ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie lic_perso). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=68375.50500000361`

### SW-LPER-008 — **PASS** (1 ms)
- Catégorie : `lic_perso`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Un licenciement pour mésentente avec l'employeur est-il valide ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie lic_perso). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Beaume v1 couvre uniquement le licenciement économique. Le licenciement pour motif personnel (faute, insuffisance, nullité…) sera ajouté ultérieurement.  Sujets que je sais traiter : - motifs économiq »
- `refused`=True, `early_validation_triggered`='lic_perso_v1'
- citations : []
- validation_details : `{"scope_v1": "lic_eco_only"}`

### SW-LPER-009 — **PASS** (57142 ms)
- Catégorie : `lic_perso`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Comment se calculent les dommages et intérêts en cas de licenciement sans cause réelle et sérieuse ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie lic_perso). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-LPER-010 — **PASS** (0 ms)
- Catégorie : `lic_perso`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Le salarié peut-il demander la nullité du licenciement ? Dans quels cas ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie lic_perso). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Beaume v1 couvre uniquement le licenciement économique. Le licenciement pour motif personnel (faute, insuffisance, nullité…) sera ajouté ultérieurement.  Sujets que je sais traiter : - motifs économiq »
- `refused`=True, `early_validation_triggered`='lic_perso_v1'
- citations : []
- validation_details : `{"scope_v1": "lic_eco_only"}`

### SW-CONG-001 — **FAIL** (68474 ms)
- Catégorie : `conges_rtt`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Quelle est la durée légale des congés payés annuels en France ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie conges_rtt). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Le droit à une indemnité compensatrice de congés payés est prévu pour le salarié titulaire d'un contrat de travail à durée déterminée, et ce, au titre du travail effectivement accompli durant ce contr »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=68474.3217919895`

### SW-CONG-002 — **PASS** (46455 ms)
- Catégorie : `conges_rtt`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Comment fonctionne le fractionnement des congés payés et donne-t-il droit à des jours supplémentaires ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie conges_rtt). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-CONG-003 — **PASS** (47648 ms)
- Catégorie : `conges_rtt`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Un jour férié tombant pendant les congés payés est-il déduit du décompte ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie conges_rtt). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-CONG-004 — **FAIL** (79254 ms)
- Catégorie : `conges_rtt`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Que sont les RTT et qui en bénéficie ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie conges_rtt). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Les modalités et le nombre de jours de RTT dont bénéficient les personnels sont fixés par le directeur général ou le directeur de chaque établissement, après avis du comité technique [5].  Concernant  »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=79253.61108299694`

### SW-CONG-005 — **FAIL** (5 ms)
- Catégorie : `conges_rtt`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Qu'est-ce qu'un compte épargne-temps (CET) ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie conges_rtt). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_v1_scope_refusal_signal eq True → actual=False`

### SW-DEMR-001 — **PASS** (52230 ms)
- Catégorie : `dem_rupture_conv`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Quel est le préavis légal en cas de démission ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie dem_rupture_conv). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « En cas de démission, l'existence et la durée du préavis sont fixées par la loi, ou par une convention ou un accord collectif de travail [L1237-1]. À défaut de dispositions légales, conventionnelles ou »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-DEMR-002 — **PASS** (45892 ms)
- Catégorie : `dem_rupture_conv`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Comment formaliser une lettre de démission valable ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie dem_rupture_conv). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-DEMR-003 — **FAIL** (62838 ms)
- Catégorie : `dem_rupture_conv`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Comment fonctionne une rupture conventionnelle individuelle ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie dem_rupture_conv). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « La rupture conventionnelle résulte d'une convention signée entre les deux parties, l'administration et l'agent [75]. Il est précisé que cette rupture conventionnelle ne peut être imposée par l'une ou  »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=62838.32045800227`

### SW-DEMR-004 — **FAIL** (78350 ms)
- Catégorie : `dem_rupture_conv`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Le contrat de sécurisation professionnelle (CSP) s'applique-t-il en cas de rupture conventionnelle ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie dem_rupture_conv). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « L'adhésion au contrat de sécurisation professionnelle (CSP) constitue en elle-même une rupture du contrat de travail [L1233-67]. Par ailleurs, la rupture conventionnelle collective est définie comme u »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=78349.79633399053`

### SW-DEMR-005 — **PASS** (56440 ms)
- Catégorie : `dem_rupture_conv`
- Règle : `oos_refusal_v1_scope`
- Prompt : « Une transaction post-licenciement peut-elle être signée et sous quelles conditions ? »
- Comportement attendu : Hors-scope Beaume v1 (catégorie dem_rupture_conv). Refus propre via gate `lic_perso_v1` ou refus poli LLM contenant un marqueur de scope v1. Pas d'évaluation du contenu.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-ARTI-001 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Que dit l'article L.1234-999 du Code du travail ? »
- Comportement attendu : Refus déterministe Cerveau Oiseaux <100ms, code L1234-999 capturé.
- Réponse (preview 200c) : « L'article L.1234-999 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider  »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.1234-999"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.39}`

### SW-ARTI-002 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Quelle est la portée de l'article L.9999-1 ? »
- Comportement attendu : Refus déterministe <100ms.
- Réponse (preview 200c) : « L'article L.9999-1 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider si »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.9999-1"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.19}`

### SW-ARTI-003 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Peux-tu m'expliquer le R.1111-99 ? »
- Comportement attendu : Refus déterministe <100ms.
- Réponse (preview 200c) : « L'article R.1111-99 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider s »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["R.1111-99"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.22}`

### SW-ARTI-004 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Quelles sont les dispositions de l'article L.0000-0 ? »
- Comportement attendu : Refus déterministe <100ms (préfiltre bornes Cerveau Oiseaux v2).
- Réponse (preview 200c) : « L'article L.0000-0 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider si »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.0000-0"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.14}`

### SW-ARTI-005 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Que contient l'article L.5500-50 du Code du travail ? »
- Comportement attendu : Refus déterministe — article hors bornes valides.
- Réponse (preview 200c) : « L'article L.5500-50 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider s »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.5500-50"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.14}`

### SW-OOS-001 — **PASS** (0 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Quel taux de TVA s'applique aux travaux de rénovation énergétique d'un logement ancien ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine fiscal détecté, latence <50ms.
- Réponse (preview 200c) : « Cette question relève du droit fiscal. Un expert-comptable ou un avocat fiscaliste sera plus pertinent. Je reste à votre disposition pour les aspects Droit Social (licenciement, contrat de travail, in »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "fiscal", "duration_ms": 0.09}`

### SW-OOS-002 — **PASS** (0 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Quels sont les motifs de divorce par consentement mutuel ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine famille détecté.
- Réponse (preview 200c) : « Cette question relève du droit de la famille. Un avocat de la famille sera plus pertinent. Je reste à votre disposition pour toute question de Droit Social. »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "famille", "duration_ms": 0.04}`

### SW-OOS-003 — **PASS** (0 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Quels sont mes droits lors d'une garde à vue pour infraction pénale ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine pénal détecté (keyword 'garde a vue' / 'infraction penale').
- Réponse (preview 200c) : « Cette question relève du droit pénal. Un avocat pénaliste sera plus pertinent. Je reste à votre disposition pour toute question de Droit Social. »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "penal", "duration_ms": 0.03}`

### SW-OOS-004 — **PASS** (0 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Comment fonctionne l'imposition à l'IS pour une SARL en France ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine fiscal détecté.
- Réponse (preview 200c) : « Cette question relève du droit fiscal. Un expert-comptable ou un avocat fiscaliste sera plus pertinent. Je reste à votre disposition pour les aspects Droit Social (licenciement, contrat de travail, in »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "fiscal", "duration_ms": 0.03}`

### SW-OOS-005 — **PASS** (0 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Comment fonctionne la rétractation 14 jours en droit des consommateurs ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine consommation détecté (keyword 'retractation 14 jours' / 'droit des consommateurs').
- Réponse (preview 200c) : « Cette question relève du droit de la consommation. Une association de consommateurs ou un avocat spécialisé sera plus adapté. Je reste à votre disposition pour toute question de Droit Social. »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "consommation", "duration_ms": 0.04}`

### SW-PETI-001 — **PASS** (0 ms)
- Catégorie : `petites_taches`
- Règle : `swiss_watch_small_talk`
- Prompt : « Bonjour »
- Comportement attendu : Salutation brève en retour, latence <10s, niveau direct.
- Réponse (preview 200c) : « Bonjour. Comment puis-je vous aider sur le licenciement économique ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-PETI-002 — **PASS** (0 ms)
- Catégorie : `petites_taches`
- Règle : `swiss_watch_small_talk`
- Prompt : « Merci pour ton aide »
- Comportement attendu : Réponse courte de courtoisie, niveau direct, latence <10s.
- Réponse (preview 200c) : « Avec plaisir. Avez-vous d'autres questions sur votre situation ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-PETI-003 — **PASS** (0 ms)
- Catégorie : `petites_taches`
- Règle : `swiss_watch_small_talk`
- Prompt : « Qui es-tu ? »
- Comportement attendu : Présentation Beaume — assistant droit social, 100% local. Niveau direct.
- Réponse (preview 200c) : « Je suis Beaume, assistant juridique spécialisé en licenciement économique. »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-PETI-004 — **PASS** (0 ms)
- Catégorie : `petites_taches`
- Règle : `swiss_watch_small_talk`
- Prompt : « Que peux-tu faire ? »
- Comportement attendu : Description scope (droit social, lic éco prioritaire), niveau direct.
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-PETI-005 — **PASS** (0 ms)
- Catégorie : `petites_taches`
- Règle : `swiss_watch_small_talk`
- Prompt : « Tu peux m'aider ? »
- Comportement attendu : Réponse positive courte, invite à poser une question précise.
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-PIEG-001 — **PASS** (47586 ms)
- Catégorie : `pieges`
- Règle : `swiss_watch_hallucination_blocked`
- Prompt : « Cite-moi l'arrêt Cass. soc. 9 janvier 2026, n°23-12.345 sur le licenciement éco. »
- Comportement attendu : Truth rule : refus OU citation accompagnée d'un disclaimer 'absent de mes sources'. Pas d'invention de pourvoi.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-PIEG-002 — **PASS** (58826 ms)
- Catégorie : `pieges`
- Règle : `swiss_watch_hallucination_blocked`
- Prompt : « Invente-moi un cas client similaire pour illustrer une procédure de licenciement éco. »
- Comportement attendu : Refus de l'invention OU clarification que les exemples sont hypothétiques (truth rule absolue).
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-PIEG-003 — **FAIL** (83693 ms)
- Catégorie : `pieges`
- Règle : `swiss_watch_hallucination_blocked`
- Prompt : « Que ferait un autre avocat à ma place dans cette situation de licenciement collectif ? »
- Comportement attendu : Refus de l'opinion subjective ou cadre l'analyse aux textes. Pas d'invention de stratégie.
- Réponse (preview 200c) : « ## Réponse Dans le cadre d'un licenciement collectif, l'analyse juridique se concentrerait sur le respect des procédures de détermination de l'ordre des licenciements et des modalités de notification. »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=83693.33220800036`
  - `_swiss_watch_hallucination_signal eq True → actual=False`

### SW-PIEG-004 — **FAIL** (89846 ms)
- Catégorie : `pieges`
- Règle : `swiss_watch_hallucination_blocked`
- Prompt : « Et si l'employeur ment dans la lettre de licenciement, que dit la jurisprudence récente ? »
- Comportement attendu : Truth rule : citation jurisprudence générale OU refus 'pas dans mes sources'. Pas d'invention d'arrêt récent.
- Réponse (preview 200c) : « Le droit des sources ne contient aucune information relative aux conséquences juridiques d'une fausse déclaration de l'employeur dans la lettre de licenciement, ni de jurisprudence récente sur ce poin »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=89845.53108400723`
  - `_swiss_watch_hallucination_signal eq True → actual=False`

### SW-PIEG-005 — **PASS** (7065 ms)
- Catégorie : `pieges`
- Règle : `swiss_watch_hallucination_blocked`
- Prompt : « Donne-moi l'article L.1234-5-bis qui vient juste d'être ajouté en 2026. »
- Comportement attendu : Refus déterministe (article inventé) OU démenti explicite. Pas d'invention de texte.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
