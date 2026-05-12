"""Régression Sprint 6 P2c-1 — chargement conditionnel du prompt privé Rédacteur.

POURQUOI : sans override privé du prompt système, Gemma4:e4b applique
littéralement la phrase de refus du prompt public même lorsque le contexte
fourni contient des articles juridiques pertinents (mesure post-mortem
batterie 50q post-P2b : cœur lic_eco 2/10 — 8 refus hallucinés sur 10). Le
flag `BEAUME_REDACTEUR_STRICT_CONTEXT` (défaut "1") permet d'injecter un
prompt enrichi depuis `prompts_private/` sans polluer le repo public.

Ces tests verrouillent les quatre comportements attendus :
  1. Flag off → toujours le prompt public.
  2. Flag on mais dossier privé absent (cas nominal repo OSS) → public.
  3. Flag on + fichier privé présent → privé.
  4. `handle()` propage bien le résultat de `_load_system_prompt` au LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lucie_v1_standalone import redacteur


PRIVATE_FIXTURE = "PROMPT PRIVÉ — sentinel value Sprint 6 P2c-1."


@pytest.fixture
def sources_json_minimal() -> str:
    """JSON sources minimal pour passer la garde `nb_sources == 0`."""
    return json.dumps(
        {
            "sources": [{"id": "L1233-67", "text": "Extrait d'article."}],
            "jurisprudences": [],
        }
    )


def test_load_returns_public_when_flag_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Flag explicitement off → le prompt public est servi même si fichier privé
    présent. Garantit que `BEAUME_REDACTEUR_STRICT_CONTEXT=0` est un kill-switch
    fiable (utile pour A/B testing prompt public vs privé)."""
    monkeypatch.setenv("BEAUME_REDACTEUR_STRICT_CONTEXT", "0")

    private_file = tmp_path / "redacteur_search_strict_context.txt"
    private_file.write_text(PRIVATE_FIXTURE, encoding="utf-8")
    monkeypatch.setattr(redacteur, "_PRIVATE_PROMPTS_DIR", tmp_path)

    result = redacteur._load_system_prompt("search")
    public_text = redacteur._SYSTEM_SEARCH.read_text(encoding="utf-8")
    assert result == public_text
    assert PRIVATE_FIXTURE not in result


def test_load_returns_public_when_private_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Flag on (défaut) mais dossier privé inexistant → public sans warning.
    C'est le cas nominal d'un clone du repo OSS : le pipeline doit fonctionner
    sans afficher de bruit log. Vérifie aussi le mode `document`."""
    monkeypatch.setenv("BEAUME_REDACTEUR_STRICT_CONTEXT", "1")
    monkeypatch.setattr(redacteur, "_PRIVATE_PROMPTS_DIR", tmp_path / "absent")

    with caplog.at_level("WARNING", logger=redacteur.__name__):
        result_search = redacteur._load_system_prompt("search")
        result_document = redacteur._load_system_prompt("document")

    assert result_search == redacteur._SYSTEM_SEARCH.read_text(encoding="utf-8")
    assert result_document == redacteur._SYSTEM_DOCUMENT.read_text(encoding="utf-8")
    assert not caplog.records, (
        "Aucun WARNING ne doit être émis quand le dossier privé est absent "
        f"(cas OSS nominal). Vu : {[r.message for r in caplog.records]}"
    )


def test_load_returns_private_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Flag on + fichier privé présent → contenu privé servi, en `search` ET
    `document`. Verrouille le cœur du mécanisme P2c-1."""
    monkeypatch.setenv("BEAUME_REDACTEUR_STRICT_CONTEXT", "1")
    monkeypatch.setattr(redacteur, "_PRIVATE_PROMPTS_DIR", tmp_path)

    (tmp_path / "redacteur_search_strict_context.txt").write_text(
        PRIVATE_FIXTURE + " (search)", encoding="utf-8"
    )
    (tmp_path / "redacteur_system_strict_context.txt").write_text(
        PRIVATE_FIXTURE + " (document)", encoding="utf-8"
    )

    assert redacteur._load_system_prompt("search") == PRIVATE_FIXTURE + " (search)"
    assert redacteur._load_system_prompt("document") == PRIVATE_FIXTURE + " (document)"


@pytest.mark.asyncio
async def test_handle_propagates_loaded_system_to_llm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sources_json_minimal: str
) -> None:
    """`handle()` doit envoyer au LLM exactement la sortie de `_load_system_prompt`.

    POURQUOI ce test au lieu d'un test plus fin : c'est la propriété d'intégration
    qui compte — si `handle()` court-circuitait `_load_system_prompt` ou
    rechargeait le fichier public par-dessus, le bug serait silencieux et la
    batterie ne mesurerait que le prompt public. Ce test gèle le branchement.
    """
    monkeypatch.setenv("BEAUME_REDACTEUR_STRICT_CONTEXT", "1")
    monkeypatch.setattr(redacteur, "_PRIVATE_PROMPTS_DIR", tmp_path)
    (tmp_path / "redacteur_search_strict_context.txt").write_text(
        PRIVATE_FIXTURE, encoding="utf-8"
    )

    captured: dict[str, object] = {}

    async def fake_generate(**kwargs: object) -> str:
        captured.update(kwargs)
        return "réponse mockée"

    monkeypatch.setattr(redacteur.ollama_client, "generate", fake_generate)

    result = await redacteur.handle(
        faits_json=json.dumps({"query": "Indemnité de licenciement L.1234-9 ?"}),
        sources_json=sources_json_minimal,
        mode="search",
    )

    assert result == "réponse mockée"
    assert captured.get("system") == PRIVATE_FIXTURE
