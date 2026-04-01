"""Tests unitaires — ModelIntegrityChecker (SEC-QW-01)."""

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from app.security.model_integrity import ModelIntegrityChecker, IntegrityError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_model_file(directory: Path, name: str, content: bytes = b"fake model data") -> Path:
    path = directory / name
    path.write_bytes(content)
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_hashes_file(directory: Path, models: dict) -> Path:
    hashes_file = directory / "model_hashes.json"
    hashes_file.write_text(json.dumps({"models": models}), encoding="utf-8")
    return hashes_file


# ---------------------------------------------------------------------------
# sha256_file
# ---------------------------------------------------------------------------

class TestSha256File:
    def test_known_content(self, tmp_path):
        data = b"hello world"
        f = tmp_path / "test.bin"
        f.write_bytes(data)
        assert ModelIntegrityChecker.sha256_file(f) == _sha256(data)

    def test_large_file_chunked(self, tmp_path):
        """Vérifie que le hash par blocs correspond au hash d'un coup."""
        data = b"x" * (3 << 20)  # 3 Mo
        f = tmp_path / "big.bin"
        f.write_bytes(data)
        assert ModelIntegrityChecker.sha256_file(f) == _sha256(data)

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        assert ModelIntegrityChecker.sha256_file(f) == _sha256(b"")


# ---------------------------------------------------------------------------
# _load_hashes
# ---------------------------------------------------------------------------

class TestLoadHashes:
    def test_loads_valid_file(self, tmp_path):
        hf = _make_hashes_file(tmp_path, {"model_a": "abc123"})
        checker = ModelIntegrityChecker(hashes_file=hf, ollama_dir=tmp_path)
        assert checker._known_hashes == {"model_a": "abc123"}

    def test_missing_file_no_crash(self, tmp_path):
        checker = ModelIntegrityChecker(
            hashes_file=tmp_path / "nonexistent.json",
            ollama_dir=tmp_path,
        )
        assert checker._known_hashes == {}

    def test_invalid_json_no_crash(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        checker = ModelIntegrityChecker(hashes_file=bad, ollama_dir=tmp_path)
        assert checker._known_hashes == {}


# ---------------------------------------------------------------------------
# verify_model
# ---------------------------------------------------------------------------

class TestVerifyModel:
    def _checker_with_model(self, tmp_path, model_name, content, registered_hash=None):
        model_file = _write_model_file(tmp_path, model_name.replace(":", "_") + ".gguf", content)
        actual_hash = _sha256(content)
        models = {model_name: registered_hash if registered_hash is not None else actual_hash}
        hf = _make_hashes_file(tmp_path, models)
        # Patch _find_model_file via sous-classe légère
        checker = ModelIntegrityChecker(hashes_file=hf, ollama_dir=tmp_path)
        checker._find_model_file = lambda _: model_file  # bypass détection réelle
        return checker, model_file, actual_hash

    def test_ok_when_hash_matches(self, tmp_path):
        checker, _, _ = self._checker_with_model(tmp_path, "mymodel:7b", b"data")
        result = checker.verify_model("mymodel:7b")
        assert result["status"] == "ok"

    def test_tampered_when_hash_differs(self, tmp_path):
        checker, model_file, _ = self._checker_with_model(
            tmp_path, "mymodel:7b", b"data", registered_hash="deadbeef" * 8
        )
        result = checker.verify_model("mymodel:7b")
        assert result["status"] == "tampered"
        assert result["expected"] == "deadbeef" * 8

    def test_not_registered_when_no_entry(self, tmp_path):
        model_file = _write_model_file(tmp_path, "unknown.gguf", b"content")
        hf = _make_hashes_file(tmp_path, {})
        checker = ModelIntegrityChecker(hashes_file=hf, ollama_dir=tmp_path)
        checker._find_model_file = lambda _: model_file
        result = checker.verify_model("unknown:latest")
        assert result["status"] == "not_registered"
        assert result["expected"] is None
        assert result["actual"] is not None

    def test_missing_from_disk(self, tmp_path):
        hf = _make_hashes_file(tmp_path, {"ghost:7b": "abc"})
        checker = ModelIntegrityChecker(hashes_file=hf, ollama_dir=tmp_path)
        checker._find_model_file = lambda _: None
        result = checker.verify_model("ghost:7b")
        assert result["status"] == "missing_from_disk"
        assert result["actual"] is None


# ---------------------------------------------------------------------------
# verify_all
# ---------------------------------------------------------------------------

class TestVerifyAll:
    def test_empty_hashes_returns_empty_summary(self, tmp_path):
        hf = _make_hashes_file(tmp_path, {})
        checker = ModelIntegrityChecker(hashes_file=hf, ollama_dir=tmp_path)
        summary = checker.verify_all()
        assert summary["tampered"] == []
        assert summary["ok"] == []

    def test_mixed_results(self, tmp_path):
        content_a = b"model_a_bytes"
        content_b = b"model_b_bytes"
        file_a = _write_model_file(tmp_path, "model_a.gguf", content_a)
        file_b = _write_model_file(tmp_path, "model_b.gguf", content_b)

        models = {
            "model_a": _sha256(content_a),   # OK
            "model_b": "wronghash" * 4,       # tampered
        }
        hf = _make_hashes_file(tmp_path, models)
        checker = ModelIntegrityChecker(hashes_file=hf, ollama_dir=tmp_path)

        def find(name):
            return file_a if "model_a" in name else file_b

        checker._find_model_file = find
        summary = checker.verify_all()

        assert "model_a" in summary["ok"]
        assert "model_b" in summary["tampered"]


# ---------------------------------------------------------------------------
# register_model
# ---------------------------------------------------------------------------

class TestRegisterModel:
    def test_register_creates_entry(self, tmp_path):
        hf = _make_hashes_file(tmp_path, {})
        checker = ModelIntegrityChecker(hashes_file=hf, ollama_dir=tmp_path)
        model_file = _write_model_file(tmp_path, "new_model.gguf", b"model bytes")
        returned_hash = checker.register_model("new:model", model_path=model_file)
        assert returned_hash == _sha256(b"model bytes")
        # Vérifie la persistance
        reloaded = ModelIntegrityChecker(hashes_file=hf, ollama_dir=tmp_path)
        assert reloaded._known_hashes.get("new:model") == returned_hash

    def test_register_missing_file_raises(self, tmp_path):
        hf = _make_hashes_file(tmp_path, {})
        checker = ModelIntegrityChecker(hashes_file=hf, ollama_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            checker.register_model("ghost:7b", model_path=tmp_path / "nonexistent.gguf")
