# packaging/sparkle/

Stub Sparkle v1 — auto-update Beaume.

**État actuel (Sprint 0.5.0)** : préparation only.
- `appcast.xml.template` — squelette RSS pour publier les versions
- Pas d'intégration runtime dans `Beaume.app` (cf. `docs/SPARKLE_SETUP.md`
  pour le pourquoi et le plan v2)

**Fichiers attendus en v2 (intégration complète)** :
- `Sparkle.framework/` — bundle ObjC à copier dans
  `Beaume.app/Contents/Frameworks/` (téléchargé depuis sparkle-project.org,
  pas commité car ~10 MB)
- `pub_key.pem` — clé publique Ed25519 (commitée, sera embedée dans `Info.plist`)
- `priv_key.pem` — clé privée Ed25519 (**JAMAIS** commitée, stockée hors repo)

**Sécurité** :
- `.gitignore` racine couvre `*.key`, `*.pem`, `packaging/secrets/`
- Le `priv_key.pem` doit vivre dans un vault sécurisé (1Password Beaume vault)

**Lectures liées** :
- `docs/SPARKLE_SETUP.md` — guide complet de génération clés + workflow signature
- `docs/PACKAGING_GUIDE.md` — guide release (Apple Developer Program)
