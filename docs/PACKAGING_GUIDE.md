# PACKAGING_GUIDE.md — Distribuer Beaume signé aux avocats

Guide pas-à-pas pour produire un `Beaume-X.Y.Z.dmg` signé Apple Developer ID
et notarisé, prêt à donner à un avocat pilote. Public visé : **Mathieu**
(solo founder, première release macOS distribuée).

**Pourquoi c'est critique** : sans signature Apple, le Mac de l'avocat affiche
"logiciel non identifié, impossible à ouvrir" et le pilote s'arrête là.
L'inscription Apple Developer Program est la condition d'accès au marché.

---

## Étape 1 — Apple Developer Program (99 €/an)

1. Ouvrir https://developer.apple.com/programs/enroll/ dans Safari
2. Cliquer **Start Your Enrollment**
3. Se connecter avec ton Apple ID `mathieu.ballotma@gmail.com` (vérification SMS)
4. Choisir **Individual** (entité légale = Mathieu Bellot, pas d'entreprise pour
   l'instant — tu pourras switcher en "Organization" plus tard quand Beaume
   sera incorporé)
5. Renseigner :
   - **Nom légal** : Mathieu Bellot (PAS "Ballotma")
   - **Adresse** : ton adresse à Moulins (03000)
   - **Numéro de téléphone** : ton mobile
6. Paiement CB → 99 € (renouvellement annuel automatique)
7. Apple envoie un email de confirmation sous 24-48 h (souvent immédiat)

> [CAPTURE: étape 6 — formulaire de paiement Apple, à compléter par Mathieu après inscription]

## Étape 2 — Générer le Developer ID Application certificate

1. Ouvrir **Xcode** (installer depuis App Store si absent, ~12 GB)
2. Menu **Xcode → Settings → Accounts**
3. Cliquer **+** → Apple ID → Login avec `mathieu.ballotma@gmail.com`
4. Sélectionner ton Team (ton nom apparaîtra) → **Manage Certificates...**
5. Cliquer **+** en bas → choisir **Developer ID Application**
6. Le certificat se génère et s'ajoute automatiquement à ton **Keychain Access**

> [CAPTURE: étape 5 — menu déroulant "+ Developer ID Application"]

## Étape 3 — Exporter le certificat en `.p12`

Pour utiliser le certificat dans GitHub Actions, il faut l'exporter en format
portable.

1. Ouvrir **Keychain Access** (Cmd+Espace → "Trousseaux d'accès")
2. Catégorie **My Certificates** (à gauche)
3. Trouver `Developer ID Application: Mathieu Bellot (TEAM_ID)`
4. Clic droit → **Export "Developer ID Application: …"**
5. Format : **Personal Information Exchange (.p12)**
6. Nom : `beaume_devid.p12` (sauvegarder dans `~/Documents/Apple Developer/`,
   PAS dans le repo)
7. Password fort (générer via 1Password) → noter ce password, tu en auras
   besoin à l'étape 6

**Sécurité** : ce `.p12` permet de signer en ton nom. Le mettre dans 1Password
vault Beaume, jamais sur un cloud non-chiffré.

> [CAPTURE: étape 4 — clic droit export, format .p12]

## Étape 4 — App-specific password pour notarytool

`xcrun notarytool` n'accepte pas le mot de passe de ton compte Apple. Il faut
un mot de passe dédié.

1. Aller sur https://appleid.apple.com → Sign-In and Security
2. Section **App-Specific Passwords** → **Generate Password...**
3. Label : `Beaume notarization`
4. Apple génère un password format `xxxx-xxxx-xxxx-xxxx` → **copier
   immédiatement** dans 1Password vault Beaume sous entrée
   "Apple app-specific password — Beaume notarization" (Apple ne le réaffichera
   pas)

## Étape 5 — Récupérer le Team ID

1. Aller sur https://developer.apple.com/account
2. Section **Membership Details**
3. Copier la valeur **Team ID** (10 chars alphanumériques, ex : `ABCDEFGHIJ`)

## Étape 6 — Configurer les variables d'env

Deux modes : local (sur ton M4) et CI (GitHub Actions).

### Mode local — pour tester un build signé sur ta machine

Créer `~/.env.packaging` (gitignored) :

```bash
# ~/.env.packaging — NE JAMAIS COMMITER
export DEVELOPER_ID="Developer ID Application: Mathieu Bellot (TEAM_ID_ICI)"
export APPLE_ID="mathieu.ballotma@gmail.com"
export APPLE_TEAM_ID="TEAM_ID_ICI"
export APPLE_APP_PWD="xxxx-xxxx-xxxx-xxxx"
```

Source ces variables avant de lancer la build :
```bash
source ~/.env.packaging
cd /Users/mathieu/Desktop/mon-agence-ia
make dmg-clean
make version-check
make dmg-signed
```

Résultat attendu en < 15 min sur M4 : `dist/Beaume.dmg` (~300-400 MB) signé +
notarized + staplé, prêt à donner à un avocat.

### Mode CI — pour automatiser via GitHub Actions

Configurer 6 secrets dans GitHub :

1. `gh secret set DEVELOPER_ID` → coller la string `Developer ID Application: Mathieu Bellot (TEAM_ID)`
2. `gh secret set APPLE_ID` → `mathieu.ballotma@gmail.com`
3. `gh secret set APPLE_TEAM_ID` → `TEAM_ID`
4. `gh secret set APPLE_APP_PWD` → app-specific password
5. `gh secret set CERT_P12_BASE64` → encoder le `.p12` :
   ```bash
   base64 -i ~/Documents/Apple\ Developer/beaume_devid.p12 | pbcopy
   gh secret set CERT_P12_BASE64
   # → coller le contenu du clipboard
   ```
6. `gh secret set CERT_P12_PASSWORD` → le password du `.p12` choisi à l'étape 3

Une fois les secrets en place, déclencher une release :

```bash
git tag v0.5.0
git push origin v0.5.0
# → workflow .github/workflows/macos-build.yml se déclenche
# → build + sign + notarize + GitHub Release créée avec Beaume.dmg attaché
```

Ou tester manuellement sans tag :

```bash
gh workflow run macos-build.yml -f sign=true
```

## Étape 7 — Distribution à l'avocat pilote

Une fois `Beaume-0.5.0.dmg` produit :

1. Calculer le SHA-256 : `shasum -a 256 dist/Beaume.dmg`
2. Uploader sur GitHub Releases (auto si CI, sinon `gh release upload v0.5.0 dist/Beaume.dmg`)
3. Donner à l'avocat :
   - **Lien direct** vers le DMG sur GitHub Releases
   - **Hash SHA-256** (à vérifier après téléchargement)
   - **Lien** vers `docs/avocat/GUIDE_INSTALLATION.md` (créé par l'agent doc parallèle)
   - **Ton numéro** pour support 1:1 pendant l'alpha

## Troubleshooting

### Notarization échoue avec "entitlements rejected"

Apple peut rejeter certains entitlements. Les plus fréquents :
- `com.apple.security.cs.allow-jit` — accepté si justification PyObjC
- `com.apple.security.cs.allow-unsigned-executable-memory` — **à retirer en premier**
  si rejet, puis re-tester

Édite `packaging/Beaume.entitlements`, relance `make dmg-signed`.

### codesign rate des dylibs `.so` Python

Si `codesign --deep` ne signe pas tous les binaires Python embarqués, la
notarization remonte une liste d'offenders. Hotfix :

```bash
find dist/Beaume.app -name "*.so" -exec \
    codesign --force --options=runtime --timestamp \
    --sign "$DEVELOPER_ID" {} \;
```

À ajouter dans `packaging/sign.sh` si rencontré régulièrement.

### `xcrun notarytool` retourne 401 Unauthorized

Tu utilises probablement ton mot de passe Apple au lieu de l'app-specific
password. Régénère sur https://appleid.apple.com (cf. étape 4).

### DMG signature timestamp offline

`codesign --timestamp` exige connexion à `timestamp.apple.com`. Si tu builds
en avion, ça échoue. Solution : retirer `--timestamp` localement pour itérer,
mais **garder `--timestamp` pour les releases publiques** (Gatekeeper le
demande au-delà de 6 mois).

### Bundle dépasse 500 MB

Vérifier `packaging/setup_py2app.py` section `excludes`. Ajouter les deps
non utilisées. Mesurer avec :
```bash
du -sh dist/Beaume.app/Contents/Resources/lib/python*/site-packages/* | sort -h | tail -20
```

## Pour aller plus loin

- **Avocat-facing doc** : `docs/avocat/GUIDE_INSTALLATION.md`
  ⚠️ TODO — créé en parallèle par l'agent doc, à lier ici une fois mergé
- **Sparkle auto-update** (v2 sprint dédié) : `docs/SPARKLE_SETUP.md`
- **Threat model packaging** : `docs/THREAT_MODEL.md`
- **Carnet de reprise interne** : `docs/progress/PACKAGING_PROGRESS.md`

---

**Version doc** : 0.5.0 — 2026-05-17
**Mainteneur** : Mathieu Bellot
