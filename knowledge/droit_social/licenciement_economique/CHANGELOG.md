# CHANGELOG — Base curatée licenciement économique

## [1.1.0] — 2026-05-13

### Ajouté

Sprint 6 P3 — extension Contrat de sécurisation professionnelle (CSP) pour couvrir SW-LECO-010 (« Qu'est-ce que le CSP et qui peut en bénéficier ? »).

- **L.1233-65** (objet du CSP — parcours retour à l'emploi, prébilan, formation)
  - LEGIARTI000024422267 — version en vigueur depuis 2011-07-30
  - https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000024422267
- **L.1233-66** (obligation de proposition par l'employeur — entreprises <1000 salariés)
  - LEGIARTI000031013988 — version en vigueur depuis 2015-08-08
  - https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000031013988
- **L.1233-67** (effets de l'adhésion : rupture, prescription 12 mois, indemnités)
  - LEGIARTI000031014016 — version en vigueur depuis 2015-08-08
  - https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000031014016
- **L.1233-68** (accord agréé fixant les modalités opérationnelles)
  - LEGIARTI000037388640 — version en vigueur depuis 2019-01-01
  - https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000037388640

Textes officiels copiés verbatim depuis la base SQLite Légifrance locale (état `VIGUEUR`). Hash SHA-256 disponibles dans le rapport privé Sprint 6 P3.

### Modifié

- `index.json` : version 1.0.0 → 1.1.0 ; `last_updated` 2026-04-12 → 2026-05-13 ; ajout des 4 entrées CSP après L1233-16.
- `README.md` : tableau d'articles étendu, section CSP ajoutée.

## [1.0.0] — 2026-04-12

### Ajouté

- 16 articles L.1233-1 à L.1233-16 du Code du travail
- index.json avec métadonnées et mots-clés pour chaque article
- README.md décrivant la base et son usage
- CHANGELOG.md (ce fichier)

### Périmètre V1

Articles couverts :
- **Fondation** : L.1233-1 (définition), L.1233-3 (motifs détaillés)
- **Obligations employeur** : L.1233-2 (adaptation/reclassement), L.1233-4 (ordre des licenciements), L.1233-5 (reclassement préalable)
- **Procédure individuelle** : L.1233-6 (convocation), L.1233-7 (entretien), L.1233-8 (notification), L.1233-9 (motif dans lettre)
- **Post-licenciement** : L.1233-10 (priorité réembauche), L.1233-16 (indemnités)
- **Procédure collective** : L.1233-11 (CSE petits licenciements), L.1233-12 (CSE grands licenciements)
- **PSE** : L.1233-13 (seuils), L.1233-14 (contenu), L.1233-15 (homologation DREETS)

### Notes

Base initiale pour le démo Lucie V1 (objectif : août 2026). Extension prévue en V2 :
- Articles L.1233-17 à L.1233-70 (CSP, congé de reclassement, PSE avancé)
- Jurisprudence Cour de cassation
- Conventions collectives de branche
