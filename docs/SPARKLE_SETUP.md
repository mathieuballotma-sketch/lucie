# SPARKLE_SETUP.md — Auto-update Beaume (v1 stub → v2 runtime)

Ce document explique pourquoi Sparkle n'est **pas** intégré au runtime de
Beaume 0.5.0, et comment l'activer dans un sprint v2 dédié.

## Pourquoi v1 est stub

Sparkle ([sparkle-project.org](https://sparkle-project.org/)) est un framework
ObjC mature pour les apps macOS natives (Sketch, Tower, Transmit, etc.).
**Première intégration dans un bundle py2app PyObjC = territoire non-éprouvé**.
Trois inconnues :

1. **codesign --deep** ne re-signe pas proprement les frameworks ajoutés
   après le build py2app. Il faut un script bash post-build qui copie
   `Sparkle.framework` dans `Beaume.app/Contents/Frameworks/`, le signe
   séparément avec le Developer ID, **puis** signe le bundle global.
2. **Le PyObjC bridge** pour appeler `SUUpdater.sharedUpdater()` au boot
   du HUD est faisable mais non testé. Risque de crash silencieux si le
   framework est mal lié.
3. **L'appcast XML** doit être hébergé sur une URL HTTPS stable —
   GitHub Pages branche `gh-pages` ou domaine custom `beaume.app`. Ni
   l'un ni l'autre n'est en place au 17 mai 2026.

**Décision** : Sparkle = sprint v2 dédié, après que le DMG signé+notarized
0.5.0 ait été distribué à au moins un avocat pilote sans incident.

## Préparation v1 (déjà faite dans ce sprint)

- `packaging/sparkle/appcast.xml.template` — squelette RSS avec placeholders
  `{{VERSION}}`, `{{PUB_DATE}}`, `{{DOWNLOAD_URL}}`, `{{SIGNATURE_ED25519}}`,
  `{{LENGTH_BYTES}}`, `{{RELEASE_NOTES_HTML}}`
- `packaging/sparkle/README.md` — pointeur vers ce doc
- `.gitignore` couvre `*.key`, `*.pem`, `packaging/secrets/` (clés Ed25519
  jamais commitées)

## Plan v2 — Intégration runtime (sprint à venir)

### Étape 1 — Génération des clés Ed25519

Le Sparkle SDK fournit deux binaires :
```bash
# Télécharge https://github.com/sparkle-project/Sparkle/releases (dernière stable)
# Extrait dans /tmp/sparkle/

/tmp/sparkle/bin/generate_keys

# Produit :
#   ~/Library/Application Support/Sparkle/ed25519/   ← clé privée (NE PAS commit)
#   public key affichée en stdout                    ← à coller dans Info.plist
```

Stocker la clé privée dans **1Password vault Beaume** sous l'entrée
"Sparkle Ed25519 private key (Beaume macOS)".

### Étape 2 — Embed Sparkle dans le bundle

Modifier `packaging/build.sh` pour ajouter une étape post-py2app :

```bash
# Après py2app build, avant sign.sh
SPARKLE_DIR="/tmp/sparkle"  # ou chemin commité dans packaging/sparkle/lib/
cp -R "$SPARKLE_DIR/Sparkle.framework" "dist/Beaume.app/Contents/Frameworks/"
```

Ajouter à `packaging/Info.plist` :
```xml
<key>SUFeedURL</key>
<string>https://beaume.app/appcast.xml</string>
<key>SUPublicEDKey</key>
<string>{{ED25519_PUBKEY_BASE64}}</string>
<key>SUEnableAutomaticChecks</key>
<true/>
<key>SUScheduledCheckInterval</key>
<integer>86400</integer>  <!-- 24h -->
```

### Étape 3 — Signature séparée du framework

Modifier `packaging/sign.sh` pour ajouter **avant** la signature globale :

```bash
codesign --force --options=runtime --timestamp \
    --sign "$DEVELOPER_ID" \
    "dist/Beaume.app/Contents/Frameworks/Sparkle.framework/Versions/B/Sparkle"
codesign --force --options=runtime --timestamp \
    --sign "$DEVELOPER_ID" \
    "dist/Beaume.app/Contents/Frameworks/Sparkle.framework"
```

Sandbox=false dans `Beaume.entitlements` → pas besoin de XPC helper séparé
(Sparkle peut tourner directement dans le process principal).

### Étape 4 — Appel PyObjC dans le HUD

Dans `app/ui/hud_native.py` ou `main_hud.py`, après initialisation du HUD :

```python
from objc import loadBundle  # PyObjC

# Charge Sparkle.framework depuis le bundle
sparkle_bundle = loadBundle(
    "Sparkle",
    globals(),
    bundle_path="/Applications/Beaume.app/Contents/Frameworks/Sparkle.framework",
)
SUUpdater = sparkle_bundle.SUUpdater  # type: ignore[attr-defined]
updater = SUUpdater.sharedUpdater()
updater.setAutomaticallyChecksForUpdates_(True)
updater.checkForUpdatesInBackground()
```

**Pièges** :
- Le `bundle_path` ne doit pas être hardcodé en absolu — utiliser
  `NSBundle.mainBundle().bundlePath()` + `/Contents/Frameworks/Sparkle.framework`
- Timeout 5 s sur la requête réseau (Beaume reste utilisable offline si
  appcast inaccessible)

### Étape 5 — Workflow signature DMG → appcast publié

Pour chaque release :

1. Build + sign + notarize : `make dmg-signed` (produit `dist/Beaume-X.Y.Z.dmg`)
2. Signer le DMG pour Sparkle :
   ```bash
   /tmp/sparkle/bin/sign_update dist/Beaume-X.Y.Z.dmg
   # → sortie : sparkle:edSignature="..." length=N
   ```
3. Remplir `packaging/sparkle/appcast.xml.template` avec les valeurs et
   uploader sur GitHub Pages (branche `gh-pages`) ou domaine custom.
4. Les Beaume installés vérifieront l'appcast au prochain démarrage et
   proposeront la mise à jour.

### Étape 6 — Hébergement appcast

Deux options :

**Option A : GitHub Pages** (gratuit, simple)
- Activer Pages dans Settings → Pages → Source = `gh-pages` branch
- Pousser `appcast.xml` sur cette branche
- URL : `https://<user>.github.io/<repo>/appcast.xml`

**Option B : domaine custom `beaume.app`** (à acheter via OVH/Cloudflare)
- DNS → CNAME vers GitHub Pages OU Vercel statique
- Plus pro pour les avocats (URL stable indépendante du repo)

Pour le pilote alpha juin-juillet 2026, **option A suffit** (les avocats
ne voient pas l'URL, elle vit dans Info.plist).

## Risques résiduels v2

1. Sparkle framework signature : si `codesign --deep` ne propage pas
   correctement, la notarization Apple rejette → debug via
   `codesign --verify --deep --strict --verbose=4`.
2. Premier appcast en ligne : tester avec une fausse version 0.5.1 sur un
   Mac de test avant de publier 0.6.0 réelle.
3. Rollback : si une release casse, retirer l'item de l'appcast — les
   installés à jour ne pourront pas revenir en arrière facilement (Sparkle
   ne supporte pas le downgrade).

## Références

- [Sparkle Documentation](https://sparkle-project.org/documentation/)
- [Sparkle Ed25519 signing](https://sparkle-project.org/documentation/eddsa/)
- [py2app + framework embedding](https://py2app.readthedocs.io/en/latest/recipes.html)
