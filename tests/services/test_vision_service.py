"""
Tests pour VisionService.
Toutes les dépendances système (Ollama, screencapture) sont mockées.
"""

import asyncio
import base64
import io
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Créer une image PNG 100x100 en mémoire pour les tests
def _make_test_png(width: int = 100, height: int = 100) -> bytes:
    """Génère un PNG en mémoire via PIL."""
    from PIL import Image
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_test_png_file(width: int = 100, height: int = 100) -> str:
    """Crée un fichier PNG temporaire et retourne son chemin."""
    data = _make_test_png(width, height)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(data)
        return f.name


@pytest.fixture
def mock_provider():
    """ProviderManager mocké — ne contacte jamais Ollama."""
    provider = MagicMock()
    provider.generate.return_value = "Analyse : image rouge unie."
    return provider


@pytest.fixture
def vision_service(mock_provider):
    """VisionService avec provider mocké."""
    from app.services.vision_service import VisionService
    return VisionService(provider_manager=mock_provider, vision_model="gemma4:e4b")


# ─────────────────────────────────────────────────────────────────────────────
# encode_image
# ─────────────────────────────────────────────────────────────────────────────

class TestEncodeImage:
    def test_encode_image_produces_valid_base64(self, vision_service):
        """encode_image retourne du base64 valide."""
        png_path = _make_test_png_file(100, 100)
        try:
            result = asyncio.run(vision_service.encode_image(png_path))
            # Doit être décodable
            decoded = base64.b64decode(result)
            assert len(decoded) > 0
        finally:
            os.unlink(png_path)

    def test_encode_image_returns_string(self, vision_service):
        """encode_image retourne une str (pas bytes)."""
        png_path = _make_test_png_file()
        try:
            result = asyncio.run(vision_service.encode_image(png_path))
            assert isinstance(result, str)
        finally:
            os.unlink(png_path)

    def test_encode_image_file_not_found(self, vision_service):
        """encode_image lève FileNotFoundError si le fichier n'existe pas."""
        with pytest.raises(FileNotFoundError):
            asyncio.run(vision_service.encode_image("/tmp/inexistant_lucie_test.png"))

    def test_encode_image_jpeg_output(self, vision_service):
        """encode_image produit un JPEG (magic bytes FF D8)."""
        png_path = _make_test_png_file(100, 100)
        try:
            result = asyncio.run(vision_service.encode_image(png_path))
            decoded = base64.b64decode(result)
            # JPEG magic bytes
            assert decoded[:2] == b"\xff\xd8", "L'image encodée n'est pas un JPEG"
        finally:
            os.unlink(png_path)


# ─────────────────────────────────────────────────────────────────────────────
# _resize_image
# ─────────────────────────────────────────────────────────────────────────────

class TestResizeImage:
    def test_large_image_is_resized(self, vision_service):
        """Une image 2000x1000 est redimensionnée à max 896px."""
        large_png = _make_test_png(2000, 1000)
        resized = vision_service._resize_image(large_png)

        from PIL import Image
        img = Image.open(io.BytesIO(resized))
        w, h = img.size
        assert w <= vision_service.MAX_RESOLUTION
        assert h <= vision_service.MAX_RESOLUTION

    def test_small_image_unchanged_dimensions(self, vision_service):
        """Une image 100x100 ne dépasse pas 896px (mais peut changer de format)."""
        small_png = _make_test_png(100, 100)
        resized = vision_service._resize_image(small_png)

        from PIL import Image
        img = Image.open(io.BytesIO(resized))
        w, h = img.size
        assert w <= vision_service.MAX_RESOLUTION
        assert h <= vision_service.MAX_RESOLUTION
        assert w == 100  # Dimensions préservées pour petite image
        assert h == 100

    def test_resize_preserves_aspect_ratio(self, vision_service):
        """Le ratio est conservé lors du redimensionnement."""
        # Image 1600x800 (ratio 2:1)
        wide_png = _make_test_png(1600, 800)
        resized = vision_service._resize_image(wide_png)

        from PIL import Image
        img = Image.open(io.BytesIO(resized))
        w, h = img.size
        # Après resize: 896x448 (ratio 2:1 préservé)
        ratio_original = 1600 / 800
        ratio_resized = w / h
        assert abs(ratio_original - ratio_resized) < 0.05

    def test_resize_returns_jpeg(self, vision_service):
        """_resize_image retourne toujours un JPEG."""
        png_data = _make_test_png(50, 50)
        result = vision_service._resize_image(png_data)
        assert result[:2] == b"\xff\xd8"

    def test_square_large_image(self, vision_service):
        """Image carrée 2000x2000 → 896x896."""
        square_png = _make_test_png(2000, 2000)
        resized = vision_service._resize_image(square_png)

        from PIL import Image
        img = Image.open(io.BytesIO(resized))
        w, h = img.size
        assert w == 896
        assert h == 896

    def test_exact_max_resolution(self, vision_service):
        """Une image exactement 896x896 n'est pas agrandie."""
        exact_png = _make_test_png(896, 896)
        resized = vision_service._resize_image(exact_png)

        from PIL import Image
        img = Image.open(io.BytesIO(resized))
        w, h = img.size
        assert w == 896
        assert h == 896


# ─────────────────────────────────────────────────────────────────────────────
# analyze_image
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzeImage:
    def test_analyze_calls_provider_generate(self, vision_service, mock_provider):
        """analyze_image appelle provider_manager.generate() avec images."""
        fake_b64 = base64.b64encode(b"fake_image_data").decode()
        result = asyncio.run(vision_service.analyze_image(fake_b64, "Décris cette image"))

        mock_provider.generate.assert_called_once()
        call_kwargs = mock_provider.generate.call_args.kwargs
        assert "images" in call_kwargs
        assert call_kwargs["images"] == [fake_b64]

    def test_analyze_returns_string(self, vision_service, mock_provider):
        """analyze_image retourne une str."""
        fake_b64 = base64.b64encode(b"fake").decode()
        result = asyncio.run(vision_service.analyze_image(fake_b64, "Test"))
        assert isinstance(result, str)
        assert result == "Analyse : image rouge unie."

    def test_analyze_passes_correct_model(self, vision_service, mock_provider):
        """analyze_image utilise vision_model configuré."""
        fake_b64 = base64.b64encode(b"x").decode()
        asyncio.run(vision_service.analyze_image(fake_b64, "Test"))
        call_kwargs = mock_provider.generate.call_args.kwargs
        assert call_kwargs.get("model") == "gemma4:e4b"


# ─────────────────────────────────────────────────────────────────────────────
# capture_screen (fallback subprocess)
# ─────────────────────────────────────────────────────────────────────────────

class TestCaptureScreen:
    def test_capture_screen_returns_base64(self, vision_service):
        """capture_screen retourne du base64 valide (fallback subprocess mocké)."""
        fake_jpg = _make_test_png(200, 150)  # utilise PNG mais OK pour le test

        with patch("app.services.vision_service.subprocess.run") as mock_subproc, \
             patch("pathlib.Path.read_bytes", return_value=fake_jpg), \
             patch("pathlib.Path.unlink"):
            mock_subproc.return_value = MagicMock(returncode=0)

            # S'assurer que ScreenCaptureKit n'est pas dispo
            with patch.object(vision_service, "_capture_via_screencapturekit", return_value=None):
                result = asyncio.run(vision_service.capture_screen())

            assert isinstance(result, str)
            decoded = base64.b64decode(result)
            assert len(decoded) > 0
