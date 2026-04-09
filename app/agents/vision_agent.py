"""
VisionAgent — Agent de vision multimodale pour Lucie.
Gère les requêtes d'analyse d'image et de capture d'écran.
"""

from typing import Any, Optional

from ..utils.logger import logger
from .base_agent import BaseAgent

# Mots-clés déclencheurs en français et anglais
_VISION_KEYWORDS = (
    "regarde",
    "regarder",
    "image",
    "capture",
    "écran",
    "ecran",
    "photo",
    "screenshot",
    "analyse cette image",
    "analyser",
    "voir",
    "vois",
    "montre",
    "montrer",
    "affiche",
    "afficher",
    "décris",
    "decrire",
    "qu'est-ce que tu vois",
    "que vois-tu",
)


class VisionAgent(BaseAgent):
    """
    Agent multimodal : analyse des images et captures d'écran.
    Utilise VisionService pour encoder et envoyer les images à Gemma 4.
    """

    name = "VisionAgent"
    description = "Analyse des images et capture d'écran via Gemma 4 multimodal"

    def __init__(self, llm_service: Any, bus: Any, vision_service: Any = None,
                 event_bus: Any = None, token: Optional[str] = None):
        super().__init__(
            name=self.name,
            llm_service=llm_service,
            bus=bus,
            event_bus=event_bus,
            token=token,
        )
        self.vision_service = vision_service
        self.stability = "experimental"

    def can_handle(self, query: str) -> bool:
        """
        Détecte les requêtes visuelles via mots-clés.
        """
        q = query.lower()
        return any(kw in q for kw in _VISION_KEYWORDS)

    async def handle(self, query: str, image_path: Optional[str] = None) -> str:
        """
        - Si image_path fourni → encode et analyse l'image.
        - Si demande de capture d'écran → capture + analyse.
        - Sinon → tente une analyse de l'écran courant.
        """
        if self.vision_service is None:
            logger.warning("VisionAgent: VisionService non configuré")
            return "Le service de vision n'est pas disponible."

        try:
            if image_path:
                logger.info(f"VisionAgent: analyse image {image_path}")
                image_b64 = await self.vision_service.encode_image(image_path)
            else:
                logger.info("VisionAgent: capture d'écran en cours…")
                image_b64 = await self.vision_service.capture_screen()

            prompt = self._build_vision_prompt(query)
            result = await self.vision_service.analyze_image(image_b64, prompt)
            logger.info(f"VisionAgent: analyse terminée ({len(result)} chars)")
            return result

        except FileNotFoundError as e:
            logger.error(f"VisionAgent: fichier introuvable — {e}")
            return f"Fichier image introuvable : {e}"
        except Exception as e:
            logger.error(f"VisionAgent: erreur — {e}")
            return f"Erreur lors de l'analyse visuelle : {e}"

    def _build_vision_prompt(self, query: str) -> str:
        """Construit le prompt d'analyse visuelle en français."""
        return (
            f"Tu es Lucie, un assistant IA local. "
            f"Analyse cette image et réponds en français à la demande suivante : {query}"
        )
