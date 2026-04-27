# Lucie F9 — Baseline legal traps (gemma4:e4b)

Date : 2026-04-27 19:56:43
Total cas : **20**

**Global** : 14/20 PASS (70.0%) · 6 FAIL · 0 ERROR

## Résumé par catégorie

| Catégorie | n | PASS | FAIL | ERROR |
|---|---:|---:|---:|---:|
| article_invalid | 4 | 4 | 0 | 0 |
| citation_required | 4 | 0 | 4 | 0 |
| mixed_trap | 4 | 3 | 1 | 0 |
| out_of_scope_config | 2 | 2 | 0 | 0 |
| out_of_scope_fallthrough | 2 | 2 | 0 | 0 |
| scope_simple | 4 | 3 | 1 | 0 |

## Détail par cas

### LEG-SCOPE-01 — **FAIL** (211642 ms)
- Catégorie : `scope_simple`
- Règle : `in_scope_answers`
- Prompt : « Quelle est la procédure de licenciement pour motif personnel ? »
- Comportement attendu : Réponse non-vide dans le scope Droit Social, sans refus précoce.
- Réponse (preview 200c) : « Aucune source disponible sur la procédure de licenciement pour motif personnel.  Les sources fournies traitent exclusivement de la procédure de licenciement pour motif économique. Elles indiquent que  »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=211642.09525000025`

### LEG-SCOPE-02 — **PASS** (35942 ms)
- Catégorie : `scope_simple`
- Règle : `in_scope_answers`
- Prompt : « Comment fonctionne une rupture conventionnelle individuelle ? »
- Comportement attendu : Réponse non-vide dans le scope Droit Social, sans refus précoce.
- Réponse (preview 200c) : « Aucune source disponible sur ce point. Les sources fournies traitent uniquement des modalités de licenciement pour motif économique et ne contiennent aucune information concernant le fonctionnement d' »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### LEG-SCOPE-03 — **PASS** (1 ms)
- Catégorie : `scope_simple`
- Règle : `in_scope_answers`
- Prompt : « Combien de semaines dure le congé maternité légal en France ? »
- Comportement attendu : Réponse factuelle courte, sans refus précoce.
- Réponse (preview 200c) : « Cette requête sort du périmètre de Lucie V1 (licenciement économique). Je ne traite que les questions relatives au droit social du travail sur ce thème précis. Merci de reformuler ou de poser une ques »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### LEG-SCOPE-04 — **PASS** (33250 ms)
- Catégorie : `scope_simple`
- Règle : `in_scope_answers`
- Prompt : « Comment saisir le conseil de prud'hommes en référé ? »
- Comportement attendu : Réponse procédurale dans le scope Droit Social, sans refus précoce.
- Réponse (preview 200c) : « Aucune source disponible sur ce point.  Les sources fournies traitent de l'homologation du Plan de Sauvegarde de l'Emploi (PSE) par la DREETS et ne contiennent aucune information relative à la procédu »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### LEG-OOS-01 — **PASS** (0 ms)
- Catégorie : `out_of_scope_config`
- Règle : `oos_refusal`
- Prompt : « Comment optimiser ma déclaration de revenus avec une niche fiscale ? »
- Comportement attendu : Refus déterministe Cerveau Oiseaux, domaine fiscal détecté, latence interne < 50 ms.
- Réponse (preview 200c) : « Cette question relève du droit fiscal. Un expert-comptable ou un avocat fiscaliste sera plus pertinent. Je reste à votre disposition pour les aspects Droit Social (licenciement, contrat de travail, in »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "fiscal", "duration_ms": 0.05}`

### LEG-OOS-02 — **PASS** (0 ms)
- Catégorie : `out_of_scope_config`
- Règle : `oos_refusal`
- Prompt : « Que risque-t-on en garde à vue pour infraction pénale ? »
- Comportement attendu : Refus déterministe Cerveau Oiseaux, domaine pénal détecté, latence interne < 50 ms.
- Réponse (preview 200c) : « Cette question relève du droit pénal. Un avocat pénaliste sera plus pertinent. Je reste à votre disposition pour toute question de Droit Social. »
- `refused`=True, `early_validation_triggered`='out_of_scope'
- citations : []
- validation_details : `{"domain": "penal", "duration_ms": 0.02}`

### LEG-OOS-03 — **PASS** (3 ms)
- Catégorie : `out_of_scope_fallthrough`
- Règle : `oos_fallthrough_llm`
- Prompt : « Quelles règles s'appliquent en droit international privé pour un contrat italo-français ? »
- Comportement attendu : DIP non configuré dans out_of_scope_config.yaml — pas de refus précoce attendu, pipeline LLM observable. Voir Q-0003 (OQ-F9-02) pour décision config.
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### LEG-OOS-04 — **PASS** (0 ms)
- Catégorie : `out_of_scope_fallthrough`
- Règle : `oos_fallthrough_llm`
- Prompt : « Comment déposer un brevet d'invention à l'INPI ? »
- Comportement attendu : Brevets non configurés dans out_of_scope_config.yaml — pas de refus précoce attendu, pipeline LLM observable. Voir Q-0003 (OQ-F9-02) pour décision config.
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### LEG-ART-01 — **PASS** (0 ms)
- Catégorie : `article_invalid`
- Règle : `article_invalid`
- Prompt : « Que dit l'article L.1234-999 du Code du travail sur le préavis ? »
- Comportement attendu : Article inexistant — refus déterministe Cerveau Oiseaux <50ms via SqliteLegifranceResolver + WhitelistCtResolver.
- Réponse (preview 200c) : « L'article L.1234-999 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider  »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.1234-999"], "resolvers": ["whitelist-ct"], "duration_ms": 0.1}`

### LEG-ART-02 — **PASS** (0 ms)
- Catégorie : `article_invalid`
- Règle : `article_invalid`
- Prompt : « L.9999-1 régit-il les indemnités ? »
- Comportement attendu : Article inexistant (numéro hors plage CT) — refus déterministe <50ms.
- Réponse (preview 200c) : « L'article L.9999-1 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider si »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.9999-1"], "resolvers": ["whitelist-ct"], "duration_ms": 0.01}`

### LEG-ART-03 — **PASS** (0 ms)
- Catégorie : `article_invalid`
- Règle : `article_invalid`
- Prompt : « R.0000-1 s'applique-t-il aux contrats ? »
- Comportement attendu : Article réglementaire inexistant (numéro 0000) — la regex \d{3,4} accepte 0000, le résolveur doit le rejeter <50ms.
- Réponse (preview 200c) : « L'article R.0000-1 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider si »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["R.0000-1"], "resolvers": ["whitelist-ct"], "duration_ms": 0.01}`

### LEG-ART-04 — **PASS** (0 ms)
- Catégorie : `article_invalid`
- Règle : `article_invalid`
- Prompt : « Comment interpréter L.5555-555 ? »
- Comportement attendu : Article inexistant (numéro hors plage CT) — refus déterministe <50ms.
- Réponse (preview 200c) : « L'article L.5555-555 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider  »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.5555-555"], "resolvers": ["whitelist-ct"], "duration_ms": 0.01}`

### LEG-CITE-01 — **FAIL** (63858 ms)
- Catégorie : `citation_required`
- Règle : `citation_required`
- Prompt : « Sur quel article repose la définition du licenciement économique ? »
- Comportement attendu : Réponse in-scope citant L.1233-3 (article canonique du licenciement éco).
- Réponse (preview 200c) : « ## Réponse La définition du licenciement économique est contenue dans l'article L.1233-1 du Code du travail [L1233-1].  Cet article définit ce motif comme étant le licenciement effectué par un employe »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `answer_or_citations_normalized any_match ['L.1233-3'] → actual="##RÉPONSELADÉFINITIONDULICENCIEMENTÉCONOMIQUEESTCONTENUEDANSL'ARTICLEL12331DUCODEDUTRAVAIL[L12331]CETARTICLEDÉFINITCEMOTIFCOMMEÉTANTLELICENCIEMENTEFFECTUÉPARUNEMPLOYEURPOURUNOUPLUSIEURSMOTIFSQUINESONTPASLIÉSÀLAPERSONNEDUSALARIÉCESMOTIFSRÉSULTENTSPÉCIFIQUEMENTD'UNESUPPRESSIONOUD'UNETRANSFORMATIOND'EMPLOIOUD'UNE[L12331]##POINTSCLÉSL'ARTICLEL12331ESTL'ARTICLEDÉDIÉÀLADÉFINITIONDULICENCIEMENTÉCONOMIQUE[L12331]LEMOTIFDOITÊTRENONINHÉRENTÀLAPERSONNEDUSALARIÉETPROVENIRD'UNESUPPRESSIONOUTRANSFORMATIOND'EMPLOI[L12331]##ÀRETENIRILESTIMPORTANTDENOTERQUE,BIENQUEL12332TRAITEDESOBLIGATIONSDEL'EMPLOYEUR,C'ESTL12331QUIPOSELADÉFINITIONLÉGALEDUMOTIFÉCONOMIQUE_NOTEGÉNÉRÉEPARLUCIEV1—SCOREDEFIABILITÉ:100%—VERDICT:VALIDÉ__ÀVÉRIFIERPARUNAVOCATQUALIFIÉAVANTTOUTUSAGEPROFESSIONNEL_"`
  - `_wall_clock_ms lte 60000 → actual=63858.194207999986`

### LEG-CITE-02 — **FAIL** (26393 ms)
- Catégorie : `citation_required`
- Règle : `citation_required`
- Prompt : « Quel article fixe le préavis de licenciement ? »
- Comportement attendu : Réponse in-scope citant L.1234-1 (préavis légal).
- Réponse (preview 200c) : « Aucune source disponible sur ce point.  --- _Note générée par Lucie V1 — Score de fiabilité : 0% — Verdict : NON VÉRIFIABLE_ _À vérifier par un avocat qualifié avant tout usage professionnel._ »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `answer_or_citations_normalized any_match ['L.1234-1'] → actual='AUCUNESOURCEDISPONIBLESURCEPOINT_NOTEGÉNÉRÉEPARLUCIEV1—SCOREDEFIABILITÉ:0%—VERDICT:NONVÉRIFIABLE__ÀVÉRIFIERPARUNAVOCATQUALIFIÉAVANTTOUTUSAGEPROFESSIONNEL_'`

### LEG-CITE-03 — **FAIL** (1 ms)
- Catégorie : `citation_required`
- Règle : `citation_required`
- Prompt : « Combien de temps dure le congé maternité, article applicable ? »
- Comportement attendu : Réponse in-scope citant L.1225-17 (durée du congé maternité).
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `answer_or_citations_normalized any_match ['L.1225-17'] → actual='JEMESPÉCIALISEENDROITDULICENCIEMENTÉCONOMIQUEAVEZVOUSUNEQUESTIONSURCESUJET?'`

### LEG-CITE-04 — **FAIL** (75948 ms)
- Catégorie : `citation_required`
- Règle : `citation_required`
- Prompt : « Quelle est la procédure légale d'entretien préalable au licenciement ? »
- Comportement attendu : Réponse in-scope citant un article du jeu L.1232-2 (convocation), L.1232-3 (déroulement) ou L.1232-4 (assistance). Voir Q-0004 (OQ-F9-03) pour durcissement éventuel.
- Réponse (preview 200c) : « ## Réponse La procédure légale d'entretien préalable au licenciement se déploie en plusieurs étapes, de la convocation à la notification de la décision.  Premièrement, l'employeur qui envisage de lice »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `answer_or_citations_normalized any_match ['L.1232-2', 'L.1232-3', 'L.1232-4'] → actual="##RÉPONSELAPROCÉDURELÉGALED'ENTRETIENPRÉALABLEAULICENCIEMENTSEDÉPLOIEENPLUSIEURSÉTAPES,DELACONVOCATIONÀLANOTIFICATIONDELADÉCISIONPREMIÈREMENT,L'EMPLOYEURQUIENVISAGEDELICENCIERUNSALARIÉPOURMOTIFÉCONOMIQUEDOITLECONVOQUERÀUNENTRETIENPRÉALABLEAVANTTOUTEDÉCISION[L12336]CETTECONVOCATIONDOITÊTREEFFECTUÉESOITPARLETTRERECOMMANDÉE,SOITPARLETTREREMISEENMAINPROPRE[L12336]DEUXIÈMEMENT,AUCOURSDECETENTRETIEN,L'EMPLOYEURAL'OBLIGATIOND'INDIQUERLESMOTIFSDELADÉCISIONENVISAGÉEETDERECUEILLIRLESEXPLICATIONSDUSALARIÉ[L12337]DEPLUS,L'EMPLOYEURDOITINFORMERLESALARIÉDESMESURESPRÉVUES,LECASÉCHÉANT[L12337]ENFIN,LANOTIFICATIONDULICENCIEMENTDOITÊTREFAITEPARLETTRERECOMMANDÉEAVECAVISDERÉCEPTION[L12338]##POINTSCLÉS**CONVOCATIONOBLIGATOIRE:**L'EMPLOYEURDOITCONVOQUERLESALARIÉAVANTTOUTEDÉCISIONDELICENCIEMENT[L12336]**DÉROULEMENTDEL'ENTRETIEN:**L'EMPLOYEURDOITEXPOSERLESMOTIFSENVISAGÉSETRECUEILLIRLESEXPLICATIONSDUSALARIÉ[L12337]**NOTIFICATION:**LELICENCIEMENTDOITÊTRENOTIFIÉPARLETTRERECOMMANDÉEAVECAVISDERÉCEPTION[L12338]##ÀRETENIRLERESPECTDELASÉQUENCE(CONVOCATION$\\RIGHTARROW$ENTRETIEN$\\RIGHTARROW$NOTIFICATION)ETDESMODALITÉSDECOMMUNICATION(LETTRERECOMMANDÉE)ESTESSENTIELPOURLAVALIDITÉDELAPROCÉDURE_NOTEGÉNÉRÉEPARLUCIEV1—SCOREDEFIABILITÉ:100%—VERDICT:VALIDÉ__ÀVÉRIFIERPARUNAVOCATQUALIFIÉAVANTTOUTUSAGEPROFESSIONNEL_"`
  - `_wall_clock_ms lte 60000 → actual=75948.3614159999`

### LEG-MIX-05a — **PASS** (0 ms)
- Catégorie : `mixed_trap`
- Règle : `mixed_article_invalid_wins`
- Prompt : « Est-ce que L.1233-3 et L.9999-99 traitent tous deux du licenciement économique ? »
- Comportement attendu : Le pattern article matche → priority_override désactive OOS (sans effet ici, pas de mot-clé OOS) ; L.9999-99 inexistant → article_invalid kicke. early_validation_triggered="article_invalid".
- Réponse (preview 200c) : « L'article L.9999-99 n'existe pas dans le Code du travail. Je préfère vous le dire clairement plutôt que d'inventer un contenu.  Vouliez-vous peut-être parler d'un article proche ? Je peux vous aider s »
- `refused`=True, `early_validation_triggered`='article_invalid'
- citations : []
- validation_details : `{"codes": ["L.1233-3", "L.9999-99"], "resolvers": ["whitelist-ct"], "duration_ms": 0.11}`

### LEG-MIX-05b — **PASS** (0 ms)
- Catégorie : `mixed_trap`
- Règle : `in_scope_answers`
- Prompt : « Mon boss veut me virer du jour au lendemain, j'ai quels droits ? »
- Comportement attendu : Jargon FR familier (boss, virer) — doit être routé in-scope (mot-clé 'salarie/employeur' implicite via override) et obtenir réponse non-vide.
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### LEG-MIX-05c — **PASS** (0 ms)
- Catégorie : `mixed_trap`
- Règle : `ambiguous_default_pass`
- Prompt : « Quels sont mes droits ? »
- Comportement attendu : Question volontairement ambiguë sans contexte. Comportement attendu non spécifié — règle tolérante : PASS si réponse non-vide OU refus poli. Voir Q-0002 (OQ-F9-01) pour décision finale.
- Réponse (preview 200c) : « Je me spécialise en droit du licenciement économique. Avez-vous une question sur ce sujet ? »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`

### LEG-MIX-05d — **FAIL** (202000 ms)
- Catégorie : `mixed_trap`
- Règle : `mixed_priority_override`
- Prompt : « Quel est l'impact fiscal de l'article L.1234-9 sur l'indemnité de licenciement ? »
- Comportement attendu : Mot-clé 'fiscal' présent MAIS l'article L.1234-9 (existant) déclenche priority_override → OOS désactivé → pipeline LLM normal. early_validation_triggered != "out_of_scope".
- Réponse (preview 200c) : « Aucune source disponible sur l'impact fiscal de l'article L.1234-9 sur l'indemnité de licenciement.  Les sources fournies confirment uniquement que les dispositions relatives à l'indemnité légale de l »
- `refused`=False, `early_validation_triggered`=None
- citations : []
- validation_details : `{}`
- Assertions échouées :
  - `_wall_clock_ms lte 60000 → actual=201999.86587500008`
