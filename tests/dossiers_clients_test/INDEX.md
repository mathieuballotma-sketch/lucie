# INDEX — Dossiers Clients de Test pour Lucie (Assistant Juridique IA)

> **Objectif** : Tester le pipeline complet de Lucie (Router 3 niveaux, analyse de dossier, recherche juridique, synthèse) sur 4 cas réalistes en droit social français.
>
> **Date de création** : 13 avril 2026

---

## Vue d'ensemble

| # | Dossier | Thème | Complexité | Irrégularité principale |
|---|---------|-------|------------|------------------------|
| 1 | MARTIN Sophie | Licenciement économique | ★★★★ | Absence de PSE obligatoire |
| 2 | DUBOIS Marc | Salarié protégé | ★★★★★ | Licenciement malgré refus de l'inspection du travail |
| 3 | PETIT Claire | Rupture conventionnelle viciée | ★★★ | Vice du consentement + indemnité insuffisante |
| 4 | ROUSSEAU Thomas | Harcèlement moral | ★★★★ | Manquement à l'obligation de sécurité |

---

## Dossier 1 — Licenciement économique : MARTIN Sophie

**Répertoire** : `01_licenciement_eco_MARTIN/`

### Résumé du cas

Sophie MARTIN, 47 ans, Responsable Marketing Digital chez SAS TECHNOVA INDUSTRIES (280 salariés) depuis 12 ans (CDI du 02/09/2012), cadre Syntec, 4 200 € brut/mois. Licenciée pour motif économique le 15/01/2026 dans le cadre d'une restructuration. L'entreprise a supprimé 14 postes sans mettre en place de PSE (Plan de Sauvegarde de l'Emploi), alors que celui-ci est obligatoire dès 10 licenciements dans une entreprise de 50+ salariés (art. L.1233-61 C. trav.).

### Fichiers du dossier

| Fichier | Description |
|---------|-------------|
| `01_contrat_travail_cdi.txt` | CDI du 02/09/2012, cadre coefficient 350, convention Syntec |
| `02_bulletins_salaire.txt` | 3 bulletins (oct., nov., déc. 2025), salaire brut 4 200 € |
| `03_convocation_entretien_prealable.txt` | Convocation du 18/12/2025, entretien le 02/01/2026 |
| `04_lettre_licenciement_economique.txt` | Lettre du 15/01/2026, motif restructuration |
| `05_pv_cse_restructuration.txt` | PV du CSE extraordinaire du 10/12/2025 |
| `06_mail_cliente.txt` | Mail de Sophie à son avocat du 20/01/2026 |
| `07_note_analyse_preliminaire.txt` | Note d'analyse interne du cabinet |

### Points juridiques à vérifier par Lucie

1. **Absence de PSE** : 14 suppressions de postes dans une entreprise de 280 salariés → PSE obligatoire (L.1233-61 C. trav.) → non respecté
2. **Insuffisance du motif économique** : La baisse de CA de 22 % et les pertes de 1,8 M€ sont-elles suffisantes pour justifier la suppression de ce poste précis ?
3. **Non-respect des critères d'ordre des licenciements** (L.1233-5 C. trav.) : aucune mention dans la lettre
4. **Obligation de reclassement** (L.1233-4 C. trav.) : aucune proposition concrète faite à la salariée
5. **Consultation du CSE** : le CSE a rendu un avis défavorable, la direction a éludé la question du PSE

### Questions à poser à Lucie pour tester

| Question | Réponse attendue |
|----------|-----------------|
| « Quels sont les vices de procédure dans ce licenciement ? » | Identification de l'absence de PSE comme vice majeur, mention du non-respect des critères d'ordre et de l'obligation de reclassement insuffisante |
| « Ce licenciement est-il nul ou simplement sans cause réelle et sérieuse ? » | **Nul** — l'absence de PSE entraîne la nullité de la procédure et de tous les licenciements prononcés (Cass. soc., 13 février 1997, n° 96-41.874) |
| « Quelles indemnités peut réclamer Mme MARTIN ? » | Réintégration ou indemnité minimale de 12 mois de salaire (nullité), + indemnité de licenciement conventionnelle (~21 000 €), + indemnité compensatrice de préavis (3 mois = 12 600 €), + dommages-intérêts |
| « L'entreprise aurait-elle pu éviter le PSE ? » | Non — dès lors que 10+ licenciements économiques sont envisagés sur 30 jours dans une entreprise de 50+ salariés, le PSE est obligatoire. Pas de contournement possible. |
| « Quel est le délai pour agir ? » | 12 mois à compter de la notification du licenciement (L.1471-1 C. trav.) → jusqu'au 15/01/2027 |

---

## Dossier 2 — Salarié protégé : DUBOIS Marc

**Répertoire** : `02_salarie_protege_DUBOIS/`

### Résumé du cas

Marc DUBOIS, 43 ans, Technicien de chantier chez SARL BATIPRO CONSTRUCTION depuis 8 ans (CDI du 15/03/2018), délégué syndical CGT et élu CSE. Licencié pour faute grave (insubordination) le 20/02/2026. Problème majeur : l'inspection du travail avait **refusé** l'autorisation de licenciement le 10/02/2026 (faits insuffisamment établis, suspicion de lien avec l'exercice du mandat). L'employeur a licencié quand même → **licenciement nul** de plein droit.

### Fichiers du dossier

| Fichier | Description |
|---------|-------------|
| `01_contrat_travail_cdi.txt` | CDI du 15/03/2018, technicien chantier, convention BTP |
| `02_pv_election_cse.txt` | PV d'élection CSE du 14/03/2023 + désignation DS CGT |
| `03_courrier_inspection_travail.txt` | Demande d'autorisation de licenciement du 25/01/2026 |
| `04_decision_inspection_travail.txt` | Décision de refus de l'inspecteur du 10/02/2026 |
| `05_lettre_licenciement_faute_grave.txt` | Lettre de licenciement du 20/02/2026 (illégale) |
| `06_convocation_entretien_prealable.txt` | Convocation du 22/01/2026, mise à pied conservatoire |
| `07_mail_client.txt` | Mail paniqué de Marc du 22/02/2026 |

### Points juridiques à vérifier par Lucie

1. **Statut protecteur** : Marc cumule deux protections (élu CSE + délégué syndical CGT) → autorisation de l'inspection du travail obligatoire (L.2411-1 et L.2411-3 C. trav.)
2. **Refus d'autorisation** : l'inspecteur a motivé son refus (faits non établis + suspicion de lien avec le mandat)
3. **Licenciement malgré le refus** : constitue un **licenciement nul** de plein droit, sans que le juge ait besoin d'examiner le fond
4. **Droit à réintégration** : le salarié protégé licencié sans autorisation a droit à sa réintégration (L.2422-1 C. trav.)
5. **Indemnité d'éviction** : salaires dus entre le licenciement et la réintégration effective
6. **Volet pénal** : délit d'entrave (L.2431-1 C. trav.) → sanctions pénales possibles

### Questions à poser à Lucie pour tester

| Question | Réponse attendue |
|----------|-----------------|
| « Ce licenciement est-il valable ? » | **Non, il est nul de plein droit.** Le licenciement d'un salarié protégé sans autorisation administrative (ou malgré un refus) est nul. |
| « Marc a-t-il un double statut protecteur ? » | Oui — élu CSE (L.2411-1) ET délégué syndical (L.2411-3). Chaque mandat confère une protection autonome. |
| « Quels sont les recours de Marc ? » | 1) Saisir le CPH en référé pour réintégration immédiate ; 2) Action au fond pour nullité + indemnité d'éviction ; 3) Plainte pénale pour délit d'entrave |
| « L'employeur peut-il contester le refus de l'inspection ? » | Oui, par recours hiérarchique devant le ministre du Travail ou recours contentieux devant le tribunal administratif dans les 2 mois. Mais en attendant, il ne peut PAS licencier. |
| « Combien peut obtenir Marc ? » | Réintégration + salaires perdus depuis le licenciement (indemnité d'éviction) OU, s'il ne souhaite pas réintégrer : indemnité minimale de 6 mois (L.1235-3-1) + indemnité de licenciement + préavis + dommages-intérêts pour violation du statut protecteur |

---

## Dossier 3 — Rupture conventionnelle viciée : PETIT Claire

**Répertoire** : `03_rupture_conventionnelle_PETIT/`

### Résumé du cas

Claire PETIT, 35 ans, Assistante juridique au sein du SAS CABINET JURIDIS CONSEIL depuis 5 ans (CDI du 01/09/2021), 2 400 € brut/mois. A signé une rupture conventionnelle le 05/12/2025 sous la pression de son employeur (menaces de procédure disciplinaire). Elle était en état anxio-dépressif au moment de la signature. De plus, l'indemnité proposée (2 000 €) est inférieure au minimum légal (~3 000 €). Double vice : consentement vicié + indemnité insuffisante.

### Fichiers du dossier

| Fichier | Description |
|---------|-------------|
| `01_contrat_travail_cdi.txt` | CDI du 01/09/2021, convention cabinets d'avocats |
| `02_convention_rupture_conventionnelle.txt` | Convention signée le 05/12/2025, indemnité 2 000 € |
| `03_echanges_mails_pression.txt` | Échanges mails montrant la pression de l'employeur |
| `04_certificat_medical.txt` | Certificats médicaux (état anxio-dépressif) |
| `05_attestation_collegue.txt` | Attestation de Nathalie FOURNIER (témoin) |
| `06_mail_cliente.txt` | Mail de Claire à son avocat du 18/01/2026 |

### Points juridiques à vérifier par Lucie

1. **Vice du consentement** (art. 1130 à 1143 C. civ.) : pression morale, menaces → violence morale viciant le consentement
2. **État de santé au moment de la signature** : anxio-dépressif sous traitement → capacité de consentement altérée
3. **Indemnité insuffisante** : 2 000 € vs minimum légal de 1/4 de mois par année d'ancienneté = (2 400 / 4) × 5 = 3 000 € → convention nulle pour non-respect de L.1237-13 C. trav.
4. **Droit de rétractation** : Claire a tenté de se rétracter dans le délai de 15 jours mais l'employeur l'a repoussée → à vérifier si la rétractation était bien dans les délais
5. **Homologation DREETS** : si l'indemnité est en dessous du minimum, la DREETS aurait dû refuser l'homologation

### Questions à poser à Lucie pour tester

| Question | Réponse attendue |
|----------|-----------------|
| « Cette rupture conventionnelle est-elle valable ? » | **Non** — elle est entachée d'un vice du consentement (pression + état de santé) ET l'indemnité est inférieure au minimum légal. Deux motifs de nullité indépendants. |
| « Quelle est la conséquence de la nullité ? » | La rupture conventionnelle nulle produit les effets d'un **licenciement sans cause réelle et sérieuse** (Cass. soc., 30 janvier 2013, n° 11-22.332) |
| « L'indemnité de rupture est-elle conforme ? » | Non — pour 5 ans d'ancienneté à 2 400 € brut, le minimum légal est de 3 000 € (1/4 de mois × 5 ans). L'indemnité de 2 000 € est insuffisante de 1 000 €. |
| « Les mails de pression sont-ils suffisants pour prouver le vice du consentement ? » | Oui — les mails montrant des menaces explicites de procédure disciplinaire constituent des violences morales (art. 1140 C. civ.). Combinés au certificat médical et à l'attestation du collègue, le faisceau de preuves est solide. |
| « Claire peut-elle encore agir ? » | Oui — prescription de 12 mois à compter de l'homologation (L.1237-14 C. trav.). L'homologation date de début janvier 2026 → elle a jusqu'à début janvier 2027. |

---

## Dossier 4 — Harcèlement moral : ROUSSEAU Thomas

**Répertoire** : `04_harcelement_moral_ROUSSEAU/`

### Résumé du cas

Thomas ROUSSEAU, 40 ans, Responsable logistique chez SA LOGISTIQUE EXPRESS OUEST depuis 7 ans (CDI du 10/06/2019), cadre, 3 500 € brut/mois. Victime de harcèlement moral de la part de son supérieur Vincent LEMAIRE depuis mars 2025 (après avoir refusé de falsifier des rapports de livraison). Le harcèlement se manifeste par : remarques dégradantes, mise à l'écart, surcharge de travail, humiliations publiques. Thomas a signalé les faits à la DRH le 01/09/2025. L'employeur n'a pris aucune mesure efficace → manquement à l'obligation de sécurité (L.4121-1 C. trav.). Thomas est en arrêt maladie pour burn-out depuis le 15/11/2025.

### Fichiers du dossier

| Fichier | Description |
|---------|-------------|
| `01_lettre_plainte_employeur.txt` | Lettre de plainte à la DRH du 01/09/2025 (LRAR) |
| `02_mails_harcelement.txt` | 5 mails/messages montrant le harcèlement (mars-nov. 2025) |
| `03_certificat_medical.txt` | Certificats médecin du travail + médecin traitant (burn-out) |
| `04_attestation_collegue_1.txt` | Attestation Julien BERNARD (collègue en poste) |
| `05_attestation_collegue_2.txt` | Attestation Sandrine LEROY (ex-collègue partie) |
| `06_reponse_employeur.txt` | Réponse DRH du 15/09/2025 (minimisante) |
| `07_depot_main_courante.txt` | Main courante du 20/11/2025 |

### Points juridiques à vérifier par Lucie

1. **Caractérisation du harcèlement moral** (L.1152-1 C. trav.) : agissements répétés ayant pour objet ou effet une dégradation des conditions de travail portant atteinte aux droits, à la dignité, à la santé
2. **Charge de la preuve aménagée** (L.1154-1 C. trav.) : le salarié doit présenter des éléments laissant supposer le harcèlement → l'employeur doit prouver que les agissements sont justifiés par des éléments objectifs
3. **Obligation de sécurité de l'employeur** (L.4121-1 C. trav.) : l'employeur doit prévenir le harcèlement et y mettre fin → ici, enquête bâclée et aucune mesure concrète
4. **Manquement de l'employeur** : la réponse de la DRH est insuffisante (enquête vague, conclusions hâtives, aucune mesure de protection)
5. **Faisceau de preuves** : mails, attestations, certificats médicaux, main courante → faisceau concordant
6. **Prise d'acte ou résiliation judiciaire** : Thomas pourrait prendre acte de la rupture du contrat aux torts de l'employeur ou demander la résiliation judiciaire

### Questions à poser à Lucie pour tester

| Question | Réponse attendue |
|----------|-----------------|
| « Les éléments du dossier sont-ils suffisants pour caractériser un harcèlement moral ? » | Oui — le faisceau est solide : 5 mails démontrant des agissements répétés, 2 attestations concordantes, certificats médicaux établissant le lien avec le travail, main courante, signalement resté sans suite. La charge de la preuve sera renversée vers l'employeur. |
| « L'employeur a-t-il manqué à son obligation de sécurité ? » | **Oui** — l'employeur a été alerté formellement le 01/09/2025 et n'a pris aucune mesure efficace. L'enquête interne est manifestement insuffisante (aucun détail, conclusions hâtives). Violation de L.4121-1 et L.1152-4 C. trav. |
| « Quelles actions Thomas peut-il engager ? » | 1) Prise d'acte ou résiliation judiciaire du contrat ; 2) Action en réparation du préjudice moral ; 3) Reconnaissance en maladie professionnelle (burn-out) ; 4) Action pénale pour harcèlement moral (222-33-2 C. pénal, 2 ans + 30 000 €) |
| « Quel est le rôle de la main courante dans le dossier ? » | Elle constitue un élément de preuve supplémentaire datant les faits et démontrant la démarche de la victime. Ce n'est pas une plainte mais elle a valeur probante dans le faisceau d'indices. |
| « L'employeur peut-il invoquer le "simple différend managérial" ? » | Difficilement — la jurisprudence distingue le pouvoir de direction (légitime) du harcèlement moral (illégitime). Ici, les agissements dépassent largement le cadre managérial : humiliations publiques, mise à l'écart, surcharge délibérée, menaces. Le faisceau de preuves contredit la thèse du différend managérial. |

---

## Guide de test — Scénarios de bout en bout

### Test du Router (classification des demandes)

| Requête utilisateur simulée | Niveau attendu | Justification |
|----------------------------|----------------|---------------|
| « Quel est le délai de prescription pour le dossier MARTIN ? » | Niveau 1 (Question simple) | Question factuelle, réponse directe |
| « Analysez le dossier DUBOIS et identifiez les irrégularités » | Niveau 3 (Analyse complète) | Analyse de dossier multi-documents |
| « L'indemnité de rupture conventionnelle de Mme PETIT est-elle conforme ? » | Niveau 2 (Recherche ciblée) | Calcul + vérification légale |
| « Rédigez des conclusions pour le dossier ROUSSEAU » | Niveau 3 (Analyse complète) | Rédaction juridique complexe |

### Test de la recherche juridique

Pour chaque dossier, vérifier que Lucie identifie correctement :

- Les **articles du Code du travail** applicables
- La **jurisprudence** pertinente
- Les **conventions collectives** en jeu
- Les **délais de prescription**
- Les **juridictions compétentes**

### Test de la synthèse

Demander à Lucie de produire pour chaque dossier :

- Une **fiche de synthèse** (résumé des faits, qualification juridique, moyens, chances de succès)
- Une **stratégie contentieuse** (juridiction, demandes, chiffrage)
- Un **calendrier procédural** (délais, étapes clés)

---

## Cohérence des données

### Dates clés par dossier

| Dossier | Chronologie |
|---------|-------------|
| MARTIN | CDI 09/2012 → CSE 12/2025 → Convocation 18/12/2025 → Entretien 02/01/2026 → Licenciement 15/01/2026 |
| DUBOIS | CDI 03/2018 → Élection CSE 03/2023 → Incident 15/01/2026 → Mise à pied 16/01/2026 → Convocation 22/01/2026 → Demande IT 25/01/2026 → Entretien 30/01/2026 → Refus IT 10/02/2026 → Licenciement 20/02/2026 |
| PETIT | CDI 09/2021 → Pressions 11/2025 → Certificat médical 25/11/2025 → Entretien RC 28/11/2025 → Signature RC 05/12/2025 → Fin rétractation 20/12/2025 → Rupture effective 15/01/2026 |
| ROUSSEAU | CDI 06/2019 → Début harcèlement 03/2025 → Plainte DRH 01/09/2025 → Réponse DRH 15/09/2025 → Arrêt maladie 15/11/2025 → Main courante 20/11/2025 |

### Montants clés

| Dossier | Salaire brut | Ancienneté | Indemnité légale minimale |
|---------|-------------|------------|--------------------------|
| MARTIN | 4 200 € | ~13 ans | ~14 350 € (légal) ou ~21 000 € (Syntec) |
| DUBOIS | 2 800 € | ~8 ans | ~5 600 € |
| PETIT | 2 400 € | ~5 ans | ~3 000 € |
| ROUSSEAU | 3 500 € | ~7 ans | ~7 000 € |
