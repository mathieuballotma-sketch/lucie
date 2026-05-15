"""Consent flow Beaume — Sprint K-8 step 0 (data model + storage local).

Ce module est la **couche modèle** du consentement utilisateur à la sync KB
Légifrance privacy-preserving. Il ne fait QUE :

  - Définir le modèle de données (`ConsentMode`, `ConsentStatus`).
  - Persister localement le choix utilisateur (`~/Library/Application
    Support/Beaume/privacy/consent.json`) de manière atomique et avec des
    permissions strictes (0o600).
  - Exposer une API minimale (4 fonctions) pour lire / écrire / effacer /
    vérifier le consentement.

Il ne touche PAS à la UI, PAS au transport P2P, PAS au réseau. Aucune
dépendance hors stdlib. Tout fonctionne offline.

Invariants Beaume respectés :
  - 100% local : aucun appel réseau, aucune télémétrie.
  - Truth rule : pas d'inférence silencieuse, erreurs explicites typées.
  - Transparence : chaque transition est loguée (jalon `logger.info`).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

# ─── Constantes module-level ─────────────────────────────────────────────────
SCHEMA_VERSION = 1
_CONSENT_FILENAME = "consent.json"
_PRIVACY_SUBDIR = "privacy"
_FILE_PERMISSIONS = 0o600
_TMP_PREFIX = ".consent_"
_TMP_SUFFIX = ".tmp"

logger = logging.getLogger(__name__)


# ─── Modèle de données ───────────────────────────────────────────────────────
class ConsentMode(str, Enum):
    """Modes de consentement utilisateur.

    STANDARD          : sync KB activée (recommandé pour la majorité des avocats).
    PRO_SOUVERAINETE  : sync KB désactivée, KB reste statique. Pour utilisateurs
                        exigeant zéro communication réseau côté KB.
    """

    STANDARD = "standard"
    PRO_SOUVERAINETE = "pro_souverainete"


@dataclass(frozen=True)
class ConsentStatus:
    """État du consentement utilisateur à un instant T.

    `frozen=True` : immuable après lecture pour éviter toute mutation
    accidentelle entre `get_consent_status()` et un consommateur en aval.
    """

    has_consented: bool
    mode: ConsentMode
    sync_enabled: bool
    consent_date: datetime | None
    last_modified: datetime | None


# ─── Erreurs typées (jamais d'exception nue avalée) ──────────────────────────
class ConsentStorageError(RuntimeError):
    """Erreur de persistance ou de lecture du fichier consent."""


class ConsentSchemaVersionError(ConsentStorageError):
    """Le fichier consent existe mais avec une version de schéma inconnue."""


# ─── Helpers privés ──────────────────────────────────────────────────────────
def _resolve_storage_path(override: Path | None) -> Path:
    """Détermine le chemin du fichier consent.

    Si `override` est fourni (cas tests / CLI dev), on l'utilise tel quel.
    Sinon on délègue à `_get_app_support_dir()` du module config Beaume,
    qui gère la migration automatique Lucie → Beaume (rebrand 2026-05-02).

    Import paresseux pour éviter tout cycle d'import si `lucie_v1_standalone`
    n'est pas chargé au moment de l'utilisation (cas script standalone).
    """
    if override is not None:
        return override
    from lucie_v1_standalone.config import _get_app_support_dir

    return _get_app_support_dir() / _PRIVACY_SUBDIR / _CONSENT_FILENAME


def _sync_enabled_for(mode: ConsentMode) -> bool:
    """Déduit `sync_enabled` du mode. Stocké explicitement pour audit."""
    return mode is ConsentMode.STANDARD


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_dt(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse_dt(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as err:
        raise ConsentStorageError(
            f"Date ISO 8601 invalide dans consent.json: {raw!r}"
        ) from err


def _default_status() -> ConsentStatus:
    """Statut par défaut quand aucun fichier n'existe.

    `sync_enabled=False` tant que `has_consented=False` : pas de sync sans
    consentement explicite, jamais.
    """
    return ConsentStatus(
        has_consented=False,
        mode=ConsentMode.STANDARD,
        sync_enabled=False,
        consent_date=None,
        last_modified=None,
    )


def _atomic_write(path: Path, payload: dict) -> None:
    """Écriture atomique : write → fsync → chmod → rename.

    Garantit qu'un crash entre les étapes ne laisse JAMAIS un fichier consent
    partiellement écrit. Si le rename échoue, on nettoie le tmp pour ne pas
    polluer le dossier privacy.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=_TMP_PREFIX, suffix=_TMP_SUFFIX
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_name, _FILE_PERMISSIONS)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _load_payload(path: Path) -> dict:
    """Lit et valide le payload JSON du fichier consent.

    Erreurs explicites : JSON invalide → ConsentStorageError, version
    inconnue → ConsentSchemaVersionError. Aucune récupération silencieuse.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as err:
        raise ConsentStorageError(
            f"Lecture impossible du fichier consent: {path}"
        ) from err

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as err:
        raise ConsentStorageError(
            f"Fichier consent corrompu (JSON invalide): {path}"
        ) from err

    if not isinstance(payload, dict):
        raise ConsentStorageError(
            f"Fichier consent invalide (racine non-objet): {path}"
        )

    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ConsentSchemaVersionError(
            f"Schema consent inconnu: attendu {SCHEMA_VERSION}, trouvé {version!r}"
        )
    return payload


# ─── API publique ────────────────────────────────────────────────────────────
def get_consent_status(storage_path: Path | None = None) -> ConsentStatus:
    """Lit le statut consent depuis le disque.

    Si le fichier n'existe pas → retourne le statut par défaut (jamais
    consenti, mode STANDARD proposé, sync désactivée tant que pas de
    consentement explicite).
    """
    path = _resolve_storage_path(storage_path)
    logger.debug("Consent storage path resolved: %s", path)

    if not path.exists():
        return _default_status()

    payload = _load_payload(path)

    try:
        mode = ConsentMode(payload["mode"])
    except (KeyError, ValueError) as err:
        raise ConsentStorageError(
            f"Champ `mode` manquant ou invalide dans {path}"
        ) from err

    return ConsentStatus(
        has_consented=bool(payload.get("has_consented", False)),
        mode=mode,
        sync_enabled=bool(payload.get("sync_enabled", _sync_enabled_for(mode))),
        consent_date=_parse_dt(payload.get("consent_date")),
        last_modified=_parse_dt(payload.get("last_modified")),
    )


def set_consent(
    mode: ConsentMode, storage_path: Path | None = None
) -> ConsentStatus:
    """Enregistre un choix de consentement.

    Préserve `consent_date` initial s'il existe déjà (l'utilisateur a déjà
    consenti une fois ; un changement de mode n'efface pas la date du premier
    consentement, traçabilité). `last_modified` est mis à jour à chaque appel.
    """
    if not isinstance(mode, ConsentMode):
        raise TypeError(
            f"set_consent attend ConsentMode, reçu {type(mode).__name__}"
        )

    path = _resolve_storage_path(storage_path)
    now = _now_utc()

    existing_consent_date: datetime | None = None
    if path.exists():
        try:
            existing = _load_payload(path)
            existing_consent_date = _parse_dt(existing.get("consent_date"))
        except ConsentStorageError:
            # Fichier corrompu / version inconnue : on ne tente pas de
            # récupérer la date, on repart de now. L'écrasement est délibéré
            # car un set_consent explicite vaut mieux qu'un échec silencieux.
            existing_consent_date = None

    consent_date = existing_consent_date or now
    sync_enabled = _sync_enabled_for(mode)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "has_consented": True,
        "mode": mode.value,
        "sync_enabled": sync_enabled,
        "consent_date": _serialize_dt(consent_date),
        "last_modified": _serialize_dt(now),
    }
    _atomic_write(path, payload)
    logger.info(
        "Consent set: mode=%s, sync_enabled=%s, path=%s",
        mode.value,
        sync_enabled,
        path,
    )

    return ConsentStatus(
        has_consented=True,
        mode=mode,
        sync_enabled=sync_enabled,
        consent_date=consent_date,
        last_modified=now,
    )


def clear_consent(storage_path: Path | None = None) -> None:
    """Efface le consentement (re-prompt forcé au prochain lancement).

    Idempotent : si le fichier n'existe pas, no-op silencieux.
    """
    path = _resolve_storage_path(storage_path)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    logger.info("Consent cleared at %s", path)


def has_user_consented(storage_path: Path | None = None) -> bool:
    """Alias court pour check rapide (daemon de sync, gating UI)."""
    return get_consent_status(storage_path).has_consented
