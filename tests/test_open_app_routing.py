"""
Tests de couverture pour le routing "ouvre app" — cas nominaux et cas limites.

Couvre :
- Orthographe correcte : "ouvre mail", "lance mail"
- Typos (distance Levenshtein 1) : "ouvr mail", "lanc mail"
- Langage naturel bruité : "ouvre moi mes mails", "ouvre l'application Mail"
- Verbes alternatifs : "va sur mail", "démarre mail", "affiche mail"
- Extraction du nom d'app dans _route_simple_action
- _fuzzy_keyword_match dans PathRouter
- _parse_open_application dans ComputerControlAgent
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

# ── Stubs macOS pour tests hors macOS ─────────────────────────────────────────

pyautogui_mock = MagicMock()
sys.modules.setdefault("pyautogui", pyautogui_mock)


# ── PathRouter — fuzzy matching ────────────────────────────────────────────────


from app.brain.cortex.router import PathRouter, _levenshtein


class TestLevenshtein:
    def test_identical(self):
        assert _levenshtein("ouvre", "ouvre") == 0

    def test_one_deletion(self):
        assert _levenshtein("ouvr", "ouvre") == 1

    def test_one_substitution(self):
        assert _levenshtein("ouvze", "ouvre") == 1

    def test_two_edits(self):
        assert _levenshtein("ouvr", "lance") > 1

    def test_empty(self):
        assert _levenshtein("", "mail") == 4
        assert _levenshtein("mail", "") == 4


class TestPathRouterFuzzy:
    def setup_method(self):
        self.router = PathRouter()

    def test_exact_ouvre(self):
        result = self.router._keyword_match("ouvre mail")
        assert result == "computer_control"

    def test_fuzzy_ouvr_typo(self):
        result = self.router._fuzzy_keyword_match("ouvr mail")
        assert result == "computer_control"

    def test_fuzzy_lanc_typo(self):
        result = self.router._fuzzy_keyword_match("lanc mail")
        assert result == "computer_control"

    def test_fuzzy_no_false_positive_short_word(self):
        # "ma" est trop court → pas de fuzzy match sur "mail" (len diff > 1)
        result = self.router._fuzzy_keyword_match("ma fenêtre")
        # Ne doit pas matcher "son" ou "don"
        # Résultat acceptable : None ou reminder mais PAS computer_control via "son"
        # Ce test vérifie que les mots très courts ne déclenchent pas de faux positifs
        assert result != "computer_control"

    def test_route_ouvr_mail_returns_fast_path(self):
        """Un typo 'ouvr' doit quand même router vers computer_control via fuzzy."""
        result = self.router.route("ouvr mail")
        assert result.agent == "computer_control"
        assert result.via_fast_path is True

    def test_route_exact_ouvre_mail(self):
        result = self.router.route("ouvre mail")
        assert result.agent == "computer_control"
        assert result.via_fast_path is True

    def test_route_va_sur_keyword(self):
        """'va sur' est un nouveau keyword multi-mots."""
        result = self.router._keyword_match("va sur mail")
        assert result == "computer_control"


# ── ExecutionEngine — _extract_app_name ───────────────────────────────────────


from app.brain.cortex.execution_engine import ExecutionEngine


class TestExtractAppName:
    """Teste _extract_app_name en isolation (ne nécessite pas un Engine complet)."""

    def setup_method(self):
        # Créer une instance minimale
        self.engine = object.__new__(ExecutionEngine)

    def test_simple_mail(self):
        assert self.engine._extract_app_name("mail") == "Mail"

    def test_moi_mes_mails(self):
        assert self.engine._extract_app_name("moi mes mails") == "Mail"

    def test_lapp_mail(self):
        assert self.engine._extract_app_name("l'app mail") == "Mail"

    def test_lapplication_mail(self):
        assert self.engine._extract_app_name("l'application mail") == "Mail"

    def test_safari(self):
        assert self.engine._extract_app_name("safari") == "Safari"

    def test_notes(self):
        assert self.engine._extract_app_name("notes") == "Notes"

    def test_chrome(self):
        assert self.engine._extract_app_name("chrome") == "Google Chrome"

    def test_unknown_app(self):
        result = self.engine._extract_app_name("monapp")
        assert result is not None
        assert result.lower() == "monapp"  # retourne tel quel (capitalisé ou non)


class TestRouteSimpleActionOpenApp:
    """Teste _route_simple_action pour l'extraction du bon app_name."""

    def setup_method(self):
        self.engine = object.__new__(ExecutionEngine)

    def _route(self, query):
        return self.engine._route_simple_action(query)

    def test_ouvre_mail(self):
        result = self._route("ouvre mail")
        assert result is not None
        agent, action = result
        assert agent == "ComputerControlAgent"
        assert action["tool"] == "open_application"
        assert action["parameters"]["app_name"] == "Mail"

    def test_ouvre_moi_mes_mails(self):
        result = self._route("ouvre moi mes mails")
        assert result is not None
        _, action = result
        assert action["parameters"]["app_name"] == "Mail"

    def test_lance_lapp_mail(self):
        result = self._route("lance l'app mail")
        assert result is not None
        _, action = result
        assert action["parameters"]["app_name"] == "Mail"

    def test_ouvre_lapplication_mail(self):
        result = self._route("ouvre l'application mail")
        assert result is not None
        _, action = result
        assert action["parameters"]["app_name"] == "Mail"

    def test_va_sur_mail(self):
        result = self._route("va sur mail")
        assert result is not None
        _, action = result
        assert action["parameters"]["app_name"] == "Mail"

    def test_aller_sur_safari(self):
        result = self._route("aller sur safari")
        assert result is not None
        _, action = result
        assert action["parameters"]["app_name"] == "Safari"

    def test_ouvre_notes(self):
        result = self._route("ouvre notes")
        assert result is not None
        _, action = result
        assert action["parameters"]["app_name"] == "Notes"

    def test_lance_mail(self):
        result = self._route("lance mail")
        assert result is not None
        _, action = result
        assert action["parameters"]["app_name"] == "Mail"

    def test_ouvre_chrome(self):
        result = self._route("ouvre chrome")
        assert result is not None
        _, action = result
        assert action["parameters"]["app_name"] == "Google Chrome"


# ── ComputerControlAgent — _parse_open_application ────────────────────────────


from app.agents.computer_control_agent import ComputerControlAgent


@pytest.fixture
def agent() -> ComputerControlAgent:
    llm = MagicMock()
    bus = MagicMock()
    config: dict[str, Any] = {}
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.agents.computer_control_agent.os.makedirs"
    ):
        return ComputerControlAgent(llm, bus, config)


class TestParseOpenApplication:
    def test_ouvre_mail(self, agent):
        assert agent._parse_open_application("ouvre mail") == "mail"

    def test_ouvre_moi_mes_mails(self, agent):
        result = agent._parse_open_application("ouvre moi mes mails")
        assert result is not None
        assert "mail" in result.lower()

    def test_lance_lapp_mail(self, agent):
        result = agent._parse_open_application("lance l'app mail")
        assert result is not None
        assert "mail" in result.lower()

    def test_ouvre_lapplication_mail(self, agent):
        result = agent._parse_open_application("ouvre l'application Mail")
        assert result is not None
        assert "mail" in result.lower()

    def test_va_sur_mail(self, agent):
        result = agent._parse_open_application("va sur mail")
        assert result is not None
        assert "mail" in result.lower()

    def test_ouvre_safari(self, agent):
        assert agent._parse_open_application("ouvre safari") == "safari"

    def test_lance_notes(self, agent):
        result = agent._parse_open_application("lance notes")
        assert result is not None
        assert "notes" in result.lower()

    def test_ouvre_le_mail(self, agent):
        result = agent._parse_open_application("ouvre le mail")
        assert result is not None
        assert "mail" in result.lower()


class TestCanHandleOpenKeywords:
    """Vérifie que can_handle retourne True pour les nouveaux verbes."""

    def test_va_sur_mail(self, agent):
        assert agent.can_handle("va sur mail") is True

    def test_demarre_mail(self, agent):
        assert agent.can_handle("démarre mail") is True

    def test_affiche_mail(self, agent):
        assert agent.can_handle("affiche mail") is True

    def test_ouvre_mail(self, agent):
        assert agent.can_handle("ouvre mail") is True

    def test_lance_mail(self, agent):
        assert agent.can_handle("lance mail") is True
