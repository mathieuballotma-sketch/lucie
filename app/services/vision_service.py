"""
VisionService — Gestion des images pour Lucie.
Encode, redimensionne (896x896 max, SigLIP natif Gemma 4), capture d'écran,
et analyse via Ollama multimodal.
"""

import asyncio
import base64
import io
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from ..utils.logger import logger

if TYPE_CHECKING:
    from ..providers.manager import ProviderManager


class VisionService:
    """
    Service de vision : encode images, capture l'écran, analyse via Gemma 4.
    """

    MAX_RESOLUTION = 896  # Résolution native SigLIP de Gemma 4
    JPEG_QUALITY = 85

    def __init__(self, provider_manager: "ProviderManager", vision_model: str = "gemma4:e4b"):
        self.provider_manager = provider_manager
        self.vision_model = vision_model
        logger.info(f"VisionService initialisé (modèle: {vision_model})")

    async def encode_image(self, image_path: str) -> str:
        """
        Charge un fichier image, redimensionne si > 896px, compresse JPEG 85%,
        retourne la chaîne base64.
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image introuvable : {image_path}")

        loop = asyncio.get_event_loop()
        image_data = await loop.run_in_executor(None, path.read_bytes)
        resized = await loop.run_in_executor(None, self._resize_image, image_data)
        return base64.b64encode(resized).decode("utf-8")

    async def capture_screen(self) -> str:
        """
        Capture l'écran via ScreenCaptureKit (fallback : screencapture CLI).
        Retourne le base64 JPEG de la capture redimensionnée.
        """
        loop = asyncio.get_event_loop()

        # Tentative ScreenCaptureKit (pyobjc)
        try:
            image_data = await loop.run_in_executor(None, self._capture_via_screencapturekit)
            if image_data:
                resized = await loop.run_in_executor(None, self._resize_image, image_data)
                return base64.b64encode(resized).decode("utf-8")
        except Exception as e:
            logger.debug(f"ScreenCaptureKit indisponible, fallback subprocess: {e}")

        # Fallback : screencapture CLI (toujours disponible sur macOS)
        return await self._capture_via_subprocess()

    def _capture_via_screencapturekit(self) -> Optional[bytes]:
        """
        Capture via pyobjc-framework-ScreenCaptureKit.
        Retourne None si non disponible.
        """
        try:
            import ScreenCaptureKit  # type: ignore[import]
            # API simplifiée — capture synchrone via CGWindowListCreateImage
            import Quartz  # type: ignore[import]
            import AppKit  # type: ignore[import]

            screen_rect = AppKit.NSScreen.mainScreen().frame()
            cg_image = Quartz.CGWindowListCreateImage(
                Quartz.CGRectInfinite,
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID,
                Quartz.kCGWindowImageDefault,
            )
            if cg_image is None:
                return None

            # Convertir CGImage → bytes PNG via NSBitmapImageRep
            ns_image = AppKit.NSImage.alloc().initWithCGImage_size_(
                cg_image, AppKit.NSZeroSize
            )
            bitmap_rep = AppKit.NSBitmapImageRep.imageRepWithData_(
                ns_image.TIFFRepresentation()
            )
            png_data = bitmap_rep.representationUsingType_properties_(
                AppKit.NSBitmapImageFileTypePNG, {}
            )
            return bytes(png_data)
        except ImportError:
            return None

    async def _capture_via_subprocess(self) -> str:
        """Fallback : screencapture -x CLI → JPEG → base64."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["screencapture", "-x", "-t", "jpg", tmp_path],
                    check=True,
                    capture_output=True,
                    timeout=10,
                ),
            )
            image_data = await loop.run_in_executor(None, Path(tmp_path).read_bytes)
            resized = await loop.run_in_executor(None, self._resize_image, image_data)
            return base64.b64encode(resized).decode("utf-8")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def analyze_image(self, image_base64: str, prompt: str) -> str:
        """
        Envoie image + prompt à Gemma 4 via Ollama.
        Utilise provider_manager.generate() avec le paramètre images.
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.provider_manager.generate(
                prompt=prompt,
                model=self.vision_model,
                images=[image_base64],
                max_tokens=1024,
            ),
        )
        return str(result)

    def _resize_image(self, image_data: bytes) -> bytes:
        """
        Redimensionne l'image si > 896px (garde le ratio), compresse JPEG 85%.
        Utilise Pillow.
        """
        try:
            from PIL import Image  # type: ignore[import]
        except ImportError:
            raise ImportError(
                "Pillow est requis pour VisionService. "
                "Installez-le avec : pip install Pillow"
            )

        with Image.open(io.BytesIO(image_data)) as img:
            # Convertir en RGB si nécessaire (ex: PNG RGBA)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            width, height = img.size
            if width > self.MAX_RESOLUTION or height > self.MAX_RESOLUTION:
                img.thumbnail(
                    (self.MAX_RESOLUTION, self.MAX_RESOLUTION),
                    Image.LANCZOS,
                )
                logger.debug(
                    f"Image redimensionnée : {width}x{height} → {img.size[0]}x{img.size[1]}"
                )

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=self.JPEG_QUALITY, optimize=True)
            return buf.getvalue()
