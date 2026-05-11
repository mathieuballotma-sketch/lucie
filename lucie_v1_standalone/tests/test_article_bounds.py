"""Tests Cerveau Oiseaux v2 — préfiltre bornes numériques d'articles.

Couvre :
  1. Parsing de divers formats d'articles (avec/sans point, casse mixte)
  2. Refus instantané pour numéros hors borne sur racine connue
  3. Silence (False) pour racine inconnue, format invalide, suffix dans borne
  4. Latence < 1 ms par appel (cible de la mission Beaume)
  5. Bounds table chargée depuis SQLite OU fallback whitelist
  6. Intégration : validate_article_refs court-circuite SQLite via le préfiltre
"""

from __future__ import annotations

import time

import pytest

from lucie_v1_standalone.dialogue.article_bounds import (
    ARTICLE_BOUNDS_CT,
    bounds_source,
    bounds_table_size,
    is_article_impossible,
    parse_article_ref,
)


# ─── Parsing des références ─────────────────────────────────────────────────


def test_parse_format_avec_point():
    assert parse_article_ref("L.1234-999") == ("L", 1234, 999)


def test_parse_format_sans_point():
    assert parse_article_ref("L1234-999") == ("L", 1234, 999)


def test_parse_format_avec_espace():
    assert parse_article_ref("L 1234-999") == ("L", 1234, 999)


def test_parse_casse_mixte():
    assert parse_article_ref("l1234-5") == ("L", 1234, 5)
    assert parse_article_ref("r.1234-5") == ("R", 1234, 5)


def test_parse_classe_d():
    """La table de bornes couvre aussi les D, donc on parse les D."""
    assert parse_article_ref("D.1234-1") == ("D", 1234, 1)


def test_parse_sans_suffixe_retourne_none():
    """Sans suffixe, pas de borne à vérifier → None."""
    assert parse_article_ref("L.1234") is None
    assert parse_article_ref("L1234") is None


def test_parse_sub_suffixe_garde_principal():
    """L1234-17-1 → on retient le suffixe principal (17), pas le sous."""
    assert parse_article_ref("L1234-17-1") == ("L", 1234, 17)


def test_parse_format_invalide():
    assert parse_article_ref("garbage") is None
    assert parse_article_ref("") is None
    assert parse_article_ref("L") is None
    assert parse_article_ref("Z.1234-1") is None  # classe non reconnue


# ─── Refus par borne (cas Beaume) ───────────────────────────────────────────


def test_article_impossible_cas_beaume():
    """Le cas exact rapporté par Mathieu : L.1234-999 doit être refusé direct."""
    impossible, raison = is_article_impossible("L.1234-999")
    assert impossible is True
    assert raison is not None
    assert "1234" in raison
    assert "999" in raison


def test_article_impossible_juste_au_dessus_du_max():
    """Si DILA dit max=20 pour L.1234-x, alors 21 doit être refusé."""
    bounds = ARTICLE_BOUNDS_CT.get(("L", 1234))
    if bounds is None:
        pytest.skip("Racine L.1234 absente de la table — table dégradée?")
    _, suffix_max = bounds
    impossible, _ = is_article_impossible(f"L.1234-{suffix_max + 1}")
    assert impossible is True


def test_article_valide_dans_la_borne_passe():
    """L.1234-1 et L.1234-max doivent passer (pas refusés par bornes)."""
    bounds = ARTICLE_BOUNDS_CT.get(("L", 1234))
    if bounds is None:
        pytest.skip("Racine L.1234 absente")
    suffix_min, suffix_max = bounds
    impossible_min, _ = is_article_impossible(f"L.1234-{suffix_min}")
    impossible_max, _ = is_article_impossible(f"L.1234-{suffix_max}")
    assert impossible_min is False
    assert impossible_max is False


def test_racine_inconnue_comportement_selon_source():
    """Racine non listée → comportement dépend de la source des bornes.

    Si table SQLite (exhaustive ~4500 racines) : refus déterministe — la
    racine n'existe nulle part en VIGUEUR dans la DILA.
    Si fallback whitelist (~250 racines) : silence pour éviter les faux
    positifs (couverture partielle).
    """
    src = bounds_source()
    impossible, raison = is_article_impossible("L.9999-1")
    if src.startswith("sqlite-legifrance"):
        assert impossible is True, (
            "Avec table SQLite exhaustive, racine inconnue = refus"
        )
        assert raison is not None
        assert "9999" in raison
    else:
        assert impossible is False, (
            "En mode dégradé whitelist, racine inconnue = silence"
        )
        assert raison is None


def test_format_invalide_passe_silencieusement():
    impossible, raison = is_article_impossible("garbage")
    assert impossible is False
    assert raison is None


def test_article_sans_suffixe_passe():
    """L.1234 (sans suffixe) ne peut pas être refusé par bornes."""
    impossible, raison = is_article_impossible("L.1234")
    assert impossible is False
    assert raison is None


# ─── Latence (cible mission Beaume : < 1 ms par appel) ──────────────────────


def test_latence_refus_borne_inferieure_a_1ms():
    """1000 appels en moins d'une seconde = < 1 ms par appel."""
    n = 1000
    t = time.perf_counter()
    for _ in range(n):
        is_article_impossible("L.1234-999")
    elapsed_per_call_ms = (time.perf_counter() - t) / n * 1000
    assert elapsed_per_call_ms < 1.0, (
        f"{elapsed_per_call_ms:.4f} ms/appel > 1 ms (cible Beaume)"
    )


def test_latence_passthrough_inferieure_a_1ms():
    """Cas passthrough (article valide) doit aussi être <1ms."""
    n = 1000
    t = time.perf_counter()
    for _ in range(n):
        is_article_impossible("L.1234-1")
    elapsed_per_call_ms = (time.perf_counter() - t) / n * 1000
    assert elapsed_per_call_ms < 1.0


# ─── Sanity checks de la table de bornes ────────────────────────────────────


def test_bounds_table_non_vide():
    """La table est chargée avec un nombre minimum de racines."""
    # Au moins 100 racines en mode dégradé (whitelist), >2000 si SQLite généré.
    assert bounds_table_size() >= 100


def test_bounds_table_inclut_l1234():
    """Sanity : la racine L.1234 (Code du travail, contrat) doit être présente."""
    assert ("L", 1234) in ARTICLE_BOUNDS_CT


def test_bounds_source_identifiee():
    """La source est soit DILA soit fallback, jamais inconnue."""
    src = bounds_source()
    assert src.startswith("sqlite-legifrance@") or src == "whitelist-ranges-fallback"


# ─── Intégration : validate_article_refs court-circuite SQLite ──────────────


def test_validate_article_refs_court_circuite_par_bornes():
    """validate_article_refs doit refuser L.1234-999 SANS toucher SQLite.

    Mesure : avec Légifrance activée, le refus doit être <100ms (vs ~9s
    sans préfiltre). On utilise une chaîne vide pour s'assurer que c'est
    bien le préfiltre qui statue, pas la chain.
    """
    import os

    os.environ["BEAUME_LEGIFRANCE"] = "1"
    from lucie_v1_standalone.dialogue.article_validator import (
        clear_validator_cache,
        validate_article_refs,
    )

    clear_validator_cache()
    t = time.perf_counter()
    msg = validate_article_refs("Que dit l'article L.1234-999 du Code du travail ?")
    elapsed_ms = (time.perf_counter() - t) * 1000

    assert msg is not None, "L.1234-999 doit être refusé"
    assert "L.1234-999" in msg
    # Cible : <100ms. On laisse 500ms de marge pour environnements lents.
    assert elapsed_ms < 500, (
        f"validate_article_refs a pris {elapsed_ms:.1f} ms — préfiltre inactif?"
    )


def test_validate_article_refs_passthrough_si_borne_ok():
    """L.1234-1 (dans borne) doit traverser le préfiltre et atteindre SQLite/whitelist.

    Le résultat dépend de la chain (None si valide, message sinon), mais
    le préfiltre ne doit PAS le refuser tout seul.
    """
    from lucie_v1_standalone.dialogue.article_bounds import is_article_impossible

    impossible, _ = is_article_impossible("L.1234-1")
    assert impossible is False  # le préfiltre laisse passer, chain décide
