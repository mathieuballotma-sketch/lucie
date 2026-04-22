"""Tests du validateur d'article early (`dialogue/article_validator.py`).

Couvre :
  1. Extraction des refs dans diverses formulations
  2. Extraction ignorée pour texte sans ref
  3. Déduplication des refs répétées
  4. Validation OK si DB contient l'article
  5. Validation KO si DB ne contient PAS l'article → message de refus
  6. LUCIE_LEGIFRANCE=0 / DB absente → no-op silencieux (None)
  7. Perf : < 200 ms même avec 3 refs
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from lucie_v1_standalone.dialogue.article_validator import (
    ARTICLE_PATTERN,
    clear_validator_cache,
    extract_article_codes,
    validate_article_refs,
)


# ─── Tests purs d'extraction (sans DB) ──────────────────────────────────────


def test_extract_basic_format():
    codes = extract_article_codes("L'article L.1234-1 est applicable")
    assert len(codes) == 1
    prefix, canonical, display = codes[0]
    assert prefix == "L"
    assert canonical == "L1234-1"
    assert display == "L.1234-1"


def test_extract_variants():
    """Accepte diverses notations (avec/sans point, avec/sans espace)."""
    q = "Voir L.1234-1, R 1234-2, L1234, et L.5678"
    codes = extract_article_codes(q)
    canonicals = {c[1] for c in codes}
    assert "L1234-1" in canonicals
    assert "R1234-2" in canonicals
    assert "L1234" in canonicals
    assert "L5678" in canonicals


def test_extract_dedup():
    codes = extract_article_codes("L.1234-1 puis L.1234-1 encore")
    assert len(codes) == 1


def test_extract_none_returns_empty():
    assert extract_article_codes("Bonjour, comment ça va ?") == []


def test_extract_ignores_noise():
    """Les nombres sans prefix L/R ne sont PAS extraits."""
    assert extract_article_codes("Il y a 1234 salariés en 2024") == []


# ─── Tests validation avec DB mockée ────────────────────────────────────────


@pytest.fixture
def fake_legifrance_db(tmp_path, monkeypatch):
    """Fabrique une DB Légifrance minimale avec 2 articles VIGUEUR + 1 abrogé,
    et pointe la config dessus."""
    db_dir = tmp_path / "legifrance"
    db_dir.mkdir()
    db_path = db_dir / "legi.sqlite"

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE articles (
            id TEXT PRIMARY KEY,
            code_cid TEXT,
            num TEXT,
            num_prefix TEXT,
            num_numeric INTEGER,
            texte TEXT,
            etat TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO articles (id, code_cid, num, num_prefix, num_numeric, texte, etat) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("A1", "LEGITEXT", "L1233-3", "L", 1233, "Texte L.1233-3", "VIGUEUR"),
            ("A2", "LEGITEXT", "L1233-4", "L", 1233, "Texte L.1233-4", "VIGUEUR"),
            ("A3", "LEGITEXT", "L9999-99", "L", 9999, "ancien", "ABROGE"),
        ],
    )
    conn.commit()
    conn.close()

    # Pointer la config vers cette DB
    monkeypatch.setenv("LUCIE_LEGIFRANCE", "1")
    monkeypatch.setenv("LUCIE_LEGIFRANCE_DIR", str(db_dir))
    # Reimport config pour que LEGIFRANCE_ENABLED soit rechargé
    import importlib

    import lucie_v1_standalone.config as cfg

    importlib.reload(cfg)
    import lucie_v1_standalone.dialogue.article_validator as av

    importlib.reload(av)
    # Expose reimported symbols pour le test
    yield av
    # Teardown
    av.clear_validator_cache()


def test_validation_passthrough_if_article_exists(fake_legifrance_db):
    """Ref valide → None (passthrough)."""
    av = fake_legifrance_db
    result = av.validate_article_refs("L'article L.1233-3 prévoit le reclassement")
    assert result is None


def test_validation_refuses_unknown_article(fake_legifrance_db):
    """Ref invalide → message de refus."""
    av = fake_legifrance_db
    result = av.validate_article_refs("L'article L.1234-999 existe-t-il ?")
    assert result is not None
    assert "L.1234-999" in result
    assert "n'existe pas" in result
    assert "Code du travail" in result


def test_validation_mixed_refs_one_invalid(fake_legifrance_db):
    """Une ref valide + une invalide → refus (sur la première invalide rencontrée)."""
    av = fake_legifrance_db
    result = av.validate_article_refs("Comparer L.1233-3 et L.9999-998")
    assert result is not None
    assert "L.9999-998" in result


def test_validation_all_valid(fake_legifrance_db):
    """Toutes refs valides → None."""
    av = fake_legifrance_db
    result = av.validate_article_refs("Lire L.1233-3 et L.1233-4")
    assert result is None


def test_abroge_article_is_not_considered_valid(fake_legifrance_db):
    """Un article en état ABROGE n'est pas traité comme valide."""
    av = fake_legifrance_db
    result = av.validate_article_refs("Article L.9999-99 s'applique ?")
    assert result is not None
    assert "L.9999-99" in result


def test_no_ref_in_query_returns_none(fake_legifrance_db):
    av = fake_legifrance_db
    assert av.validate_article_refs("Bonjour, comment ça va ?") is None


def test_empty_query_returns_none(fake_legifrance_db):
    av = fake_legifrance_db
    assert av.validate_article_refs("") is None
    assert av.validate_article_refs("   ") is None


def test_perf_under_200ms(fake_legifrance_db):
    """Perf budgétée : validation de 3 refs < 200 ms."""
    av = fake_legifrance_db
    q = "Comparer L.1233-3, L.1233-4 et L.9999-999 sur le reclassement"
    t0 = time.perf_counter()
    av.validate_article_refs(q)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 200, f"trop lent : {elapsed_ms:.1f} ms"


# ─── Tests mode dégradé (pas de DB) ─────────────────────────────────────────


def test_degraded_mode_legifrance_disabled(tmp_path, monkeypatch, caplog):
    """LUCIE_LEGIFRANCE=0 → no-op silencieux, pas d'erreur."""
    monkeypatch.setenv("LUCIE_LEGIFRANCE", "0")
    monkeypatch.setenv("LUCIE_LEGIFRANCE_DIR", str(tmp_path))
    import importlib

    import lucie_v1_standalone.config as cfg

    importlib.reload(cfg)
    import lucie_v1_standalone.dialogue.article_validator as av

    importlib.reload(av)
    try:
        result = av.validate_article_refs("L'article L.1234-999 existe-t-il ?")
        # Mode dégradé : on laisse passer même un article qui paraît faux
        assert result is None
    finally:
        av.clear_validator_cache()


def test_degraded_mode_db_missing(tmp_path, monkeypatch, caplog):
    """LEGIFRANCE=1 mais DB absente → warning log + None."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setenv("LUCIE_LEGIFRANCE", "1")
    monkeypatch.setenv("LUCIE_LEGIFRANCE_DIR", str(empty_dir))
    import importlib

    import lucie_v1_standalone.config as cfg

    importlib.reload(cfg)
    import lucie_v1_standalone.dialogue.article_validator as av

    importlib.reload(av)
    try:
        with caplog.at_level("WARNING"):
            result = av.validate_article_refs("L.1234-999 ?")
        assert result is None
        assert any("introuvable" in rec.message for rec in caplog.records)
    finally:
        av.clear_validator_cache()
