"""
Tests unitaires pour TextExtractorAgent.

Couverture :
  - can_handle() : mots-clés (écran, visible, texte, affiche, bouton…)
  - get_tools() : 3 outils attendus
  - _capture_text() : cache hit, OCR fallback, aucun texte détecté
  - _ocr_screen() : subprocess mocké + pytesseract mocké
  - _tool_get_screen_text() : appelle _capture_text
  - _tool_get_text_at_position() / _tool_get_ui_element_info() : stubs
  - handle() : appelle _tool_get_screen_text

Ces tests ne nécessitent PAS macOS, AppKit, ni pytesseract réel.
"""
from __future__ import annotations

import sys
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Stub les dépendances macOS avant l'import de l'agent
for mod in ("AppKit", "ApplicationServices"):
    sys.modules.setdefault(mod, MagicMock())

# Stub pytesseract et PIL
sys.modules.setdefault("pytesseract", MagicMock())
sys.modules.setdefault("PIL", MagicMock())
sys.modules.setdefault("PIL.Image", MagicMock())

from app.agents.vision.text_extractor import TextExtractorAgent


# ── Fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture
def agent() -> TextExtractorAgent:
    """TextExtractorAgent avec dépendances macOS mockées."""
    llm = MagicMock()
    bus = MagicMock()
    config: dict[str, Any] = {
        "use_ocr_fallback": True,
        "min_text_length": 10,
        "cache_duration": 5,
    }
    with patch.object(TextExtractorAgent, "_check_accessibility", return_value=False):
        return TextExtractorAgent(llm, bus, config)


# ── can_handle ─────────────────────────────────────────────────────────────────


def test_can_handle_ecran(agent: TextExtractorAgent) -> None:
    assert agent.can_handle("qu'est-ce qu'il y a sur l'écran") is True


def test_can_handle_visible(agent: TextExtractorAgent) -> None:
    assert agent.can_handle("lis le texte visible") is True


def test_can_handle_texte(agent: TextExtractorAgent) -> None:
    assert agent.can_handle("extrais le texte affiché") is True


def test_can_handle_affiche(agent: TextExtractorAgent) -> None:
    assert agent.can_handle("que vois-je affiché") is True


def test_can_handle_bouton(agent: TextExtractorAgent) -> None:
    assert agent.can_handle("quel bouton est disponible") is True


def test_can_handle_image(agent: TextExtractorAgent) -> None:
    assert agent.can_handle("décris l'image à l'écran") is True


def test_can_handle_negatif_rappel(agent: TextExtractorAgent) -> None:
    assert agent.can_handle("crée un rappel demain matin") is False


def test_can_handle_negatif_meteo(agent: TextExtractorAgent) -> None:
    assert agent.can_handle("quelle est la météo à Paris") is False


# ── get_tools ──────────────────────────────────────────────────────────────────


def test_get_tools_count(agent: TextExtractorAgent) -> None:
    tools = agent.get_tools()
    assert len(tools) == 3


def test_get_tools_names(agent: TextExtractorAgent) -> None:
    names = {t.name for t in agent.get_tools()}
    assert "get_screen_text" in names
    assert "get_text_at_position" in names
    assert "get_ui_element_info" in names


# ── _capture_text ──────────────────────────────────────────────────────────────


def test_capture_text_cache_hit(agent: TextExtractorAgent) -> None:
    """Si le cache est récent, retourne la valeur cached sans appeler OCR."""
    agent.last_text = "Texte en cache depuis moins de 5 secondes"
    agent.last_capture_time = time.time()  # maintenant → dans la fenêtre du cache

    with patch.object(agent, "_ocr_screen") as mock_ocr:
        result = agent._capture_text()

    mock_ocr.assert_not_called()
    assert result == agent.last_text


def test_capture_text_no_text(agent: TextExtractorAgent) -> None:
    """Retourne le message par défaut si OCR ne trouve rien."""
    agent.accessibility_available = False
    agent.last_text = ""
    agent.last_capture_time = 0.0

    with patch.object(agent, "_ocr_screen", return_value=None):
        result = agent._capture_text()
    assert "Aucun texte" in result


def test_capture_text_ocr_short_text(agent: TextExtractorAgent) -> None:
    """Retourne le texte OCR même s'il est court (< min_text_length)."""
    agent.accessibility_available = False
    agent.last_text = ""
    agent.last_capture_time = 0.0

    with patch.object(agent, "_ocr_screen", return_value="Court"):
        result = agent._capture_text()
    assert result == "Court"


def test_capture_text_ocr_long_text(agent: TextExtractorAgent) -> None:
    """Met à jour le cache pour les textes longs."""
    agent.accessibility_available = False
    agent.last_text = ""
    agent.last_capture_time = 0.0
    long_text = "A" * 100

    with patch.object(agent, "_ocr_screen", return_value=long_text):
        result = agent._capture_text()
    assert result == long_text
    assert agent.last_text == long_text


# ── _ocr_screen ────────────────────────────────────────────────────────────────


def test_ocr_screen_returns_text(agent: TextExtractorAgent) -> None:
    """_ocr_screen() appelle screencapture + pytesseract et retourne le texte."""
    mock_image = MagicMock()

    with patch("app.agents.vision.text_extractor.subprocess.run"):
        with patch("app.agents.vision.text_extractor.Image.open", return_value=mock_image):
            with patch("app.agents.vision.text_extractor.pytesseract.image_to_string", return_value="Texte OCR") as mock_ocr:
                result = agent._ocr_screen()
    assert result == "Texte OCR"


def test_ocr_screen_exception_returns_none(agent: TextExtractorAgent) -> None:
    """_ocr_screen() retourne None si screencapture échoue."""
    with patch("app.agents.vision.text_extractor.subprocess.run", side_effect=Exception("permission denied")):
        result = agent._ocr_screen()
    assert result is None


# ── _tool_get_screen_text ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_tool_get_screen_text_calls_capture(agent: TextExtractorAgent) -> None:
    with patch.object(agent, "_capture_text", return_value="Texte capturé") as mock_cap:
        result = await agent._tool_get_screen_text()
    mock_cap.assert_called_once()
    assert result == "Texte capturé"


# ── _tool stubs ────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_tool_get_text_at_position_stub(agent: TextExtractorAgent) -> None:
    result = await agent._tool_get_text_at_position(x=100, y=200)
    assert "non encore implémentée" in result


@pytest.mark.anyio
async def test_tool_get_ui_element_info_stub(agent: TextExtractorAgent) -> None:
    result = await agent._tool_get_ui_element_info()
    assert "non encore implémentée" in result


# ── handle ─────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_handle_appelle_get_screen_text(agent: TextExtractorAgent) -> None:
    with patch.object(agent, "_tool_get_screen_text", return_value="Texte écran") as mock_tool:
        result = await agent.handle("lis l'écran")
    mock_tool.assert_called_once()
    assert result == "Texte écran"
