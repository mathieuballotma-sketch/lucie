# `lucie_v1_standalone/privacy/` — Couche privacy Beaume

## But

Couche **modèle** du consentement utilisateur à la sync KB Légifrance
privacy-preserving (Sprint K-8, step 0). Ce module ne fait QUE :

- Définir le modèle de données (`ConsentMode`, `ConsentStatus`).
- Persister localement le choix utilisateur, atomiquement, avec permissions
  strictes (`0o600`).
- Exposer une API minimale (4 fonctions) pour lire / écrire / effacer /
  vérifier le consentement.

Aucune UI, aucun transport réseau, aucune dépendance hors stdlib.

## Les 2 modes

| Mode               | Sync KB Légifrance | Profil cible |
|--------------------|--------------------|--------------|
| `STANDARD`         | Activée            | Recommandé. Avocats qui veulent une KB à jour automatiquement (transport privacy-preserving — détails à venir step 1+). |
| `PRO_SOUVERAINETE` | Désactivée         | Avocats exigeant zéro communication réseau côté KB. KB reste statique à la version installée. |

Tant que l'utilisateur n'a **jamais** consenti (`has_consented=False`),
`sync_enabled` est forcé à `False`. Pas de sync sans consentement explicite,
jamais.

## Storage

- **Chemin** : `~/Library/Application Support/Beaume/privacy/consent.json`
  (résolu via `_get_app_support_dir()` du module `config`, qui gère la
  migration automatique Lucie → Beaume).
- **Format** : JSON, schéma versionné (`schema_version=1`).
- **Permissions** : `0o600` (lecture/écriture utilisateur uniquement).
- **Atomicité** : écriture via `tempfile.mkstemp` + `os.fsync` + `os.replace`.
  Un crash entre les étapes ne corrompt jamais le fichier existant.
- **Erreurs** : explicites et typées (`ConsentStorageError`,
  `ConsentSchemaVersionError`). Aucun fail silencieux.

## API publique

```python
from lucie_v1_standalone.privacy import (
    ConsentMode,
    ConsentStatus,
    get_consent_status,
    set_consent,
    clear_consent,
    has_user_consented,
)

status = get_consent_status()         # ConsentStatus (default si jamais consenti)
set_consent(ConsentMode.STANDARD)     # Persiste et retourne le nouveau ConsentStatus
clear_consent()                       # Efface (idempotent)
if has_user_consented():              # alias court
    ...
```

Toutes les fonctions acceptent un `storage_path: Path | None = None` optionnel
pour overrider le chemin (utile pour tests / outils dev).

## Outil dev

`scripts/test_consent_flow.py` — mini-CLI argparse pour tester les transitions
manuellement depuis le terminal :

```bash
python scripts/test_consent_flow.py --status
python scripts/test_consent_flow.py --set standard
python scripts/test_consent_flow.py --set pro_souverainete
python scripts/test_consent_flow.py --clear
```

## Tests

```bash
venv311/bin/pytest lucie_v1_standalone/privacy/tests/ -v
```

13 tests couvrent : statut par défaut, persistance des 2 modes, idempotence
de `clear_consent`, préservation de `consent_date`, mise à jour de
`last_modified`, atomicité face à un crash simulé, permissions disque,
erreurs explicites (JSON corrompu, schema mismatch, mauvais type d'argument),
immutabilité du `ConsentStatus`.

## Étapes futures K-8

- **Step 1+ : transport KB sync** — à venir, hors scope step 0. Aucune
  description anticipée ici (truth rule : on ne documente pas ce qui n'est
  pas livré).
- **Wizard W-1 carte 7** — UI de premier lancement qui appellera
  `set_consent()` avec le choix utilisateur.
- **Préférences Beaume** — écran de modification du mode après onboarding.
