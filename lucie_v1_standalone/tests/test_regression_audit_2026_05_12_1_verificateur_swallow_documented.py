"""Régression audit 2026-05-12 P0 #1 — verificateur._build_source_ids JSONDecodeError.

POURQUOI : avant l'audit, verificateur._build_source_ids() avalait silencieusement
les JSONDecodeError via `except Exception: return {}`, produisant un source_ids
vide qui rendait TOUTES les citations INVALIDES sans la moindre trace de
diagnostic. Ce test verrouille le log.error pour empêcher la régression.

Source : Audit qualité lucie_v1_standalone 2026-05-12 (hash d35f4a52...).
"""
from __future__ import annotations

import logging

import pytest

from lucie_v1_standalone.verificateur import _build_source_ids


def test_malformed_json_logs_error_and_returns_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """sources_json invalide → dict vide + 1 log.error mentionnant 'malformé'.

    Le retour {} reste le contrat (pour ne pas casser la pipeline en aval),
    mais le log.error doit être émis pour que le diagnostic soit possible.
    """
    caplog.set_level(logging.ERROR, logger="lucie_v1_standalone.verificateur")

    result = _build_source_ids("{not valid json")

    assert result == {}
    error_records = [
        r for r in caplog.records if r.levelname == "ERROR"
    ]
    assert len(error_records) == 1, (
        f"Expected exactly 1 ERROR log, got {len(error_records)}"
    )
    assert "malformé" in error_records[0].getMessage()


def test_valid_json_does_not_log(caplog: pytest.LogCaptureFixture) -> None:
    """Happy path : JSON valide → pas de log d'erreur, dict peuplé."""
    caplog.set_level(logging.ERROR, logger="lucie_v1_standalone.verificateur")
    payload = (
        '{"sources": [{"id": "L1233-3", "extrait": "test extrait"}],'
        ' "jurisprudences": []}'
    )

    result = _build_source_ids(payload)

    assert result, "Expected non-empty result for valid JSON"
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
