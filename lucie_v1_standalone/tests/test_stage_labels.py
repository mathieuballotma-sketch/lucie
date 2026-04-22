"""Tests unitaires des libellés utilisateur (`stage_labels.py`).

Couvre `user_label()` (existant) et `sub_label()` (ajouté en Commit 6).
Pas de dépendance AppKit — pure logique de mapping string.
"""

from __future__ import annotations

from lucie_v1_standalone.stage_labels import sub_label, user_label


def test_user_label_defaults():
    assert user_label("lecteur") == "Je comprends votre question"
    assert user_label("retriever") == "Je consulte les articles pertinents"
    assert user_label("redacteur") == "Je prépare la réponse"
    assert user_label("verificateur") == "Je vérifie chaque citation"


def test_user_label_with_document():
    assert user_label("retriever", has_document=True) == "Je lis votre dossier"


def test_user_label_document_mode():
    assert (
        user_label("redacteur", produces_document=True)
        == "Je rédige le projet de courrier"
    )
    assert (
        user_label("redacteur", mode="action") == "Je rédige le projet de courrier"
    )


def test_sub_label_lit_article_with_ref():
    """Format attendu : « Je lis L.1233-3 »."""
    assert sub_label("lit_article", {"article": "L1233-3"}) == "Je lis L1233-3"
    assert sub_label("lit_article", {"article": "L.1233-3"}) == "Je lis L.1233-3"


def test_sub_label_lit_article_without_ref():
    """Fallback générique si la clé `article` manque."""
    assert sub_label("lit_article", {}) == "Je lis un article"
    assert sub_label("lit_article", None) == "Je lis un article"


def test_sub_label_verifie_citation():
    assert (
        sub_label("verifie_citation", {"cite": "L.1233-3"})
        == "Je vérifie L.1233-3"
    )
    assert sub_label("verifie_citation", {}) == "Je vérifie une citation"


def test_sub_label_redacteur_hooks():
    assert sub_label("structure_reponse") == "Je structure la réponse"
    assert sub_label("redige") == "Je rédige"


def test_sub_label_unknown_hook_generic_fallback():
    """Hook inconnu → libellé générique sans exposer le nom interne."""
    assert sub_label("some_internal_hook_xyz") == "Je travaille"


def test_sub_label_ref_fallback_key():
    """`ref` accepté comme alias de `article`/`cite` pour flexibilité emit."""
    assert sub_label("lit_article", {"ref": "R.1234"}) == "Je lis R.1234"
    assert sub_label("verifie_citation", {"ref": "L.1"}) == "Je vérifie L.1"
