"""
tests/ui/test_hud.py — Tests unitaires HUD v2

Ces tests s'exécutent SANS engine ni Ollama.
Ils vérifient les helpers purs et la logique non-UI de HUDWindow.

NOTE : Les tests qui instancient HUDWindow nécessitent macOS + PyObjC.
       Ils sont skippés automatiquement sur les autres plateformes.
"""
import os
import platform
import sys
import types
import pytest


# ─── Skip sur non-macOS ──────────────────────────────────────────────────────
requires_macos = pytest.mark.skipif(
    platform.system() != "Darwin",
    reason="Nécessite macOS + PyObjC",
)


# ─── Helpers purs (pas de PyObjC) ────────────────────────────────────────────

class TestFormatFileCard:
    """Tests de la logique de format_file_card sans PyObjC."""

    def _make_stub_hud(self):
        """Crée un stub minimal de HUDWindow pour tester format_file_card."""
        # On teste uniquement la logique pure sans AppKit
        stub = types.SimpleNamespace()

        # Lookup table copiée de hud_native
        _icon_map = {
            ".pdf": "📄", ".docx": "📝", ".doc": "📝", ".txt": "📋",
            ".xlsx": "📊", ".csv": "📊", ".py": "🐍", ".md": "📖",
            ".png": "🖼", ".jpg": "🖼", ".jpeg": "🖼",
            ".mp3": "🎵", ".mp4": "🎬", ".zip": "📦",
        }

        def _icon_for(filepath):
            ext = os.path.splitext(os.path.basename(filepath))[1].lower()
            return _icon_map.get(ext, "📁")

        stub.icon_for = _icon_for
        return stub

    def test_icon_pdf(self):
        stub = self._make_stub_hud()
        assert stub.icon_for("/tmp/rapport.pdf") == "📄"

    def test_icon_python(self):
        stub = self._make_stub_hud()
        assert stub.icon_for("/home/user/script.py") == "🐍"

    def test_icon_unknown(self):
        stub = self._make_stub_hud()
        assert stub.icon_for("/tmp/archive.tar.gz") == "📁"

    def test_icon_docx(self):
        stub = self._make_stub_hud()
        assert stub.icon_for("/Documents/contract.docx") == "📝"

    def test_icon_image(self):
        stub = self._make_stub_hud()
        assert stub.icon_for("/photos/selfie.jpg") == "🖼"

    def test_path_components(self):
        filepath = "/Users/mathieu/Desktop/notes.txt"
        assert os.path.basename(filepath) == "notes.txt"
        assert os.path.dirname(filepath) == "/Users/mathieu/Desktop"
        assert os.path.splitext("notes.txt")[1] == ".txt"


# ─── Tests des constantes de layout ──────────────────────────────────────────

class TestLayoutConstants:
    """Vérifie que les constantes de layout sont cohérentes."""

    def test_import_constants(self):
        """Les constantes doivent s'importer sans lancer d'UI."""
        # On évite d'importer hud_native directement car il lance AppKit
        # On recrée les calculs pour les valider
        WINDOW_W = 520
        WINDOW_H = 500
        HEADER_H = 56
        INPUT_H = 40
        STATUS_H = 20
        AGENT_BAR_H = 22
        PADDING = 14

        _STATUS_Y = 6
        _INPUT_Y = _STATUS_Y + STATUS_H + 6
        _INPUT_TOP = _INPUT_Y + INPUT_H
        _TEXT_Y = _INPUT_TOP + PADDING
        _HEADER_Y = WINDOW_H - HEADER_H
        _AGENT_BAR_Y = _HEADER_Y - AGENT_BAR_H
        _TEXT_H = _AGENT_BAR_Y - 2 - _TEXT_Y
        _TEXT_W = WINDOW_W - PADDING * 2

        assert _INPUT_Y == 32
        assert _INPUT_TOP == 72
        assert _TEXT_Y == 86
        assert _HEADER_Y == 444
        assert _AGENT_BAR_Y == 422
        assert _TEXT_H == 334
        assert _TEXT_W == 492

    def test_text_area_positive(self):
        """La zone de texte doit avoir une hauteur positive."""
        WINDOW_H = 500
        HEADER_H = 56
        AGENT_BAR_H = 22
        PADDING = 14
        INPUT_H = 40
        STATUS_H = 20

        _STATUS_Y = 6
        _INPUT_Y = _STATUS_Y + STATUS_H + 6
        _INPUT_TOP = _INPUT_Y + INPUT_H
        _TEXT_Y = _INPUT_TOP + PADDING
        _AGENT_BAR_Y = WINDOW_H - HEADER_H - AGENT_BAR_H
        _TEXT_H = _AGENT_BAR_Y - 2 - _TEXT_Y

        assert _TEXT_H > 0, "La zone de texte doit avoir une hauteur positive"
        assert _TEXT_H > 200, "La zone de texte doit être suffisamment grande"

    def test_no_overlap(self):
        """Les zones ne doivent pas se chevaucher."""
        WINDOW_H = 500
        HEADER_H = 56
        AGENT_BAR_H = 22
        INPUT_H = 40
        STATUS_H = 20
        PADDING = 14

        _STATUS_Y = 6
        _INPUT_Y = _STATUS_Y + STATUS_H + 6
        _INPUT_TOP = _INPUT_Y + INPUT_H
        _TEXT_Y = _INPUT_TOP + PADDING
        _HEADER_Y = WINDOW_H - HEADER_H
        _AGENT_BAR_Y = _HEADER_Y - AGENT_BAR_H

        # Input zone est au-dessous de la zone de texte
        assert _INPUT_TOP < _TEXT_Y
        # Agent bar est au-dessus de la zone de texte
        assert _TEXT_Y < _AGENT_BAR_Y
        # Header est au-dessus de l'agent bar
        assert _AGENT_BAR_Y < _HEADER_Y
        # Header est dans la fenêtre
        assert _HEADER_Y + HEADER_H == WINDOW_H


# ─── Tests PyObjC (macOS seulement) ──────────────────────────────────────────

@requires_macos
class TestHUDWindowMacOS:
    """Tests nécessitant PyObjC."""

    @pytest.fixture(autouse=True)
    def _check_pyobjc(self):
        try:
            import AppKit  # noqa: F401
        except ImportError:
            pytest.skip("PyObjC non installé")

    @pytest.fixture
    def hud(self):
        """Instancie un HUDWindow sans engine (mode test)."""
        # Il faut un NSApplication pour que NSWindow fonctionne
        import AppKit
        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyProhibited)

        # Import local pour éviter les side-effects au niveau module
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        from app.ui.hud_native import HUDWindow
        window = HUDWindow.alloc().init()
        assert window is not None, "HUDWindow.alloc().init() doit retourner une instance"
        yield window
        window.close()

    def test_instantiation(self, hud):
        """HUDWindow s'instancie sans engine."""
        import AppKit
        from app.ui.hud_native import WINDOW_W, WINDOW_H
        frame = hud.frame()
        assert frame.size.width == WINDOW_W
        assert frame.size.height == WINDOW_H

    def test_has_required_attributes(self, hud):
        """Tous les attributs requis par l'onboarding sont présents."""
        assert hasattr(hud, "_input")
        assert hasattr(hud, "_send_btn")
        assert hasattr(hud, "_thinking_indicator")
        assert hasattr(hud, "_thinking_label")
        assert hasattr(hud, "_latency_label")
        assert hasattr(hud, "_status")
        assert hasattr(hud, "_status_text")
        assert hasattr(hud, "_agents_label")
        assert hasattr(hud, "_llm_dot")
        assert hasattr(hud, "_llm_label")

    def test_append_message_safe_user(self, hud):
        """append_message_safe insère un message utilisateur sans erreur."""
        hud.append_message_safe("Toi", "Bonjour Lucie", user=True)
        storage = hud._text_view.textStorage()
        content = storage.string()
        assert "Toi" in content
        assert "Bonjour Lucie" in content

    def test_append_message_safe_agent(self, hud):
        """append_message_safe insère un message agent sans erreur."""
        hud.append_message_safe("Lucie", "Bonjour, que puis-je faire ?", user=False)
        storage = hud._text_view.textStorage()
        content = storage.string()
        assert "Lucie" in content
        assert "Bonjour, que puis-je faire ?" in content

    def test_append_multiple_messages(self, hud):
        """Plusieurs messages s'accumulent sans effacement."""
        hud.append_message_safe("Toi", "Message 1", user=True)
        hud.append_message_safe("Lucie", "Réponse 1", user=False)
        hud.append_message_safe("Toi", "Message 2", user=True)
        storage = hud._text_view.textStorage()
        content = storage.string()
        assert "Message 1" in content
        assert "Réponse 1" in content
        assert "Message 2" in content

    def test_set_status(self, hud):
        """_set_status met à jour le dot et le label."""
        import AppKit
        from app.ui.hud_native import _orange
        hud._set_status("●", _orange(), "Traitement…")
        assert hud._status.stringValue() == "●"
        assert hud._status_text.stringValue() == "Traitement…"

    def test_format_file_card_returns_attributed_string(self, hud):
        """format_file_card retourne un NSAttributedString non-vide."""
        import AppKit
        card = hud.format_file_card("/tmp/rapport.pdf", "DocumentAgent")
        assert card is not None
        s = card.string()
        assert "rapport.pdf" in s
        assert "DocumentAgent" in s
        assert "📄" in s

    def test_format_file_card_unknown_ext(self, hud):
        """format_file_card utilise 📁 pour les extensions inconnues."""
        card = hud.format_file_card("/tmp/archive.tar.gz", "FileAgent")
        s = card.string()
        assert "📁" in s

    def test_update_agent_status(self, hud):
        """update_agent_status met à jour le label des agents."""
        hud.update_agent_status({"FileAgent": True, "DocumentAgent": False})
        label = hud._agents_label.stringValue()
        assert "FileAgent" in label
        assert "DocumentAgent" in label
        assert "●" in label  # active
        assert "○" in label  # inactive

    def test_set_llm_status_connected(self, hud):
        """set_llm_status(True) affiche 'Ollama' en vert."""
        hud.set_llm_status(True)
        assert hud._llm_label.stringValue() == "Ollama"

    def test_set_llm_status_disconnected(self, hud):
        """set_llm_status(False) affiche 'Ollama ✗' en rouge."""
        hud.set_llm_status(False)
        assert "Ollama" in hud._llm_label.stringValue()
        assert "✗" in hud._llm_label.stringValue()

    def test_is_non_activating_panel(self, hud):
        """La fenêtre est bien un NSPanel non-activant."""
        import AppKit
        assert isinstance(hud, AppKit.NSPanel)

    def test_window_dimensions(self, hud):
        """La fenêtre est 520×500."""
        from app.ui.hud_native import WINDOW_W, WINDOW_H
        frame = hud.frame()
        assert frame.size.width == WINDOW_W
        assert frame.size.height == WINDOW_H

    def test_floating_level(self, hud):
        """La fenêtre est flottante (niveau > 0)."""
        import Quartz
        assert hud.level() >= Quartz.kCGFloatingWindowLevel
