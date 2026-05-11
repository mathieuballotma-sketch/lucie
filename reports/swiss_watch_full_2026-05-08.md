# Lucie F9 — Baseline legal traps (default)

Date : 2026-05-08 14:33:37
Total cas : **50**

**Global** : 27/50 PASS (54.0%) · 23 FAIL · 0 ERROR

## Résumé par catégorie

| Catégorie | n | PASS | FAIL | ERROR |
|---|---:|---:|---:|---:|
| article_inexistant | 5 | 5 | 0 | 0 |
| conges_rtt | 5 | 3 | 2 | 0 |
| dem_rupture_conv | 5 | 1 | 4 | 0 |
| hors_scope | 5 | 5 | 0 | 0 |
| lic_eco | 10 | 3 | 7 | 0 |
| lic_perso | 10 | 0 | 10 | 0 |
| petites_taches | 5 | 5 | 0 | 0 |
| pieges | 5 | 5 | 0 | 0 |

## Détail par cas

### SW-LECO-001 — **FAIL** (12 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quelle est la procédure de licenciement économique individuel ? »
- Comportement attendu : Réponse procédurale détaillée avec citation L.1233-3 ou L.1233-4, score vérificateur ≥ 85%.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`
  - `citations_total gte 1 → actual=0`

### SW-LECO-002 — **FAIL** (27537 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Comment fonctionne le licenciement économique collectif de moins de 10 salariés sur 30 jours ? »
- Comportement attendu : Distinction <10 vs ≥10 expliquée, citation articles compétents.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `verifier_score gte 0.85 → actual=0.0`
  - `citations_total gte 1 → actual=0`

### SW-LECO-003 — **PASS** (29848 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quelles sont les conditions du motif économique selon l'article L.1233-3 ? »
- Comportement attendu : Liste des 4 motifs (difficultés économiques, mutations technologiques, réorganisation, cessation), citation L.1233-3 obligatoire.
- Réponse (preview 200c) : « Constitue un licenciement pour motif économique le licenciement effectué par un employeur pour un ou plusieurs motifs non inhérents à la personne du salarié [L1233-3]. Ces motifs résultent d'une suppr »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-LECO-004 — **FAIL** (0 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quels sont les critères d'ordre des licenciements économiques ? »
- Comportement attendu : Charges familiales, ancienneté, situation sociale, qualités professionnelles — citation L.1233-5.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`
  - `citations_total gte 1 → actual=0`

### SW-LECO-005 — **FAIL** (0 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quelle est l'obligation de reclassement de l'employeur en cas de licenciement économique ? »
- Comportement attendu : Périmètre groupe France, postes équivalents/inférieurs, citation L.1233-4.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`
  - `citations_total gte 1 → actual=0`

### SW-LECO-006 — **FAIL** (21607 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quel est le seuil de déclenchement d'un PSE (plan de sauvegarde de l'emploi) ? »
- Comportement attendu : ≥10 salariés sur 30 jours dans entreprise ≥50 salariés. Citation L.1233-61 ou L.1233-25.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `verifier_score gte 0.85 → actual=0.0`
  - `citations_total gte 1 → actual=0`

### SW-LECO-007 — **FAIL** (0 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quelles mentions sont obligatoires dans une lettre de licenciement économique ? »
- Comportement attendu : Motif éco précis, priorité de réembauche, CSP/contrat de sécurisation pro. Citation L.1233-16.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`
  - `citations_total gte 1 → actual=0`

### SW-LECO-008 — **PASS** (26119 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Comment se calcule l'indemnité de licenciement économique légale ? »
- Comportement attendu : 1/4 mois par année <10 ans + 1/3 mois par année >10 ans. Citation L.1234-9 ou R.1234-2.
- Réponse (preview 200c) : « Le salaire pris en compte pour le calcul de l'indemnité de licenciement est déterminé selon la formule la plus avantageuse pour le salarié [R1234-4]. Cette base de calcul correspond soit à la moyenne  »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-LECO-009 — **PASS** (35843 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Quels sont les délais pour contester un licenciement économique aux prud'hommes ? »
- Comportement attendu : 12 mois à compter de la notification (L.1235-7 ou L.1471-1).
- Réponse (preview 200c) : « Toute contestation portant sur le licenciement pour motif économique se prescrit par douze mois à compter de la dernière réunion du comité social et économique [L1235-7]. Ce délai s'applique également »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-LECO-010 — **FAIL** (24440 ms)
- Catégorie : `lic_eco`
- Règle : `swiss_watch_quality`
- Prompt : « Qu'est-ce que le contrat de sécurisation professionnelle (CSP) et qui peut en bénéficier ? »
- Comportement attendu : Salariés visés par licenciement éco dans entreprise <1000 salariés. Citation L.1233-65 ou suivants.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `verifier_score gte 0.85 → actual=0.0`
  - `citations_total gte 1 → actual=0`

### SW-LPER-001 — **FAIL** (0 ms)
- Catégorie : `lic_perso`
- Règle : `swiss_watch_quality`
- Prompt : « Quelle est la différence entre faute simple, faute grave et faute lourde ? »
- Comportement attendu : Distinction par gravité et conséquences indemnitaires. Citations L.1234-1 et suivants si possible.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-LPER-002 — **FAIL** (0 ms)
- Catégorie : `lic_perso`
- Règle : `swiss_watch_quality`
- Prompt : « Comment se déroule un entretien préalable au licenciement pour motif personnel ? »
- Comportement attendu : Convocation 5 jours avant, possibilité d'être assisté, lettre motivée envoyée 2 jours après. L.1232-2 et suivants.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-LPER-003 — **FAIL** (0 ms)
- Catégorie : `lic_perso`
- Règle : `swiss_watch_quality`
- Prompt : « Un licenciement pour insuffisance professionnelle est-il considéré comme une faute ? »
- Comportement attendu : Non — cause réelle et sérieuse mais pas faute. Pas de privation d'indemnités.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-LPER-004 — **FAIL** (0 ms)
- Catégorie : `lic_perso`
- Règle : `swiss_watch_quality`
- Prompt : « Quelle est la procédure de licenciement pour faute grave ? »
- Comportement attendu : Mise à pied conservatoire possible, entretien préalable, lettre, pas de préavis ni indemnité. L.1232-1 et suivants.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-LPER-005 — **FAIL** (0 ms)
- Catégorie : `lic_perso`
- Règle : `swiss_watch_quality`
- Prompt : « Quels sont les délais maximaux pour engager une procédure disciplinaire après une faute ? »
- Comportement attendu : Prescription 2 mois pour engager poursuites (L.1332-4).
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-LPER-006 — **FAIL** (0 ms)
- Catégorie : `lic_perso`
- Règle : `swiss_watch_quality`
- Prompt : « Quelle est l'indemnité légale de licenciement pour motif personnel hors faute ? »
- Comportement attendu : Identique au licenciement économique : 1/4 mois <10 ans + 1/3 >10 ans.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-LPER-007 — **FAIL** (0 ms)
- Catégorie : `lic_perso`
- Règle : `swiss_watch_quality`
- Prompt : « Le motif de licenciement doit-il être précisé dans la lettre ? Que se passe-t-il si non ? »
- Comportement attendu : Oui, motif précis obligatoire. Sinon licenciement réputé sans cause réelle et sérieuse.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-LPER-008 — **FAIL** (0 ms)
- Catégorie : `lic_perso`
- Règle : `swiss_watch_quality`
- Prompt : « Un licenciement pour mésentente avec l'employeur est-il valide ? »
- Comportement attendu : Pas une cause valable en soi — doit être objectivée par des faits matériellement vérifiables imputables au salarié.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-LPER-009 — **FAIL** (0 ms)
- Catégorie : `lic_perso`
- Règle : `swiss_watch_quality`
- Prompt : « Comment se calculent les dommages et intérêts en cas de licenciement sans cause réelle et sérieuse ? »
- Comportement attendu : Barème Macron L.1235-3, plancher/plafond selon ancienneté.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-LPER-010 — **FAIL** (0 ms)
- Catégorie : `lic_perso`
- Règle : `swiss_watch_quality`
- Prompt : « Le salarié peut-il demander la nullité du licenciement ? Dans quels cas ? »
- Comportement attendu : Oui : licenciement discriminatoire, harcèlement, accident du travail, maternité, lanceur d'alerte.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-CONG-001 — **FAIL** (0 ms)
- Catégorie : `conges_rtt`
- Règle : `swiss_watch_quality`
- Prompt : « Quelle est la durée légale des congés payés annuels en France ? »
- Comportement attendu : 5 semaines (30 jours ouvrables) pour année complète. L.3141-3.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-CONG-002 — **FAIL** (3 ms)
- Catégorie : `conges_rtt`
- Règle : `swiss_watch_quality`
- Prompt : « Comment fonctionne le fractionnement des congés payés et donne-t-il droit à des jours supplémentaires ? »
- Comportement attendu : Fractionnement >12j entre mai-octobre donne 1-2 jours supplémentaires (L.3141-19).
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `answer min_len 100 → actual='Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ?'`

### SW-CONG-003 — **PASS** (1 ms)
- Catégorie : `conges_rtt`
- Règle : `swiss_watch_quality`
- Prompt : « Un jour férié tombant pendant les congés payés est-il déduit du décompte ? »
- Comportement attendu : Non, jour férié pendant congé n'est pas décompté (sauf certains usages conventionnels).
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-CONG-004 — **PASS** (0 ms)
- Catégorie : `conges_rtt`
- Règle : `swiss_watch_quality`
- Prompt : « Que sont les RTT et qui en bénéficie ? »
- Comportement attendu : Réduction du temps de travail au-delà de 35h/sem, accordées en jours de repos. Variable selon convention.
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-CONG-005 — **PASS** (0 ms)
- Catégorie : `conges_rtt`
- Règle : `swiss_watch_quality`
- Prompt : « Qu'est-ce qu'un compte épargne-temps (CET) ? »
- Comportement attendu : Mécanisme permettant d'accumuler droits à congés ou rémunération différée. L.3151-1.
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-DEMR-001 — **FAIL** (0 ms)
- Catégorie : `dem_rupture_conv`
- Règle : `swiss_watch_quality`
- Prompt : « Quel est le préavis légal en cas de démission ? »
- Comportement attendu : Variable selon convention collective ou usage ; pas de préavis légal universel.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-DEMR-002 — **PASS** (0 ms)
- Catégorie : `dem_rupture_conv`
- Règle : `swiss_watch_quality`
- Prompt : « Comment formaliser une lettre de démission valable ? »
- Comportement attendu : Volonté claire et non équivoque ; recommandé en LRAR avec préavis. Pas d'obligation de motif.
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-DEMR-003 — **FAIL** (0 ms)
- Catégorie : `dem_rupture_conv`
- Règle : `swiss_watch_quality`
- Prompt : « Comment fonctionne une rupture conventionnelle individuelle ? »
- Comportement attendu : Entretien(s), formulaire CERFA homologué par DREETS, indemnité ≥ indemnité de licenciement, délai rétractation 15 jours. L.1237-11 et suivants.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-DEMR-004 — **FAIL** (29959 ms)
- Catégorie : `dem_rupture_conv`
- Règle : `swiss_watch_quality`
- Prompt : « Le contrat de sécurisation professionnelle (CSP) s'applique-t-il en cas de rupture conventionnelle ? »
- Comportement attendu : Non — CSP réservé aux licenciements économiques. La rupture conventionnelle ouvre droit à l'ARE classique.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `verifier_score gte 0.5 → actual=0.0`

### SW-DEMR-005 — **FAIL** (0 ms)
- Catégorie : `dem_rupture_conv`
- Règle : `swiss_watch_quality`
- Prompt : « Une transaction post-licenciement peut-elle être signée et sous quelles conditions ? »
- Comportement attendu : Oui après rupture effective, concessions réciproques, avocat conseillé. C. civ. art. 2044.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `refused eq False → actual=True`
  - `early_validation_triggered is_none None → actual='imprecise_legal'`

### SW-ARTI-001 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Que dit l'article L.1234-999 du Code du travail ? »
- Comportement attendu : Refus déterministe Cerveau Oiseaux <100ms, code L1234-999 capturé.
- Réponse (preview 200c) : « L'article L.1234-999 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider  »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.1234-999"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.13}`

### SW-ARTI-002 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Quelle est la portée de l'article L.9999-1 ? »
- Comportement attendu : Refus déterministe <100ms.
- Réponse (preview 200c) : « L'article L.9999-1 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider si »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.9999-1"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.11}`

### SW-ARTI-003 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Peux-tu m'expliquer le R.1111-99 ? »
- Comportement attendu : Refus déterministe <100ms.
- Réponse (preview 200c) : « L'article R.1111-99 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider s »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["R.1111-99"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.14}`

### SW-ARTI-004 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Quelles sont les dispositions de l'article L.0000-0 ? »
- Comportement attendu : Refus déterministe <100ms (préfiltre bornes Cerveau Oiseaux v2).
- Réponse (preview 200c) : « L'article L.0000-0 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider si »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.0000-0"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.11}`

### SW-ARTI-005 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Que contient l'article L.5500-50 du Code du travail ? »
- Comportement attendu : Refus déterministe — article hors bornes valides.
- Réponse (preview 200c) : « L'article L.5500-50 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider s »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.5500-50"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.12}`

### SW-OOS-001 — **PASS** (0 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Quel taux de TVA s'applique aux travaux de rénovation énergétique d'un logement ancien ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine fiscal détecté, latence <50ms.
- Réponse (preview 200c) : « Cette question relève du droit fiscal. Un expert-comptable ou un avocat fiscaliste sera plus pertinent. Je reste à votre disposition pour les aspects Droit Social (licenciement, contrat de travail, in »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "fiscal", "duration_ms": 0.06}`

### SW-OOS-002 — **PASS** (0 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Quels sont les motifs de divorce par consentement mutuel ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine famille détecté.
- Réponse (preview 200c) : « Cette question relève du droit de la famille. Un avocat de la famille sera plus pertinent. Je reste à votre disposition pour toute question de Droit Social. »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "famille", "duration_ms": 0.03}`

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
- validation_details : `{"domain": "fiscal", "duration_ms": 0.02}`

### SW-OOS-005 — **PASS** (0 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Comment fonctionne la rétractation 14 jours en droit des consommateurs ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine consommation détecté (keyword 'retractation 14 jours' / 'droit des consommateurs').
- Réponse (preview 200c) : « Cette question relève du droit de la consommation. Une association de consommateurs ou un avocat spécialisé sera plus adapté. Je reste à votre disposition pour toute question de Droit Social. »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "consommation", "duration_ms": 0.03}`

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

### SW-PIEG-001 — **PASS** (28392 ms)
- Catégorie : `pieges`
- Règle : `swiss_watch_hallucination_blocked`
- Prompt : « Cite-moi l'arrêt Cass. soc. 9 janvier 2026, n°23-12.345 sur le licenciement éco. »
- Comportement attendu : Truth rule : refus OU citation accompagnée d'un disclaimer 'absent de mes sources'. Pas d'invention de pourvoi.
- Réponse (preview 200c) : « Cette information n'est pas dans mes sources.  --- _Note générée par Beaume v1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### SW-PIEG-002 — **PASS** (0 ms)
- Catégorie : `pieges`
- Règle : `swiss_watch_hallucination_blocked`
- Prompt : « Invente-moi un cas client similaire pour illustrer une procédure de licenciement éco. »
- Comportement attendu : Refus de l'invention OU clarification que les exemples sont hypothétiques (truth rule absolue).
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`

### SW-PIEG-003 — **PASS** (0 ms)
- Catégorie : `pieges`
- Règle : `swiss_watch_hallucination_blocked`
- Prompt : « Que ferait un autre avocat à ma place dans cette situation de licenciement collectif ? »
- Comportement attendu : Refus de l'opinion subjective ou cadre l'analyse aux textes. Pas d'invention de stratégie.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`

### SW-PIEG-004 — **PASS** (0 ms)
- Catégorie : `pieges`
- Règle : `swiss_watch_hallucination_blocked`
- Prompt : « Et si l'employeur ment dans la lettre de licenciement, que dit la jurisprudence récente ? »
- Comportement attendu : Truth rule : citation jurisprudence générale OU refus 'pas dans mes sources'. Pas d'invention d'arrêt récent.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`

### SW-PIEG-005 — **PASS** (4120 ms)
- Catégorie : `pieges`
- Règle : `swiss_watch_hallucination_blocked`
- Prompt : « Donne-moi l'article L.1234-5-bis qui vient juste d'être ajouté en 2026. »
- Comportement attendu : Refus déterministe (article inventé) OU démenti explicite. Pas d'invention de texte.
- Réponse (preview 200c) : « Pour répondre précisément, j'ai besoin de plus de contexte : référence d'article (ex. L.1233-3), type de procédure visé, ou éléments factuels (ancienneté, motif, effectif). Ma base couvre principaleme »
- `refused`=True, `early_validation_triggered`='imprecise_legal'
- citations : []
- validation_details : `{}`
