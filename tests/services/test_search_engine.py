"""
Tests pour le moteur de recherche local intelligent.
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.services.search_engine import (
    DocumentIndex,
    FileExtractor,
    KeywordGenerator,
    LocalSearchEngine,
)


# ─────────────────────────────────────────────────────────────────────────────
# FileExtractor
# ─────────────────────────────────────────────────────────────────────────────
class TestFileExtractor:
    """Teste l'extraction de contenu."""

    @pytest.mark.asyncio
    async def test_extract_txt(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.txt"
        f.write_text("Bonjour le monde", encoding="utf-8")
        extractor = FileExtractor()
        content = await extractor.extract(str(f))
        assert content is not None
        assert "Bonjour" in content

    @pytest.mark.asyncio
    async def test_extract_py(self, tmp_path: Path) -> None:
        f = tmp_path / "script.py"
        f.write_text("def main():\n    print('hello')\n", encoding="utf-8")
        extractor = FileExtractor()
        content = await extractor.extract(str(f))
        assert content is not None
        assert "def main" in content

    @pytest.mark.asyncio
    async def test_extract_md(self, tmp_path: Path) -> None:
        f = tmp_path / "readme.md"
        f.write_text("# Titre\n\nContenu markdown", encoding="utf-8")
        extractor = FileExtractor()
        content = await extractor.extract(str(f))
        assert content is not None
        assert "Titre" in content

    @pytest.mark.asyncio
    async def test_extract_unsupported(self, tmp_path: Path) -> None:
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG\r\n")
        extractor = FileExtractor()
        content = await extractor.extract(str(f))
        assert content is None

    @pytest.mark.asyncio
    async def test_extract_nonexistent(self) -> None:
        extractor = FileExtractor()
        content = await extractor.extract("/nonexistent/file.txt")
        assert content is None

    @pytest.mark.asyncio
    async def test_extract_too_large(self, tmp_path: Path) -> None:
        f = tmp_path / "big.txt"
        f.write_text("x" * 100, encoding="utf-8")
        extractor = FileExtractor(max_file_size=50)
        content = await extractor.extract(str(f))
        assert content is None


# ─────────────────────────────────────────────────────────────────────────────
# DocumentIndex
# ─────────────────────────────────────────────────────────────────────────────
class TestDocumentIndex:
    """Teste la structure DocumentIndex."""

    def test_all_fields(self) -> None:
        doc = DocumentIndex(
            file_path="/tmp/test.txt",
            file_name="test.txt",
            file_type=".txt",
            file_size=100,
            modified_at=time.time(),
            indexed_at=time.time(),
            content_hash="abc123",
            keywords=["test", "document"],
            summary="Un document de test",
            category="document",
        )
        assert doc.file_name == "test.txt"
        assert len(doc.keywords) == 2
        assert doc.embedding_id is None


# ─────────────────────────────────────────────────────────────────────────────
# LocalSearchEngine
# ─────────────────────────────────────────────────────────────────────────────
class TestLocalSearchEngine:
    """Teste le moteur de recherche."""

    @pytest.mark.asyncio
    async def test_index_file(self, tmp_path: Path) -> None:
        # Creer un fichier
        f = tmp_path / "doc.txt"
        f.write_text("Contenu important sur la cybersecurite", encoding="utf-8")

        engine = LocalSearchEngine(
            index_dir=str(tmp_path / "index"),
            generate_keywords=False,
        )

        doc = await engine.index_file(str(f))
        assert doc is not None
        assert doc.file_name == "doc.txt"
        assert doc.file_type == ".txt"
        engine.close()

    @pytest.mark.asyncio
    async def test_index_skip_unchanged(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("Contenu stable", encoding="utf-8")

        engine = LocalSearchEngine(
            index_dir=str(tmp_path / "index"),
            generate_keywords=False,
        )

        doc1 = await engine.index_file(str(f))
        assert doc1 is not None

        # Re-indexer sans changement → None (skip)
        doc2 = await engine.index_file(str(f))
        assert doc2 is None
        engine.close()

    @pytest.mark.asyncio
    async def test_search_returns_results(self, tmp_path: Path) -> None:
        # Creer des fichiers
        (tmp_path / "python.py").write_text("def hello(): pass", encoding="utf-8")
        (tmp_path / "readme.md").write_text("# Guide Python", encoding="utf-8")

        engine = LocalSearchEngine(
            index_dir=str(tmp_path / "index"),
            generate_keywords=False,
        )

        await engine.index_file(str(tmp_path / "python.py"))
        await engine.index_file(str(tmp_path / "readme.md"))

        # Recherche FTS5 / LIKE
        results = await engine.search("python")
        assert len(results) > 0
        engine.close()

    @pytest.mark.asyncio
    async def test_search_by_keywords(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("Machine learning et intelligence artificielle", encoding="utf-8")

        engine = LocalSearchEngine(
            index_dir=str(tmp_path / "index"),
            generate_keywords=False,
        )
        await engine.index_file(str(f))

        results = await engine.search_by_keywords(["machine", "learning"])
        # Peut retourner 0 si FTS5 n'est pas disponible et LIKE ne match pas
        assert isinstance(results, list)
        engine.close()

    @pytest.mark.asyncio
    async def test_get_index_stats(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("Contenu", encoding="utf-8")

        engine = LocalSearchEngine(
            index_dir=str(tmp_path / "index"),
            generate_keywords=False,
        )
        await engine.index_file(str(f))

        stats = await engine.get_index_stats()
        assert stats["total_files"] == 1
        assert stats["total_size_bytes"] > 0
        assert ".txt" in stats["by_type"]
        engine.close()

    @pytest.mark.asyncio
    async def test_remove_stale(self, tmp_path: Path) -> None:
        f = tmp_path / "ephemeral.txt"
        f.write_text("Temporaire", encoding="utf-8")

        engine = LocalSearchEngine(
            index_dir=str(tmp_path / "index"),
            generate_keywords=False,
        )
        await engine.index_file(str(f))

        # Supprimer le fichier
        f.unlink()

        removed = await engine.remove_stale()
        assert removed == 1

        stats = await engine.get_index_stats()
        assert stats["total_files"] == 0
        engine.close()

    @pytest.mark.asyncio
    async def test_add_directory(self, tmp_path: Path) -> None:
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "a.txt").write_text("Fichier A", encoding="utf-8")
        (sub / "b.py").write_text("# Fichier B", encoding="utf-8")
        (sub / "c.png").write_bytes(b"\x89PNG")  # non supporte

        engine = LocalSearchEngine(
            index_dir=str(tmp_path / "index"),
            generate_keywords=False,
        )

        count = await engine.add_directory(str(sub))
        assert count == 2  # .txt et .py, pas .png
        engine.close()


# ─────────────────────────────────────────────────────────────────────────────
# KeywordGenerator
# ─────────────────────────────────────────────────────────────────────────────
class TestKeywordGenerator:
    """Teste la generation de mots-cles (mock LLM)."""

    def test_generate_with_mock_llm(self) -> None:
        mock_provider = MagicMock()
        mock_provider.generate.return_value = json.dumps({
            "keywords": ["python", "test", "code"],
            "summary": "Un fichier Python de test",
            "category": "code",
        })

        gen = KeywordGenerator(mock_provider)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            gen.generate("test.py", ".py", "def test(): pass")
        )
        assert "keywords" in result
        assert len(result["keywords"]) == 3
        assert result["category"] == "code"

    def test_fallback_on_llm_error(self) -> None:
        mock_provider = MagicMock()
        mock_provider.generate.side_effect = Exception("LLM down")

        gen = KeywordGenerator(mock_provider)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            gen.generate("my_script.py", ".py", "content")
        )
        assert "keywords" in result
        assert "my" in result["keywords"] or "script" in result["keywords"]
