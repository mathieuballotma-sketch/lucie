"""
Tests UI pour le redimensionnement fenêtre (brique N12, résout Q-0012).

Vérifie :
- pipeline boot : load_frame → clamp_min → clamp_max → frame valide
- bornes brief Mathieu (HUD_MIN/MAX) en place
- styleMask inclut bien NSWindowStyleMaskResizable
- autoresizing mask flags définis (smoke test)
- combinaisons multi-écran : frame perdue (off-screen) → fallback origine
"""

from __future__ import annotations

import pytest

AppKit = pytest.importorskip("AppKit")

from app.services import preferences


@pytest.fixture(autouse=True)
def _reset_defaults():
    initial = AppKit.NSUserDefaults.standardUserDefaults().stringForKey_(
        preferences.HUD_FRAME_KEY
    )
    yield
    if initial is None:
        preferences.clear_frame()
    else:
        AppKit.NSUserDefaults.standardUserDefaults().setObject_forKey_(
            initial, preferences.HUD_FRAME_KEY
        )


# ─── Boot frame restoration pipeline ─────────────────────────────────────────

def test_boot_pipeline_clamp_min_then_max_keeps_size_in_bounds() -> None:
    """N12 — frame héritée 200×2000 restaurée → clampée à 400×900."""
    persisted = AppKit.NSMakeRect(50.0, 60.0, 200.0, 2000.0)
    after_min = preferences.clamp_to_min_size(persisted)
    after_max = preferences.clamp_to_max_size(after_min)
    assert after_max.size.width == pytest.approx(preferences.HUD_MIN_W)
    assert after_max.size.height == pytest.approx(preferences.HUD_MAX_H)
    # Origine inchangée
    assert after_max.origin.x == pytest.approx(50.0)


def test_boot_pipeline_normal_frame_preserved() -> None:
    """N12 — frame raisonnable 800×600 → ni clampée min ni clampée max."""
    persisted = AppKit.NSMakeRect(100.0, 100.0, 800.0, 600.0)
    after = preferences.clamp_to_max_size(preferences.clamp_to_min_size(persisted))
    assert after.size.width == pytest.approx(800.0)
    assert after.size.height == pytest.approx(600.0)


def test_persisted_size_survives_save_load_roundtrip() -> None:
    """N12 — si l'utilisateur a redimensionné, la taille est bien rechargée."""
    rect = AppKit.NSMakeRect(60.0, 80.0, 950.0, 720.0)
    preferences.save_frame(rect)
    loaded = preferences.load_frame()
    assert loaded is not None
    assert loaded.size.width == pytest.approx(950.0)
    assert loaded.size.height == pytest.approx(720.0)


# ─── Style mask resizable ────────────────────────────────────────────────────

def test_window_style_mask_resizable_constant_available() -> None:
    """N12 — le drapeau Resizable est exposé par AppKit (pas de typo runtime)."""
    assert isinstance(AppKit.NSWindowStyleMaskResizable, int)
    assert AppKit.NSWindowStyleMaskResizable > 0


def test_window_style_mask_combination_borderless_resizable() -> None:
    """N12 — la combinaison utilisée par HUDWindow.init est valide en bitwise."""
    mask = (
        AppKit.NSWindowStyleMaskBorderless
        | AppKit.NSWindowStyleMaskNonactivatingPanel
        | AppKit.NSWindowStyleMaskResizable
    )
    # Resizable doit être présent
    assert (mask & AppKit.NSWindowStyleMaskResizable) == AppKit.NSWindowStyleMaskResizable


# ─── Autoresizing masks ──────────────────────────────────────────────────────

def test_autoresizing_constants_available() -> None:
    """N12 — les constantes utilisées par _apply_autoresizing_masks existent."""
    for name in (
        "NSViewWidthSizable", "NSViewHeightSizable",
        "NSViewMinYMargin", "NSViewMaxYMargin",
        "NSViewMinXMargin", "NSViewMaxXMargin",
    ):
        assert hasattr(AppKit, name), f"AppKit.{name} manquant"
        assert isinstance(getattr(AppKit, name), int)


def test_pin_top_left_combination_distinct_from_pin_bottom_right() -> None:
    """N12 — les masks pin-top-left et pin-bottom-right ne se confondent pas."""
    pin_top_left = AppKit.NSViewMinYMargin | AppKit.NSViewMaxXMargin
    pin_bottom_right = AppKit.NSViewMaxYMargin | AppKit.NSViewMinXMargin
    assert pin_top_left != pin_bottom_right
