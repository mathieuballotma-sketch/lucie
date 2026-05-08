# Lucie F9 — Baseline legal traps (default)

Date : 2026-05-08 14:24:49
Total cas : **5**

**Global** : 5/5 PASS (100.0%) · 0 FAIL · 0 ERROR

## Résumé par catégorie

| Catégorie | n | PASS | FAIL | ERROR |
|---|---:|---:|---:|---:|
| hors_scope | 5 | 5 | 0 | 0 |

## Détail par cas

### SW-OOS-001 — **PASS** (10 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Quel taux de TVA s'applique aux travaux de rénovation énergétique d'un logement ancien ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine fiscal détecté, latence <50ms.
- Réponse (preview 200c) : « Cette question relève du droit fiscal. Un expert-comptable ou un avocat fiscaliste sera plus pertinent. Je reste à votre disposition pour les aspects Droit Social (licenciement, contrat de travail, in »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "fiscal", "duration_ms": 10.38}`

### SW-OOS-002 — **PASS** (0 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Quels sont les motifs de divorce par consentement mutuel ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine famille détecté.
- Réponse (preview 200c) : « Cette question relève du droit de la famille. Un avocat de la famille sera plus pertinent. Je reste à votre disposition pour toute question de Droit Social. »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "famille", "duration_ms": 0.01}`

### SW-OOS-003 — **PASS** (0 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Quels sont mes droits lors d'une garde à vue pour infraction pénale ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine pénal détecté (keyword 'garde a vue' / 'infraction penale').
- Réponse (preview 200c) : « Cette question relève du droit pénal. Un avocat pénaliste sera plus pertinent. Je reste à votre disposition pour toute question de Droit Social. »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "penal", "duration_ms": 0.01}`

### SW-OOS-004 — **PASS** (0 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Comment fonctionne l'imposition à l'IS pour une SARL en France ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine fiscal détecté.
- Réponse (preview 200c) : « Cette question relève du droit fiscal. Un expert-comptable ou un avocat fiscaliste sera plus pertinent. Je reste à votre disposition pour les aspects Droit Social (licenciement, contrat de travail, in »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "fiscal", "duration_ms": 0.01}`

### SW-OOS-005 — **PASS** (0 ms)
- Catégorie : `hors_scope`
- Règle : `oos_refusal`
- Prompt : « Comment fonctionne la rétractation 14 jours en droit des consommateurs ? »
- Comportement attendu : Refus poli Cerveau Oiseaux, domaine consommation détecté (keyword 'retractation 14 jours' / 'droit des consommateurs').
- Réponse (preview 200c) : « Cette question relève du droit de la consommation. Une association de consommateurs ou un avocat spécialisé sera plus adapté. Je reste à votre disposition pour toute question de Droit Social. »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "consommation", "duration_ms": 0.01}`
