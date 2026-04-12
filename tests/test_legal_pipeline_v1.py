"""
Tests unitaires pour le pipeline V1 droit social — LegalPipeline.

Couverture :
  - LegalRouter : filtrage déterministe (pas de LLM)
  - RetrieverAgent : indexation et recherche BM25 (pas de LLM)
  - LegalPipeline : smoke test complet (requiert Ollama — skippé si absent)

Lancer avec :
    python -m pytest tests/test_legal_pipeline_v1.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── S'assurer que la racine du projet est dans sys.path ──────────────────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.lucie_v1.router import LegalRouter, REFUSAL_MESSAGE
from app.agents.lucie_v1.retriever import RetrieverAgent


# ─── Utilitaire Ollama ────────────────────────────────────────────────────────

def _ollama_running() -> bool:
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "2", "http://localhost:11434/api/tags"],
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def router() -> LegalRouter:
    return LegalRouter()


@pytest.fixture
def retriever(tmp_path) -> RetrieverAgent:
    """RetrieverAgent pointant sur la vraie base curatée (chemin absolu)."""
    mock_llm = MagicMock()
    mock_bus = MagicMock()
    agent = RetrieverAgent(llm_service=mock_llm, bus=mock_bus)
    # Pointer sur la base curatée réelle avec un chemin absolu
    agent._knowledge_base = ROOT / "knowledge/droit_social/licenciement_economique"
    # Rediriger le journal vers tmp pour ne pas polluer le repo
    agent.JOURNAL_DIR = tmp_path / "journals"
    return agent


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  ROUTER — tests déterministes, 0 LLM
# ═══════════════════════════════════════════════════════════════════════════════

class TestLegalRouter:

    def test_valid_query_licenciement_economique(self, router, tmp_path):
        router.JOURNAL_DIR = tmp_path / "journals"
        result = router.validate("Mon client a reçu une lettre de licenciement économique")
        assert result["valid"] is True
        assert result["intent"] == "analyse_licenciement"
        assert result["refusal_reason"] is None

    def test_valid_query_PSE(self, router, tmp_path):
        router.JOURNAL_DIR = tmp_path / "journals"
        result = router.validate("L'entreprise a lancé un PSE pour 200 salariés")
        assert result["valid"] is True
        assert result["intent"] == "analyse_licenciement"

    def test_out_of_scope_refusal(self, router, tmp_path):
        router.JOURNAL_DIR = tmp_path / "journals"
        result = router.validate("recette de gâteau au chocolat")
        assert result["valid"] is False
        assert result["intent"] == "hors_scope"
        assert result["refusal_reason"] == REFUSAL_MESSAGE
        assert result["document"] is None

    def test_force_bypasses_filtering(self, router, tmp_path):
        router.JOURNAL_DIR = tmp_path / "journals"
        result = router.validate("recette de gâteau", force=True)
        assert result["valid"] is True
        assert result["intent"] == "analyse_licenciement"

    def test_keyword_in_document_text(self, router, tmp_path):
        """Un document joint contenant un mot-clé valide la requête même si la query est neutre."""
        router.JOURNAL_DIR = tmp_path / "journals"
        result = router.validate(
            query="Analyse ce document",
            document_text="Objet : licenciement économique suite à difficultés économiques",
        )
        assert result["valid"] is True

    def test_document_returned_in_result(self, router, tmp_path):
        router.JOURNAL_DIR = tmp_path / "journals"
        doc = "Lettre de licenciement économique du 01/01/2024"
        result = router.validate(query="analyser", document_text=doc, force=True)
        assert result["document"] == doc

    def test_multiple_scope_keywords(self, router, tmp_path):
        router.JOURNAL_DIR = tmp_path / "journals"
        for kw in ["RCC", "L1233", "reclassement", "préavis", "droit du travail"]:
            res = router.validate(f"Question sur le {kw}")
            assert res["valid"] is True, f"Keyword '{kw}' should match scope"


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  RETRIEVER — indexation et recherche, 0 LLM
# ═══════════════════════════════════════════════════════════════════════════════

class TestRetrieverIndex:

    def test_build_index_finds_all_articles(self, retriever):
        index = retriever._build_index()
        assert len(index) >= 16, f"Attendu ≥ 16 docs, trouvé {len(index)}"

    def test_index_contains_required_fields(self, retriever):
        index = retriever._build_index()
        assert index, "Index vide"
        doc = index[0]
        for field in ("id", "path", "content", "tokens", "tokens_set"):
            assert field in doc, f"Champ manquant : {field}"

    def test_index_finds_L1233_3(self, retriever):
        index = retriever._build_index()
        ids = [d["id"] for d in index]
        assert "L1233-3" in ids, f"L1233-3 absent de l'index — ids trouvés : {ids[:5]}…"

    def test_extract_legal_refs_single(self):
        refs = RetrieverAgent._extract_legal_refs("Voir l'article L1233-1 du Code du travail")
        assert "L1233-1" in refs

    def test_extract_legal_refs_multiple(self):
        refs = RetrieverAgent._extract_legal_refs("Articles L1233-1 et L1233-5 applicables")
        assert "L1233-1" in refs
        assert "L1233-5" in refs

    def test_extract_legal_refs_with_spaces(self):
        """Normalise les références avec espaces internes (ex: L 1233-3 → L1233-3)."""
        refs = RetrieverAgent._extract_legal_refs("Voir L 1233-3")
        assert "L1233-3" in refs

    def test_extract_legal_refs_empty(self):
        refs = RetrieverAgent._extract_legal_refs("Aucune référence légale ici")
        assert refs == []

    @pytest.mark.asyncio
    async def test_bm25_search_returns_results(self, retriever):
        faits_json = json.dumps({
            "faits": "indemnités licenciement préavis salarié"
        })
        raw = await retriever.handle(faits_json)
        result = json.loads(raw)
        assert "sources" in result
        assert isinstance(result["sources"], list)
        # BM25 doit remonter au moins 1 source pertinente
        assert len(result["sources"]) >= 1, "Aucune source trouvée pour 'indemnités licenciement'"

    @pytest.mark.asyncio
    async def test_bm25_finds_L1233_3_by_content(self, retriever):
        """
        L1233-3 est retrouvé via BM25 sur son contenu (difficultés économiques,
        suppression d'emploi). Les fichiers .md utilisent "L.1233-3" (avec point),
        donc le matching exact sur la ref "L1233-3" ne s'active pas — BM25 prend
        le relais.
        """
        faits_json = json.dumps({
            "faits": (
                "difficultés économiques suppression emploi motif économique "
                "sauvegarde compétitivité mutations technologiques"
            )
        })
        raw = await retriever.handle(faits_json)
        result = json.loads(raw)
        all_sources = result["sources"] + result.get("jurisprudences", [])
        ids = [s["id"] for s in all_sources]
        assert "L1233-3" in ids, (
            f"L1233-3 non trouvé via BM25 — sources retournées : {ids}"
        )

    @pytest.mark.asyncio
    async def test_empty_knowledge_base_returns_warning(self, tmp_path):
        """Si la base est vide, le retriever retourne un avertissement explicite."""
        mock_llm = MagicMock()
        mock_bus = MagicMock()
        agent = RetrieverAgent(llm_service=mock_llm, bus=mock_bus)
        agent._knowledge_base = tmp_path / "empty_kb"  # dossier inexistant
        agent.JOURNAL_DIR = tmp_path / "journals"

        raw = await agent.handle(json.dumps({"faits": "licenciement économique"}))
        result = json.loads(raw)
        assert result["sources"] == []
        assert "avertissement" in result

    @pytest.mark.asyncio
    async def test_non_trouve_lists_missing_refs(self, retriever):
        """Les références non trouvées dans la base sont listées dans 'non_trouve'."""
        faits_json = json.dumps({
            "faits": "voir article L9999-99 inexistant"
        })
        raw = await retriever.handle(faits_json)
        result = json.loads(raw)
        assert "non_trouve" in result
        assert "L9999-99" in result["non_trouve"]

    @pytest.mark.asyncio
    async def test_max_5_sources_returned(self, retriever):
        """Le retriever ne retourne jamais plus de 5 sources."""
        faits_json = json.dumps({
            "faits": "licenciement économique préavis indemnités reclassement L1233-1 L1233-2 L1233-3"
        })
        raw = await retriever.handle(faits_json)
        result = json.loads(raw)
        assert len(result["sources"]) <= 5


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  SMOKE TEST PIPELINE COMPLET — requiert Ollama / Gemma
# ═══════════════════════════════════════════════════════════════════════════════

SAMPLE_LETTRE = """
Madame, Monsieur,

Nous avons le regret de vous informer que votre poste de Chargé de clientèle
est supprimé dans le cadre d'un plan de sauvegarde de l'emploi (PSE)
engagé conformément aux articles L.1233-61 et suivants du Code du travail.

Ce licenciement est motivé par des difficultés économiques caractérisées
au sens de l'article L.1233-3, ayant entraîné la suppression de 45 postes.

Votre préavis d'une durée de deux mois débutera à la date de première
présentation de ce courrier. Les indemnités légales de licenciement vous
seront versées conformément aux dispositions de l'article L.1237-19.

Veuillez agréer, Madame, Monsieur, l'expression de nos salutations distinguées.
""".strip()


@pytest.mark.skipif(
    not _ollama_running(),
    reason="Ollama non disponible — smoke test ignoré",
)
@pytest.mark.asyncio
async def test_pipeline_smoke(tmp_path):
    """
    Smoke test bout-en-bout : lettre de licenciement → note Markdown avec disclaimer.
    Requiert Ollama avec un modèle disponible (ex: gemma2:2b ou gemma4:e4b).
    """
    from app.core.config import Config
    from app.core.engine import LucidEngine

    try:
        config = Config.load("config.yaml")
        engine = LucidEngine(config)
    except Exception as e:
        pytest.skip(f"Engine non initialisable : {e}")

    try:
        from app.agents.lucie_v1 import LegalPipeline

        pipeline = LegalPipeline(
            manager=engine.provider_manager,
            bus=engine.bus,
        )
        note = await pipeline.run(
            query="Analyser cette lettre de licenciement",
            document_text=SAMPLE_LETTRE,
        )

        assert isinstance(note, str), "La note doit être une chaîne"
        assert len(note) > 50, "La note semble trop courte"
        # Le disclaimer de fiabilité doit toujours être présent
        assert "Lucie V1" in note or "licenciement" in note.lower(), (
            "La note ne semble pas traiter du licenciement économique"
        )
        assert "À vérifier" in note or "avocat" in note.lower(), (
            "Le disclaimer de vérification est absent"
        )
    finally:
        try:
            engine.stop()
        except Exception:
            pass
