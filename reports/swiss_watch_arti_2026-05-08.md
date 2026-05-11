# Lucie F9 — Baseline legal traps (default)

Date : 2026-05-08 14:23:33
Total cas : **5**

**Global** : 5/5 PASS (100.0%) · 0 FAIL · 0 ERROR

## Résumé par catégorie

| Catégorie | n | PASS | FAIL | ERROR |
|---|---:|---:|---:|---:|
| article_inexistant | 5 | 5 | 0 | 0 |

## Détail par cas

### SW-ARTI-001 — **PASS** (13 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Que dit l'article L.1234-999 du Code du travail ? »
- Comportement attendu : Refus déterministe Cerveau Oiseaux <100ms, code L1234-999 capturé.
- Réponse (preview 200c) : « L'article L.1234-999 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider  »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.1234-999"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 2.9}`

### SW-ARTI-002 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Quelle est la portée de l'article L.9999-1 ? »
- Comportement attendu : Refus déterministe <100ms.
- Réponse (preview 200c) : « L'article L.9999-1 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider si »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.9999-1"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.06}`

### SW-ARTI-003 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Peux-tu m'expliquer le R.1111-99 ? »
- Comportement attendu : Refus déterministe <100ms.
- Réponse (preview 200c) : « L'article R.1111-99 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider s »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["R.1111-99"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.06}`

### SW-ARTI-004 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Quelles sont les dispositions de l'article L.0000-0 ? »
- Comportement attendu : Refus déterministe <100ms (préfiltre bornes Cerveau Oiseaux v2).
- Réponse (preview 200c) : « L'article L.0000-0 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider si »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.0000-0"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.06}`

### SW-ARTI-005 — **PASS** (0 ms)
- Catégorie : `article_inexistant`
- Règle : `article_invalid`
- Prompt : « Que contient l'article L.5500-50 du Code du travail ? »
- Comportement attendu : Refus déterministe — article hors bornes valides.
- Réponse (preview 200c) : « L'article L.5500-50 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider s »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.5500-50"], "resolvers": ["sqlite-legifrance", "whitelist-ct"], "duration_ms": 0.06}`
