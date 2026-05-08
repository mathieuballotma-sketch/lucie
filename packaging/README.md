# Packaging macOS — Beaume (ex-Lucie)

Infrastructure de packaging pour produire `Beaume.app` signée Developer ID et
notarizée Apple, distribuable aux avocats pilotes sans friction Gatekeeper.

> **Rebrand 2026-05-02** : `CFBundleName/DisplayName/Executable` passent à
> `Beaume`. Les noms de fichiers internes au répertoire `packaging/`
> (`Lucie.entitlements` etc.) sont conservés tels quels tant que les scripts
> n'ont pas été renommés — voir `KNOWN_ISSUES_REBRAND` dans le rapport
> 2026-05-07. Le bundle produit s'appellera `dist/Beaume.app` après rebuild.

---

## Commande unique

```bash
bash packaging/release.sh
```

Fait tout : build → sign → notarize → DMG. Chaque étape saute si ses
prérequis manquent, avec un message explicite.

---

## Structure

```
packaging/
├── Info.plist              # metadata bundle + usage strings TCC
├── Lucie.entitlements      # hardened runtime (JIT, network, AppleEvents…)
├── setup_py2app.py         # config py2app (entry, data_files, excludes)
├── build.sh                # py2app → dist/Lucie.app
├── sign.sh                 # codesign --deep --options runtime
├── notarize.sh             # notarytool submit + stapler staple
├── make_dmg.sh             # hdiutil + signature + notarization du DMG
├── release.sh              # orchestrateur 4 étapes
└── README.md               # ce fichier
```

Carnet de progression : `PACKAGING_PROGRESS.md` (racine repo).

---

## Prérequis

### Pour un build local (sans distribution)

- macOS 13+ (Ventura ou plus récent)
- Python 3.13 (`brew install python@3.13`)
- `py2app` installé dans le Python 3.13 cible :
  ```bash
  /opt/homebrew/bin/python3.13 -m pip install py2app
  /opt/homebrew/bin/python3.13 -m pip install -r requirements.txt
  ```

C'est tout. `bash packaging/build.sh` produit `dist/Lucie.app` utilisable en
local (non signée — Gatekeeper refuse de l'ouvrir sur un autre Mac).

### Pour signer + notarizer (distribution aux avocats)

1. **Souscrire Apple Developer Program** — 99 €/an sur
   [developer.apple.com](https://developer.apple.com/programs/).
2. **Créer un certificat Developer ID Application** :
   - Option facile : Xcode → Settings → Accounts → Manage Certificates →
     `+` → "Developer ID Application".
   - Option manuelle : developer.apple.com/account/resources/certificates.
   Installer le `.cer` dans le trousseau (double-clic).
3. **Récupérer le Team ID** : developer.apple.com/account → Membership.
   Format à 10 caractères (ex. `ABCDE12345`).
4. **Générer un app-specific password** : appleid.apple.com → Sign-In and
   Security → App-Specific Passwords → `+`. Nommer `lucie-notarize`.
   Format : `xxxx-xxxx-xxxx-xxxx`.
5. **Exporter les variables d'env** (ou les stocker dans `~/.zshrc` —
   **jamais** dans le repo) :
   ```bash
   export DEVELOPER_ID="Developer ID Application: Mathieu Ballot (ABCDE12345)"
   export APPLE_ID="mathieu.ballotma@gmail.com"
   export APPLE_TEAM_ID="ABCDE12345"
   export APPLE_APP_PWD="xxxx-xxxx-xxxx-xxxx"
   ```
6. **Lancer** : `bash packaging/release.sh`.

---

## Scripts en détail

| Script | Entrée | Sortie | Idempotent |
|---|---|---|---|
| `build.sh` | — | `dist/Lucie.app` | Oui (clean avant build) |
| `sign.sh` | `DEVELOPER_ID` | `dist/Lucie.app` signée | Oui (resign propre) |
| `notarize.sh` | `APPLE_ID` + `APPLE_TEAM_ID` + `APPLE_APP_PWD` | `Lucie.app` staplée | Oui |
| `make_dmg.sh` | tous les creds | `dist/Lucie.dmg` signé + notarizé | Oui (écrase) |
| `release.sh` | tout ce qui est dispo | fait toutes les étapes dispo | Oui |

Mode **développement** (build rapide qui pointe vers les sources, sans
copier le code dans le bundle) :

```bash
DEV=1 bash packaging/build.sh
```

---

## Arbitrages packaging v1 (2026-04-21)

### Tree-shaking agressif

Sont **exclues du bundle** : `torch`, `torchvision`, `torchaudio`,
`faster-whisper`, `onnxruntime`, `ctranslate2`, `scipy`, `sentence-transformers`,
`transformers`, `sklearn`.

**Raison** : la dictée est désactivée en v1 ; ces deps ajouteraient 3-4 GB au
bundle pour aucun bénéfice utilisateur. Cible DMG < 500 MB.

**À ré-inclure quand** : la dictée whisper est réactivée, ou le RAG vectoriel
sentence-transformers est câblé au HUD. Retirer l'entrée de
`packaging/setup_py2app.py` → `OPTIONS["excludes"]`.

### Base Légifrance hors bundle

Les ~3 GB de la DB Légifrance ne sont **pas** dans le DMG. Elle est
téléchargée au premier lancement par `scripts/legifrance_sync.py` (daemon
launchd déjà en place).

### Sandbox désactivé en v1

`com.apple.security.app-sandbox` = `false`. Simplifie le bundling Python +
deps natives. **À réévaluer** si on vise le Mac App Store en v2 (sandbox y
est obligatoire).

### Accessibility = seule TCC réellement utilisée

Le code source utilise aujourd'hui uniquement l'Accessibility (hotkey global
Cmd+Shift+L via `AXIsProcessTrusted`). Les autres usage strings
(Calendar / Reminders / Contacts / AppleEvents / Microphone / Speech) sont
**présentes dans `Info.plist` pour l'avenir** (intégrations opt-in v1+), mais
ne déclenchent aucun prompt tant que le code ne les appelle pas.

---

## Troubleshooting

### `py2app: command not found` / `ImportError: No module named py2app`

```bash
/opt/homebrew/bin/python3.13 -m pip install py2app
```

### Bundle 4 GB au lieu de <500 MB

Le tree-shaking n'a pas pris. Vérifier que `packaging/setup_py2app.py`
contient bien la liste `excludes`, et que les deps exclues ne sont pas
importées dans le chemin d'entrée. Commande de vérification :

```bash
du -sh dist/Lucie.app/Contents/Resources/lib/python3.13/ | sort -h
# regarder les plus gros sous-dossiers
```

### `codesign: Developer ID introuvable`

```bash
security find-identity -v -p codesigning
```

Doit lister au moins une ligne `"Developer ID Application: … (TEAMID)"`. Si
rien : le certif n'est pas installé dans le trousseau (cf. prérequis §2).

### `notarytool submit: Invalid credentials`

- L'app-specific password a 16 caractères `xxxx-xxxx-xxxx-xxxx`, **pas** le
  mot de passe Apple ID normal.
- Le Team ID est bien l'ID à 10 caractères, pas le Team Name.
- L'Apple ID doit être celui du **compte développeur** (membre du Program).

### `notarytool` refuse : "hardened runtime not enabled"

Le build n'a pas été signé avec `--options runtime`. Relancer `sign.sh`,
vérifier la ligne `codesign --options runtime` dedans.

### `notarytool` refuse : "library validation enabled"

L'entitlement `com.apple.security.cs.disable-library-validation` est
indispensable pour les deps Python natives (PyObjC, lxml, cryptography).
Vérifier `packaging/Lucie.entitlements`.

### `spctl refuses` après stapler OK

Attendre quelques minutes (propagation CDN Apple). Tester sur un autre Mac
avec :
```bash
xcrun stapler validate dist/Lucie.app
spctl --assess --type execute --verbose dist/Lucie.app
```

### Premier lancement : Gatekeeper dit "app endommagée"

- L'app n'est pas notarizée.
- Ou : l'utilisateur a téléchargé le DMG → quarantine attribute → staple
  indispensable (l'avocat n'a pas accès à Apple CDN forcément). Vérifier :
  ```bash
  xcrun stapler validate dist/Lucie.app
  ```

### Build prend 20+ minutes

Normal pour un premier build (py2app copie l'interpréteur Python et résout
toutes les deps). Les builds suivants sont plus rapides.

---

## Coûts

| Poste | Montant |
|---|---|
| Apple Developer Program | 99 €/an |
| App-specific password | Gratuit |
| Certificat Developer ID | Inclus dans le Program |
| Notarization Apple | Inclus (illimité pour les membres) |

---

## Sécurité

**Jamais commiter** :
- `.cer`, `.p12`, `.mobileprovision`
- Fichiers `.env.packaging`, `packaging/secrets/`
- L'app-specific password sous aucune forme

`.gitignore` couvre ces patterns. En cas de doute : `git status` avant chaque
commit.
