# PACKAGING_PROGRESS.md — Chantier packaging macOS Lucie

**Branche** : `chore/packaging-macos-app`
**Démarré** : 2026-04-21
**Tech lead** : Cowork
**Objectif** : livrer `Lucie.app` distribuable, signable Developer ID + notarizable, via une commande unique `bash packaging/release.sh`.

---

## Contexte

Audit archéologique du 2026-04-20 : aucune infra de packaging (pas d'`Info.plist`, pas d'`.entitlements`, pas de `CFBundleIdentifier`, aucun script `codesign`/`notarytool`). Sans ça, Gatekeeper bloque l'installation chez les avocats pilotes d'août 2026.

## Arbitrages tech lead (2026-04-21)

1. **Apple Developer account** : pas encore souscrit → build local fonctionnel + scripts prêts à l'emploi. Mathieu exécutera sign/notarize/dmg dès que son compte est actif.
2. **Tree-shaking** : agressif. Exclure `torch`, `torchvision`, `torchaudio`, `faster-whisper`, `onnxruntime`, `ctranslate2`, `scipy`, `tkinter`. Cible DMG < 500 MB.
3. **Légifrance** : téléchargée au premier lancement via le daemon launchd existant. Zéro data juridique bundlée.

## Choix du build tool : py2app

Retenu pour son alignement PyObjC natif, sa maturité sur les bundles Cocoa, et sa compatibilité directe avec `codesign --deep --options runtime`. Briefcase et PyInstaller écartés (abstraction Toga inutile / hardened runtime fragile).

---

## Phases

### ✅ Phase 1 — Carnet
- [x] `PACKAGING_PROGRESS.md` créé (ce fichier).

### ⏳ Phase 2 — Recon et choix build tool
- [x] Exploration codebase (entry point, UI framework, deps, TCC réels, données à bundler).
- [x] Décision py2app documentée dans le plan.

### ✅ Phase 3 — Implémentation
- [x] `packaging/Info.plist` (CFBundleIdentifier + 8 usage strings TCC)
- [x] `packaging/Lucie.entitlements` (hardened runtime, JIT, network, AppleEvents)
- [x] `packaging/setup_py2app.py` (tree-shaking: torch, whisper, onnxruntime exclus)
- [x] `packaging/build.sh` (idempotent, DEV=1 pour alias rapide)
- [x] `packaging/sign.sh` (valide DEV_ID + filet sécu anti-chemin-fichier)
- [x] `packaging/notarize.sh` (3 creds obligatoires + staple auto)
- [x] `packaging/make_dmg.sh` (hdiutil + sign + notarize DMG)
- [x] `packaging/release.sh` (orchestrateur 4 étapes, skip propre si creds absents)
- [x] `packaging/README.md` (prérequis, coûts, troubleshooting exhaustif)
- [x] `.gitignore` étendu (*.cer, *.mobileprovision, packaging/secrets/, .env.packaging)

### ✅ Phase 4 — Test
- [x] `bash -n` sur les 5 scripts : syntaxe OK
- [x] `plutil -lint` Info.plist : OK
- [x] `plutil -lint` Lucie.entitlements : OK
- [x] Dry-run `sign.sh` sans args → échec explicite avec instructions ✅
- [x] Dry-run `sign.sh` avec chemin de fichier (p12) → filet de sécurité déclenché ✅
- [x] Dry-run `notarize.sh` sans env → liste exacte des 3 vars manquantes ✅
- [x] **Premier build py2app effectif (mode alias, DEV=1)** :
  - `dist/Lucie.app` produit (232 KB en alias)
  - Mach-O universal `x86_64 arm64` (compatible Intel + Apple Silicon)
  - `CFBundleIdentifier=com.mon-agence-ia.lucie` confirmé
  - Toutes les usage strings TCC embarquées
  - Signature adhoc par py2app (sera remplacée par Developer ID au sign.sh)
- [ ] Build standalone complet (non testé : ~10-20 min, lancé par Mathieu)
- [ ] `open dist/Lucie.app` — non lancé dans cette session (à faire Mathieu sur son Mac)

### ⏳ Phase 5 — Merge main
- [ ] Branche `chore/packaging-macos-app`
- [ ] Commit
- [ ] Merge `--no-ff`
- [ ] Tag `v0.2.2-packaging`

### ⏳ Phase 6 — Rapport
- [ ] `~/Documents/Lucie/01_Produit/Packaging_Rapport_2026-04-21.md`

---

## Journal d'exécution

### 2026-04-21 — Démarrage
- Exploration complète : entry point = `main_hud.py`, UI = PyObjC 12.1 pur, Python 3.13.
- Découverte : `requirements.txt` pinne 170+ PyObjC framework bindings + torch 2.10.0 + faster-whisper + onnxruntime + ctranslate2. Bundle brut potentiel = 4-5 GB → tree-shaking indispensable.
- Confirmation audit : aucun artefact de packaging préexistant dans le repo.
- Plan validé par le tech lead avec les 3 arbitrages ci-dessus.

### 2026-04-21 — Implémentation phase 3 + test phase 4
- 9 fichiers créés dans `packaging/` + carnet + extension `.gitignore`.
- Toolchain disponible : Python 3.13.12 (framework), py2app 0.28.10.
- Build alias (`DEV=1 bash packaging/build.sh`) passe en ~5 s.
- Bundle produit : `dist/Lucie.app`, 232 KB en alias, Mach-O universel.
- Dry-runs des 3 scripts protégés (sign, notarize, release) : tous échouent avec messages explicites quand les creds manquent.
- Non testé : build standalone complet (nécessite 10-20 min + `pip install -r requirements.txt` complet) + `open Lucie.app` (nécessite un Mac de dev propre, lancement HUD). À lancer par Mathieu sur sa machine.
