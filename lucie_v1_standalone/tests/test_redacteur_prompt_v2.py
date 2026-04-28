"""Tests statiques sur le prompt search v2 du Rédacteur (brique F16).

Vérifie les propriétés contractuelles du fichier
`lucie_v1_standalone/prompts/redacteur_search_system.txt` après refonte :
- absence des blocs défensifs (« À retenir » & co.)
- présence de la phrase de refus simple
- préservation de l'exigence de citations + compatibilité regex Vérificateur

Aucun appel LLM. Tests purement statiques sur le contenu du fichier.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROMPT_PATH = (
    Path(__file__).parent.parent / "prompts" / "redacteur_search_system.txt"
)


@pytest.fixture(scope="module")
def prompt_content() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def test_no_defensive_disclaimer_block(prompt_content: str) -> None:
    """Aucun bloc terminal défensif n'est prescrit comme partie du format.

    Le bug observé en prod : le LLM ajoutait systématiquement « ## À retenir »
    avec une paraphrase moralisante de la règle de refus. Le prompt v2 doit
    interdire explicitement ce bloc et tous ses cousins.
    """
    # Le terme « À retenir » apparaît UNIQUEMENT dans la règle 5 d'interdiction
    # et dans l'anti-pattern (avec ✗). Il ne doit JAMAIS apparaître comme
    # consigne de format à appliquer.
    occurrences = prompt_content.count("À retenir")
    assert occurrences <= 2, (
        f"« À retenir » apparaît {occurrences} fois — devrait apparaître au plus "
        "2 fois (interdiction règle 5 + anti-pattern)."
    )

    # Aucun titre Markdown défensif comme directive de format.
    forbidden_headers = re.findall(
        r"##\s*(En conclusion|Important|Avertissement|Mise en garde|Précautions)",
        prompt_content,
    )
    # Tolérance : ces termes peuvent apparaître dans la règle 5 (liste
    # d'exemples interdits) mais pas comme « ## En conclusion » directive.
    # On vérifie qu'ils n'apparaissent qu'à l'intérieur d'une chaîne entre
    # guillemets (citation de l'interdit), pas comme vrai titre.
    for header in forbidden_headers:
        # Vérifier que le titre est dans un contexte d'interdiction (règle 5
        # ou anti-pattern), c'est-à-dire entouré de guillemets ou précédé d'un ✗.
        idx = prompt_content.find(f"## {header}")
        context = prompt_content[max(0, idx - 5) : idx + 5]
        assert '"' in context or "✗" in context, (
            f"Titre Markdown '## {header}' apparaît comme directive de format, "
            "pas comme exemple interdit."
        )

    # L'anti-pattern doit être explicitement étiqueté (renforce le rejet).
    assert "ANTI-PATTERN" in prompt_content, (
        "Le prompt v2 doit contenir un bloc ANTI-PATTERN explicite pour que "
        "le LLM identifie clairement le comportement à rejeter."
    )


def test_simple_dont_know_clause_present(prompt_content: str) -> None:
    """Quand pas de source : 1 phrase exacte, sèche, sans verbiage.

    La règle 4 doit prescrire littéralement la phrase de refus pour que le LLM
    ne paraphrase pas en y ajoutant du défensif (cf. bug initial).
    """
    expected_phrase = "Cette information n'est pas dans mes sources."
    assert expected_phrase in prompt_content, (
        f"Phrase de refus exacte « {expected_phrase} » manquante dans le prompt."
    )

    # Le mot « exactement » signale au LLM que la phrase doit être reproduite
    # littéralement, pas paraphrasée.
    assert "exactement" in prompt_content, (
        "Le mot « exactement » doit signaler la nature littérale de la "
        "phrase de refus (sinon le LLM la paraphrase)."
    )


def test_citation_requirement_preserved(prompt_content: str) -> None:
    """L'exigence de citations reste forte ET reste compatible avec la regex
    Vérificateur (`\\[REF:\\s*([^\\]]+)\\]|\\[([A-Za-z0-9_\\-\\.]+)\\]`).
    """
    # Format de citation enseigné au LLM.
    assert "[ID_SOURCE]" in prompt_content, (
        "Le placeholder [ID_SOURCE] doit rester dans le prompt pour signaler "
        "la syntaxe de citation au LLM."
    )

    # Mention explicite du caractère obligatoire de la citation.
    rules_block = prompt_content.split("FORMAT")[0]  # avant le bloc FORMAT
    assert (
        "Cite chaque source" in rules_block
        or "citation" in rules_block.lower()
    ), "Aucune règle absolue n'impose la citation systématique."

    # Garde-fou anti-régression : les exemples du prompt doivent matcher la
    # regex du Vérificateur. Sinon le Rédacteur enseigne un format invalide
    # qui sera silencieusement supprimé en aval.
    verificateur_regex = re.compile(
        r"\[REF:\s*([^\]]+)\]|\[([A-Za-z0-9_\-\.]+)\]"
    )
    matches = verificateur_regex.findall(prompt_content)
    # Au moins un exemple concret de citation doit être présent (les exemples
    # de style en contiennent : [L1234-1], etc.).
    concrete_citations = [m for m in matches if m[1] and m[1] != "ID"]
    assert concrete_citations, (
        "Aucune citation concrète (ex [L1234-1]) dans les exemples du prompt — "
        "le LLM n'a pas de modèle imitable au format Vérificateur."
    )
