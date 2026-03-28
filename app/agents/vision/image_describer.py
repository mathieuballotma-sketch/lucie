"""
Agent spécialisé dans la description d'images à l'écran.
Utilise un modèle de vision-langage léger (moondream) si disponible.
"""

import subprocess
import tempfile
from typing import Any, List, Optional

from pydantic.v1 import BaseModel, Field as PydField

from ...agents.base_agent import BaseAgent, Tool
from ...utils.logger import logger

try:
    MOONDREAM_AVAILABLE = True
except ImportError:
    MOONDREAM_AVAILABLE = False
    logger.warning(
        "Module 'moondream' non disponible. L'agent ImageDescriber utilisera un fallback simple."
    )


# ── Contrats pydantic pour les outils ──
class DescribeScreenContract(BaseModel):
    pass

class DescribeImageAtPositionContract(BaseModel):
    x: Optional[int] = PydField(None, description="Coordonnée X (optionnel)")
    y: Optional[int] = PydField(None, description="Coordonnée Y (optionnel)")


class ImageDescriberAgent(BaseAgent):
    """
    Agent capable de décrire le contenu des images affichées à l'écran.
    Utilise un VLM (Vision-Language Model) pour générer des descriptions textuelles.
    """

    def __init__(self, llm_service: Any, bus: Any, config: Any) -> None:
        super().__init__("ImageDescriberAgent", llm_service, bus)
        self.model: Any = None
        if MOONDREAM_AVAILABLE:
            try:
                # Charger le modèle (à ajuster selon la bibliothèque)
                # self.model = md.vl(model='moondream2')
                logger.info("Modèle Moondream chargé (simulé pour l'instant)")
            except Exception as e:
                logger.error(f"Erreur chargement Moondream: {e}")
        self.use_fallback = config.get("use_fallback", True)

    def get_tools(self) -> List[Tool]:
        return [
            Tool(
                name="describe_screen",
                description="Décrit le contenu visuel général de l'écran (ce qu'on voit).",
                contract=DescribeScreenContract,
            ),
            Tool(
                name="describe_image_at_position",
                description="Décrit l'image à une position donnée (x, y) ou sous la souris.",
                contract=DescribeImageAtPositionContract,
            ),
        ]

    def _tool_describe_screen(self) -> str:
        return self._describe_screen()

    def _tool_describe_image_at_position(self, x: Optional[int] = None, y: Optional[int] = None) -> str:
        return self._describe_image_at_position(x, y)

    def _capture_screen(self) -> Optional[str]:
        """Capture l'écran et retourne le chemin du fichier temporaire."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run(
                ["screencapture", "-x", tmp_path], check=True, capture_output=True
            )
            return tmp_path
        except Exception as e:
            logger.error(f"Erreur capture écran: {e}")
            return None

    def _describe_screen(self) -> str:
        img_path = self._capture_screen()
        if not img_path:
            return "Impossible de capturer l'écran."

        if MOONDREAM_AVAILABLE and self.model:
            # Utiliser Moondream pour décrire
            try:
                description = "Description simulée : L'écran affiche plusieurs fenêtres, du texte et des icônes."  # noqa: E501
                return description
            except Exception as e:
                logger.error(f"Erreur Moondream: {e}")
                if not self.use_fallback:
                    return f"Erreur de description: {e}"

        # Fallback simple
        return "L'écran contient du texte et des éléments graphiques (description limitée par manque de modèle VLM)."  # noqa: E501

    def _describe_image_at_position(self, x: Optional[int] = None, y: Optional[int] = None) -> str:
        # Pour l'instant, on ne capture qu'une région, mais c'est plus
        # complexe.
        return "Fonction non implémentée."

    def can_handle(self, query: str) -> bool:
        keywords = ["image", "photo", "voir", "affiche", "dessin", "graphique"]
        return any(kw in query.lower() for kw in keywords)

    async def handle(self, query: str) -> str:
        return self._tool_describe_screen()
