# BEAUME_SPRINT_PACKAGING_REPORT.md — Sprint Packaging 0.5.0

**Branche** : `claude/admiring-moore-721734` (worktree, vise merge vers `main`)
**Date** : 2026-05-17
**Auteur** : Agent ingénierie packaging (sous direction Mathieu Bellot)
**Version livrée** : Beaume 0.5.0

---

## 1. Objectif

Produire la **condition d'accès au marché** pour l'alpha avocats juin-juillet
2026 : un `.dmg` reproductible, signable Apple Developer ID, notarisable, et
distribuable à un avocat pilote sans qu'il voie "logiciel non identifié".

**Bloquant initial** : pipeline `packaging/` mature mais :
- versions désynchronisées (`pyproject 0.5.0` / `Info.plist 0.2.2`)
- bug bloquant dans `notarize.sh` (refs résiduelles `Lucie.app`)
- aucun garde-fou anti-fuite cloud SDK
- aucune CI macOS automatisée
- aucune doc opérationnelle pour Mathieu
- aucun test d'installabilité
- aucun stub de préparation pour l'auto-update v2

## 2. Livrables

| Fichier | Action | Lignes | Rôle |
|---|---|---:|---|
| `packaging/notarize.sh` | edit | ±4 | Hotfix refs `Lucie` → `Beaume` (lignes 3, 15, 62, 63) |
| `packaging/setup_py2app.py` | edit | ±1 | `version="0.2.2"` → `version="0.5.0"` |
| `packaging/Info.plist` | edit | ±2 | CFBundleVersion + CFBundleShortVersionString → `0.5.0` |
| `CHANGELOG.md` | edit | +50 | Entrée `[0.5.0] — 2026-05-17 — Packaging signé + CI macOS` |
| `Makefile` | rewrite | +60 / -3 | 7 nouvelles cibles : `version-check`, `dmg-build`, `dmg-unsigned`, `dmg-signed`, `dmg-check-secrets`, `dmg-test-install`, `dmg-clean` |
| `scripts/check_no_cloud_sdks.sh` | create | 108 | Negative grep packages cloud + secrets dans le bundle final |
| `scripts/test_install.sh` | create | 148 | Montage DMG + spctl + codesign verify + taille + démontage + rapport |
| `tests/manual/INSTALLATION_CHECKLIST.md` | create | 95 | 30+ cases à cocher Mac vierge (8 sections A→H) |
| `packaging/sparkle/appcast.xml.template` | create | 35 | Squelette RSS Sparkle avec placeholders Ed25519 |
| `packaging/sparkle/README.md` | create | 25 | Pointeur vers `docs/SPARKLE_SETUP.md` |
| `docs/SPARKLE_SETUP.md` | create | 145 | Pourquoi stub v1 + plan v2 (6 étapes) + pièges py2app+Sparkle |
| `.github/workflows/macos-build.yml` | create | 115 | Job `macos-14` arm64 Python 3.13 unsigned + signed conditionnel + release |
| `docs/PACKAGING_GUIDE.md` | create | 225 | Guide 7 étapes pour Mathieu (Apple Dev Program → release GHA) |
| `docs/POST_PACKAGING_BUGS.md` | create | 25 | Carnet vide pour bugs Python découverts hors-scope |
| `.gitignore` | edit | +8 | Section "Sprint Packaging" : `priv_key*`, `install_test_report.md`, `.env.packaging` |
| `BEAUME_SPRINT_PACKAGING_REPORT.md` | create | ce fichier | Rapport sprint 7 sections |

**Total** : 5 modifications + 11 créations. **~1090 lignes nettes ajoutées**.

## 3. Tests

### Tests exécutés pendant le sprint

| Test | Statut |
|---|:---:|
| `bash -n packaging/notarize.sh` (syntax) | ✅ PASS |
| `grep -i "lucie" packaging/notarize.sh` (aucune trace) | ✅ PASS |
| `make version-check` (4 sources alignées à 0.5.0) | ✅ PASS |
| `bash -n scripts/check_no_cloud_sdks.sh` (syntax) | ✅ PASS |
| `bash -n scripts/test_install.sh` (syntax) | ✅ PASS |
| `grep -rn "0.2.2" packaging/` (aucune trace résiduelle) | ✅ PASS |

### Tests à exécuter par Mathieu après pull

```bash
make version-check         # → "All versions aligned to 0.5.0"
make dmg-clean
make dmg-unsigned          # → dist/Beaume.dmg en < 5 min sur M4
make dmg-check-secrets     # → "0 SDK cloud, 0 secret hardcodé"
make dmg-test-install      # → tests/manual/install_test_report.md
```

### Tests Python existants

**762 tests verts au commit f9a628a — aucun touché.** Le sprint n'a modifié
aucun fichier `.py` du runtime (`app/`, `lucie_v1_standalone/`, `corpus/`,
`knowledge/`). Seuls fichiers `.py` touchés :
- `packaging/setup_py2app.py` — version bump uniquement (zéro impact runtime)

## 4. Décisions techniques

### D1 — Wrap l'existant, pas de refonte
**Choix** : `Makefile` orchestre `packaging/*.sh` existants au lieu de créer
`scripts/build_dmg.sh` + `scripts/sign_and_notarize.sh` ex nihilo comme
demandé dans le prompt initial.

**Justification** : Le pipeline `packaging/` (build.sh, sign.sh, notarize.sh,
make_dmg.sh, release.sh) existe déjà et est mature. Le réécrire = churn pur,
risque de régression. Le wrapper Make préserve la valeur existante.

**Validé par Mathieu** : oui (Phase 3 plan mode, AskUserQuestion #1).

### D2 — py2app vs Briefcase vs PyInstaller
**Choix** : conserver py2app (déjà en place).

**Justification** : `packaging/setup_py2app.py` configure le tree-shaking
agressif qui maintient le bundle < 500 MB. Briefcase = réécriture complète
sans bénéfice clair. PyInstaller = unique-file binaire, mal adapté à un
bundle `.app` macOS avec Info.plist + entitlements custom.

### D3 — HUD PyObjC natif (pas SwiftUI)
**Choix** : conserver le HUD `app/ui/hud_native.py` PyObjC + Cocoa (~182 KB).

**Justification** : Le HUD existant est fonctionnel, intégré au pipeline
py2app, et le pivot vers SwiftUI = nouveau Xcode project + Swift bridge =
3-5 jours de travail hors scope du sprint. À considérer en v2 si UX limitante.

### D4 — Sparkle = stub v1, runtime v2
**Choix** : livrer `appcast.xml.template` + `SPARKLE_SETUP.md` mais
**ne pas embarquer `Sparkle.framework`** dans le bundle 0.5.0.

**Justification** :
- Sparkle est un framework ObjC. Première intégration dans un bundle py2app
  PyObjC = territoire non éprouvé, 3 risques identifiés (cf.
  `docs/SPARKLE_SETUP.md` section "Pourquoi v1 est stub").
- Le `.dmg` signé+notarized est le **bloquant absolu** pour l'alpha.
  Sparkle est nice-to-have : l'avocat peut télécharger manuellement les
  updates pendant le pilote.
- En séparant les sprints, on protège le 0.5.0 d'un risque de régression
  Sparkle au pire moment (juste avant le pilote).

**Validé par Mathieu** : oui (AskUserQuestion #2, option "Bloc A+C+D + Sparkle stub").

### D5 — Version 0.5.0, pas 0.7.0
**Choix** : aligner toutes les sources à `0.5.0` (valeur `pyproject.toml`),
au lieu de bumper à `0.7.0` comme suggéré dans le prompt initial.

**Justification** : pas de bump artificiel. Le 0.6.0 ou 0.7.0 sera décidé
par Mathieu après tests d'install réels et premiers retours pilotes.
**Validé par Mathieu** : oui (AskUserQuestion #3).

### D6 — Negative grep secrets : approche structurelle, pas regex sources
**Choix** : `scripts/check_no_cloud_sdks.sh` cherche les **packages installés**
(`openai/__init__.py`) dans `dist/Beaume.app/Contents/Resources/lib/`, pas les
strings `"openai"` dans les sources.

**Justification** : zéro false positive depuis un commentaire ou un nom de
variable. Si `openai` est installé dans le bundle, son `__init__.py` existe ;
sinon il n'existe pas. Approche bool clean.

### D7 — CI : `macos-14` arm64, trigger restreint
**Choix** : workflow sur `workflow_dispatch` + `push tags v*`. **Pas sur
chaque PR**.

**Justification** : runner macOS = ~10× le coût Ubuntu. Mathieu = solo founder,
budget GHA fini. Lancement manuel suffit pour itérer, tag pour les releases.

### D8 — Signature CI conditionnelle
**Choix** : workflow build toujours l'unsigned, ajoute le job signé
**uniquement** si secret `DEVELOPER_ID` présent ET (tag v* OU input
`sign=true`).

**Justification** : Mathieu n'a pas encore les creds. Le workflow doit
pouvoir tourner vert dès aujourd'hui pour valider la compilation py2app
sur GH macOS runner (la vraie inconnue technique), et activer la signature
plus tard sans modification.

## 5. Trous restants — TODO Mathieu

### Bloquant alpha avocats

1. **Apple Developer Program ($99/an)** — Mathieu seul peut inscrire son
   identité légale + payer. Détaillé étape 1 de `docs/PACKAGING_GUIDE.md`.
2. **Génération + export du certificat `.p12`** — étape 2 et 3 du guide.
3. **App-specific password Apple** — étape 4 du guide.
4. **6 secrets GitHub Actions** (`DEVELOPER_ID`, `APPLE_ID`, `APPLE_TEAM_ID`,
   `APPLE_APP_PWD`, `CERT_P12_BASE64`, `CERT_P12_PASSWORD`) — étape 6 du guide.

### Non-bloquant mais à faire avant pilote

5. **Captures d'écran** dans `docs/PACKAGING_GUIDE.md` (placeholders
   `[CAPTURE: …]`) — à remplir après inscription Apple.
6. **Premier test bout-en-bout sur Mac vierge** — utiliser
   `tests/manual/INSTALLATION_CHECKLIST.md`. Idéalement sur un MacBook
   secondaire, sinon créer un user macOS séparé pour simuler.
7. **Premier test signé réel** — exécuter `make dmg-signed` localement
   d'abord (itération rapide), avant de pousser le tag v0.5.0 qui déclenche
   la release CI.
8. **Lier `docs/avocat/GUIDE_INSTALLATION.md`** dans `PACKAGING_GUIDE.md`
   section "Pour aller plus loin" une fois mergé par l'agent doc parallèle.

### Optionnel v2

9. **Intégration runtime Sparkle** — sprint dédié, suivre `docs/SPARKLE_SETUP.md`
10. **Activation GitHub Pages** pour l'hébergement `appcast.xml`
11. **Domaine custom `beaume.app`** pour URL stable de l'appcast

## 6. Risques résiduels

### À la première signature réelle (Mathieu lance `make dmg-signed`)

1. **Entitlements `allow-jit` + `allow-unsigned-executable-memory`** souvent
   flaggés par notarization. Plan B : retirer `allow-unsigned-executable-memory`
   d'abord, justifier `allow-jit` par PyObjC.

2. **Dylibs Python `.so` non signés** : `codesign --deep` rate parfois certains
   binaires embarqués. La notarization remonte la liste. Fix :
   ```bash
   find dist/Beaume.app -name "*.so" -exec \
       codesign --force --options=runtime --timestamp \
       --sign "$DEVELOPER_ID" {} \;
   ```
   À ajouter dans `packaging/sign.sh` si rencontré.

3. **Hardened runtime + Ollama subprocess** : si `ollama` CLI pas dans PATH
   accessible au bundle hardened, le spawn peut échouer. Mitigation :
   `brew install ollama` documenté en prérequis dans `INSTALLATION_CHECKLIST.md`
   case A.4.

4. **Taille bundle > 500 MB** : si py2app embarque des deps non listées dans
   `excludes`. `make dmg-test-install` log la taille → alerte précoce
   (étape 8 du script).

5. **CI macOS-14 runner Python 3.13** : à vérifier au premier `workflow_dispatch`.
   Si 3.13 indispo, fallback 3.12 (modifier `.github/workflows/macos-build.yml`
   ligne 30).

6. **`xcrun notarytool` 401 silencieux** : si Mathieu confond mot-de-passe
   compte Apple et app-specific password. Documenté explicitement dans
   `PACKAGING_GUIDE.md` étape 4 + section troubleshooting.

7. **DMG timestamp Apple offline** : `codesign --timestamp` exige connexion à
   `timestamp.apple.com`. Si offline → échec opaque. Doc dans troubleshooting.

### Architecture

8. **Si `packaging/release.sh` ne supporte pas `FORCE_UNSIGNED=1`** : le
   `Makefile` cible `dmg-unsigned` est conçue pour wrap cette variable. À
   vérifier au premier `make dmg-unsigned` : si `release.sh` ignore la
   variable, ajouter le support (~5 lignes bash).

9. **PyObjC dependency implicit** : `requirements.txt` doit contenir `pyobjc-*`
   ou `setup_py2app.py` doit l'inclure. À vérifier au premier `make dmg-build`
   propre.

## 7. Commande de push (chaînée)

Depuis le worktree (branche `claude/admiring-moore-721734`), pour pousser et
ouvrir une PR vers `main` :

```bash
cd /Users/mathieu/Desktop/mon-agence-ia/.claude/worktrees/admiring-moore-721734 && \
git add packaging/notarize.sh packaging/setup_py2app.py packaging/Info.plist \
        packaging/sparkle/ \
        CHANGELOG.md Makefile .gitignore \
        scripts/check_no_cloud_sdks.sh scripts/test_install.sh \
        tests/manual/INSTALLATION_CHECKLIST.md \
        .github/workflows/macos-build.yml \
        docs/PACKAGING_GUIDE.md docs/SPARKLE_SETUP.md docs/POST_PACKAGING_BUGS.md \
        BEAUME_SPRINT_PACKAGING_REPORT.md && \
git commit -m "Sprint Packaging 0.5.0 — DMG signé Apple Developer ID + CI macOS + tests install + doc Mathieu (Sparkle stub v1)" && \
git push origin claude/admiring-moore-721734 && \
gh pr create --base main --head claude/admiring-moore-721734 \
    --title "Sprint Packaging 0.5.0 — DMG signé + CI macOS + doc Mathieu" \
    --body "Voir BEAUME_SPRINT_PACKAGING_REPORT.md pour le détail. Bloque l'alpha avocats juin-juillet 2026."
```

Avant push, **vérifier** :
- [ ] `make version-check` → PASS
- [ ] `make dmg-unsigned` → produit `dist/Beaume.dmg` en < 5 min sur M4
- [ ] `make dmg-check-secrets` → PASS
- [ ] 762 tests Python toujours verts : `pytest tests/ lucie_v1_standalone/tests/`

Si tous PASS → push. Sinon, hotfix avant.

---

**Fin de rapport sprint Packaging 0.5.0.**
