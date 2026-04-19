"""
Tests — SmallTalkHandler (30 tests, 1 par pattern).
"""

from __future__ import annotations


from lucie_v1_standalone.dialogue.small_talk_handler import handle, handle_or_default


# ── Identité ──────────────────────────────────────────────────────────────────

def test_qui_es_tu() -> None:
    r = handle("Qui es-tu ?")
    assert r is not None
    assert "Lucie" in r


def test_comment_tu_tappelles() -> None:
    r = handle("Comment tu t'appelles ?")
    assert r is not None
    assert "Lucie" in r


def test_cest_quoi_ton_nom() -> None:
    r = handle("C'est quoi ton nom ?")
    assert r is not None
    assert "Lucie" in r


# ── Fonctions ─────────────────────────────────────────────────────────────────

def test_tu_peux_faire_quoi() -> None:
    r = handle("Tu peux faire quoi ?")
    assert r is not None
    assert "licenciement" in r.lower()


def test_quelles_sont_tes_fonctions() -> None:
    r = handle("Quelles sont tes fonctions ?")
    assert r is not None
    assert "licenciement" in r.lower()


def test_tu_es_capable_de_quoi() -> None:
    r = handle("Tu es capable de quoi ?")
    assert r is not None


# ── Aide ──────────────────────────────────────────────────────────────────────

def test_aide_moi() -> None:
    r = handle("Aide-moi")
    assert r is not None


def test_help() -> None:
    r = handle("Help")
    assert r is not None


# ── Salutations ───────────────────────────────────────────────────────────────

def test_bonjour() -> None:
    r = handle("Bonjour")
    assert r is not None
    assert "bonjour" in r.lower() or "comment" in r.lower()


def test_bonsoir() -> None:
    r = handle("Bonsoir")
    assert r is not None


def test_salut() -> None:
    r = handle("Salut !")
    assert r is not None


def test_hello() -> None:
    r = handle("Hello")
    assert r is not None


def test_hey() -> None:
    r = handle("Hey")
    assert r is not None


def test_coucou() -> None:
    r = handle("Coucou")
    assert r is not None


def test_bonne_journee() -> None:
    r = handle("Bonne journée")
    assert r is not None


def test_bonne_soiree() -> None:
    r = handle("Bonne soirée")
    assert r is not None


# ── Remerciements ─────────────────────────────────────────────────────────────

def test_merci() -> None:
    r = handle("Merci")
    assert r is not None


def test_merci_beaucoup() -> None:
    r = handle("Merci beaucoup")
    assert r is not None


def test_thanks() -> None:
    r = handle("Thanks")
    assert r is not None


# ── Validation / accord ───────────────────────────────────────────────────────

def test_ok() -> None:
    r = handle("Ok")
    assert r is not None


def test_daccord() -> None:
    r = handle("D'accord")
    assert r is not None


def test_parfait() -> None:
    r = handle("Parfait")
    assert r is not None


# ── Clôtures ──────────────────────────────────────────────────────────────────

def test_au_revoir() -> None:
    r = handle("Au revoir")
    assert r is not None
    assert "revoir" in r.lower() or "continuation" in r.lower()


def test_bye() -> None:
    r = handle("Bye")
    assert r is not None


def test_a_bientot() -> None:
    r = handle("À bientôt")
    assert r is not None


# ── Déclinaisons ──────────────────────────────────────────────────────────────

def test_meteo_declined() -> None:
    r = handle("Quelle est la météo aujourd'hui ?")
    assert r is not None
    assert "météo" in r.lower() or "licenciement" in r.lower()


def test_blague_declined() -> None:
    r = handle("Raconte-moi une blague")
    assert r is not None
    assert "blague" in r.lower() or "droit" in r.lower()


def test_film_declined() -> None:
    r = handle("Tu connais un bon film ?")
    assert r is not None


# ── Test ou ping ──────────────────────────────────────────────────────────────

def test_ping() -> None:
    r = handle("test")
    assert r is not None


# ── handle_or_default toujours non-None ──────────────────────────────────────

def test_handle_or_default_unknown() -> None:
    r = handle_or_default("une question totalement hors contexte XYZ123")
    assert r  # non vide
    assert isinstance(r, str)
