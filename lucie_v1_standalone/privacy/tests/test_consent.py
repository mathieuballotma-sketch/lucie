"""Tests unitaires du consent flow Beaume (Sprint K-8 step 0).

Tous les tests sont isolés via `tmp_path` — aucun ne touche au vrai storage
utilisateur (`~/Library/Application Support/Beaume/privacy/`). Aucun appel
réseau n'est effectué (invariant Beaume #8).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lucie_v1_standalone.privacy.consent import (
    SCHEMA_VERSION,
    ConsentMode,
    ConsentSchemaVersionError,
    ConsentStatus,
    ConsentStorageError,
    clear_consent,
    get_consent_status,
    has_user_consented,
    set_consent,
)


@pytest.fixture
def tmp_consent_path(tmp_path: Path) -> Path:
    """Chemin isolé pour chaque test, garantit aucune interférence avec le
    vrai storage utilisateur."""
    return tmp_path / "consent.json"


def test_no_consent_returns_default_status(tmp_consent_path: Path) -> None:
    status = get_consent_status(tmp_consent_path)
    assert status.has_consented is False
    assert status.mode is ConsentMode.STANDARD
    assert status.sync_enabled is False
    assert status.consent_date is None
    assert status.last_modified is None
    assert not tmp_consent_path.exists(), "get ne doit jamais créer le fichier"


def test_set_consent_standard_persists_correctly(tmp_consent_path: Path) -> None:
    returned = set_consent(ConsentMode.STANDARD, tmp_consent_path)
    assert returned.has_consented is True
    assert returned.mode is ConsentMode.STANDARD
    assert returned.sync_enabled is True
    assert returned.consent_date is not None
    assert returned.last_modified is not None

    reread = get_consent_status(tmp_consent_path)
    assert reread.has_consented is True
    assert reread.mode is ConsentMode.STANDARD
    assert reread.sync_enabled is True
    assert reread.consent_date == returned.consent_date
    assert reread.last_modified == returned.last_modified


def test_set_consent_pro_souverainete_disables_sync(tmp_consent_path: Path) -> None:
    status = set_consent(ConsentMode.PRO_SOUVERAINETE, tmp_consent_path)
    assert status.mode is ConsentMode.PRO_SOUVERAINETE
    assert status.sync_enabled is False, (
        "Pro souveraineté DOIT désactiver la sync — invariant Beaume"
    )

    reread = get_consent_status(tmp_consent_path)
    assert reread.sync_enabled is False


def test_clear_consent_removes_file(tmp_consent_path: Path) -> None:
    set_consent(ConsentMode.STANDARD, tmp_consent_path)
    assert tmp_consent_path.exists()

    clear_consent(tmp_consent_path)
    assert not tmp_consent_path.exists()

    # Idempotent : deuxième appel ne lève pas
    clear_consent(tmp_consent_path)
    assert not tmp_consent_path.exists()

    # Et l'état repart bien sur défaut
    status = get_consent_status(tmp_consent_path)
    assert status.has_consented is False


def test_consent_date_set_on_first_consent_not_overwritten_on_change(
    tmp_consent_path: Path,
) -> None:
    first = set_consent(ConsentMode.STANDARD, tmp_consent_path)
    initial_date = first.consent_date
    assert initial_date is not None

    # Petit sleep pour garantir un timestamp différent (résolution micro-seconde
    # mais on reste prudent face aux horloges peu précises).
    time.sleep(0.01)

    second = set_consent(ConsentMode.PRO_SOUVERAINETE, tmp_consent_path)
    assert second.consent_date == initial_date, (
        "consent_date doit être préservé lors d'un changement de mode"
    )
    assert second.last_modified is not None
    assert second.last_modified > initial_date


def test_last_modified_updated_on_every_change(tmp_consent_path: Path) -> None:
    first = set_consent(ConsentMode.STANDARD, tmp_consent_path)
    time.sleep(0.01)
    second = set_consent(ConsentMode.PRO_SOUVERAINETE, tmp_consent_path)
    time.sleep(0.01)
    third = set_consent(ConsentMode.STANDARD, tmp_consent_path)

    assert first.last_modified is not None
    assert second.last_modified is not None
    assert third.last_modified is not None
    assert first.last_modified < second.last_modified < third.last_modified


def test_atomic_write_no_corruption_on_simulated_crash(
    tmp_consent_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. Établir un état initial valide.
    set_consent(ConsentMode.STANDARD, tmp_consent_path)
    original_bytes = tmp_consent_path.read_bytes()

    # 2. Simuler un crash juste avant le rename atomique.
    from lucie_v1_standalone.privacy import consent as consent_mod

    def _crash(_src: str, _dst: str) -> None:
        raise OSError("simulated crash between tmp write and rename")

    monkeypatch.setattr(consent_mod.os, "replace", _crash)

    with pytest.raises(OSError, match="simulated crash"):
        set_consent(ConsentMode.PRO_SOUVERAINETE, tmp_consent_path)

    # 3. Vérifier que l'ancien fichier est intact (pas de corruption).
    assert tmp_consent_path.read_bytes() == original_bytes, (
        "Le fichier consent original a été corrompu malgré le crash simulé"
    )

    # 4. Vérifier qu'aucun .tmp orphelin ne traîne dans le dossier.
    leftover = list(tmp_consent_path.parent.glob(".consent_*.tmp"))
    assert leftover == [], (
        f"Tmp file orphelin après crash simulé: {leftover}"
    )


def test_storage_file_has_secure_permissions(tmp_consent_path: Path) -> None:
    set_consent(ConsentMode.STANDARD, tmp_consent_path)
    mode = tmp_consent_path.stat().st_mode & 0o777
    assert mode == 0o600, (
        f"Permissions attendues 0o600 (privacy), trouvées {oct(mode)}"
    )


def test_invalid_json_in_storage_raises_explicit_error(tmp_consent_path: Path) -> None:
    tmp_consent_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_consent_path.write_text("{garbage not json", encoding="utf-8")

    with pytest.raises(ConsentStorageError) as excinfo:
        get_consent_status(tmp_consent_path)
    assert "corrompu" in str(excinfo.value).lower()


def test_schema_version_mismatch_raises_explicit_error(
    tmp_consent_path: Path,
) -> None:
    tmp_consent_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_consent_path.write_text(
        json.dumps(
            {
                "schema_version": 99,
                "has_consented": True,
                "mode": "standard",
                "sync_enabled": True,
                "consent_date": "2026-05-15T10:00:00+00:00",
                "last_modified": "2026-05-15T10:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConsentSchemaVersionError) as excinfo:
        get_consent_status(tmp_consent_path)
    assert "99" in str(excinfo.value)
    assert str(SCHEMA_VERSION) in str(excinfo.value)


def test_get_status_returns_dataclass_instance_not_dict(
    tmp_consent_path: Path,
) -> None:
    status = get_consent_status(tmp_consent_path)
    assert isinstance(status, ConsentStatus)

    with pytest.raises(FrozenInstanceError):
        status.has_consented = True  # type: ignore[misc]


def test_has_user_consented_alias(tmp_consent_path: Path) -> None:
    assert has_user_consented(tmp_consent_path) is False
    set_consent(ConsentMode.STANDARD, tmp_consent_path)
    assert has_user_consented(tmp_consent_path) is True


def test_set_consent_rejects_non_enum_input(tmp_consent_path: Path) -> None:
    with pytest.raises(TypeError):
        set_consent("standard", tmp_consent_path)  # type: ignore[arg-type]
