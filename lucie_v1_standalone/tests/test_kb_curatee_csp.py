"""Tests unitaires KB curatée CSP — Sprint 6 P3.

Vérifie que les articles L.1233-65 à L.1233-68 (Contrat de sécurisation
professionnelle) ajoutés en Sprint 6 P3 sont présents, bien formés et
référencés correctement dans ``index.json``. Ces 4 articles couvrent
SW-LECO-010 (« Qu'est-ce que le CSP et qui peut en bénéficier ? ») — sans
eux, le retriever curaté ne ramène rien pour cette query et Gemma refuse
faute de sources.

Garde-fou truth rule : un test vérifie qu'aucun mot-clé n'est une copie
verbatim du prompt du benchmark, pour éviter tout overfit déguisé.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


KB_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "knowledge"
    / "droit_social"
    / "licenciement_economique"
)

CSP_ARTICLE_IDS = ["L1233-65", "L1233-66", "L1233-67", "L1233-68"]

REQUIRED_SECTIONS = ("## Texte officiel", "## Résumé opérationnel", "## Mots-clés", "## Articles liés")

# Prompt SW-LECO-010 — référence pour le test anti-overfit. Conservé en
# constante locale pour garder le test autonome (pas de dépendance au
# benchmark file qui peut bouger).
SW_LECO_010_PROMPT = (
    "Qu'est-ce que le contrat de sécurisation professionnelle (CSP) "
    "et qui peut en bénéficier ?"
)


@pytest.mark.parametrize("article_id", CSP_ARTICLE_IDS)
def test_csp_article_file_present(article_id: str) -> None:
    """Le fichier .md de chaque article CSP existe et n'est pas vide."""
    path = KB_DIR / f"{article_id}.md"
    assert path.exists(), f"Article CSP manquant : {path}"
    assert path.stat().st_size > 200, f"Article {article_id} suspect (trop court)"


@pytest.mark.parametrize("article_id", CSP_ARTICLE_IDS)
def test_csp_article_format(article_id: str) -> None:
    """Chaque article CSP a les 4 sections obligatoires du format KB."""
    content = (KB_DIR / f"{article_id}.md").read_text(encoding="utf-8")
    for section in REQUIRED_SECTIONS:
        assert section in content, (
            f"Section '{section}' manquante dans {article_id}.md "
            f"— format KB curatée non respecté"
        )


def test_csp_index_lists_all_four_articles() -> None:
    """``index.json`` liste les 4 articles CSP avec id, title, path, keywords."""
    index = json.loads((KB_DIR / "index.json").read_text(encoding="utf-8"))
    article_ids_in_index = {a["id"] for a in index["articles"]}
    for csp_id in CSP_ARTICLE_IDS:
        assert csp_id in article_ids_in_index, (
            f"{csp_id} absent de index.json — le retriever ne le trouvera pas"
        )
    for article in index["articles"]:
        if article["id"] in CSP_ARTICLE_IDS:
            assert article.get("title"), f"{article['id']} sans title"
            assert article.get("path"), f"{article['id']} sans path"
            assert article.get("keywords"), f"{article['id']} sans keywords"


def test_csp_index_version_bumped() -> None:
    """La version d'``index.json`` est ≥ 1.1.0 (Sprint 6 P3)."""
    index = json.loads((KB_DIR / "index.json").read_text(encoding="utf-8"))
    version = index["version"]
    major, minor, _ = (int(x) for x in version.split("."))
    assert (major, minor) >= (1, 1), (
        f"Version index.json={version} — attendu ≥1.1.0 après extension CSP"
    )


def test_csp_keywords_no_overfit_on_benchmark_prompt() -> None:
    """Aucun mot-clé d'un article CSP ne copie verbatim le prompt SW-LECO-010.

    Truth rule : on enrichit la KB pour répondre à un sujet juridique
    (« contrat de sécurisation professionnelle »), pas pour matcher la
    phrase exacte du benchmark. Ce test bloque toute tentative de tuning
    qui copierait la question verbatim en mot-clé.
    """
    prompt_lower = SW_LECO_010_PROMPT.lower()
    index = json.loads((KB_DIR / "index.json").read_text(encoding="utf-8"))
    for article in index["articles"]:
        if article["id"] not in CSP_ARTICLE_IDS:
            continue
        for keyword in article["keywords"]:
            assert keyword.lower() != prompt_lower, (
                f"Mot-clé overfit détecté sur {article['id']} : "
                f"'{keyword}' == prompt SW-LECO-010 verbatim"
            )
            # Plus strict : pas de sous-chaîne longue (>40 chars) qui contiendrait
            # une grosse portion du prompt.
            if len(keyword) > 40 and keyword.lower() in prompt_lower:
                pytest.fail(
                    f"Mot-clé long {keyword!r} de {article['id']} "
                    "semble extrait verbatim du prompt — risque d'overfit"
                )


def test_csp_articles_cross_reference_each_other() -> None:
    """Les 4 articles CSP se référencent mutuellement (cohérence interne KB).

    L.1233-65/66/67/68 forment un bloc juridique — chaque article cite au
    moins un autre article du bloc dans sa section "Articles liés".
    """
    for article_id in CSP_ARTICLE_IDS:
        content = (KB_DIR / f"{article_id}.md").read_text(encoding="utf-8")
        others = [aid for aid in CSP_ARTICLE_IDS if aid != article_id]
        # Cherche L.1233-6X ou L1233-6X dans la section "Articles liés"
        articles_lies_section = content.split("## Articles liés", 1)
        if len(articles_lies_section) < 2:
            pytest.fail(f"{article_id} sans section 'Articles liés'")
        section = articles_lies_section[1]
        normalized = re.sub(r"[.\s]", "", section)
        cross_refs = sum(
            1 for other in others
            if re.sub(r"[.\s]", "", other) in normalized
        )
        assert cross_refs >= 1, (
            f"{article_id} ne référence aucun autre article du bloc CSP "
            f"({others}) — cohérence interne suspecte"
        )
