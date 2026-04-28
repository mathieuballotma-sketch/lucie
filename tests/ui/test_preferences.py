"""Tests H8 — preferences.py wrapper NSUserDefaults (Sprint S1, brique H8).

Couvre 6 cas du plan :
1. save → load roundtrip
2. load sans clé → None
3. load valeur corrompue → None
4. is_frame_visible avec mainScreen normal → True
5. is_frame_visible avec frame impossible → False
6. clamp_to_min_size : 399x349 → 400x350

PyObjC requis (NSUserDefaults + NSScreen). Skip si AppKit indisponible.
"""
from __future__ import annotations

import pytest

AppKit = pytest.importorskip("AppKit")

from app.services import preferences


@pytest.fixture(autouse=True)
def _reset_defaults():
    """Garantit qu'on n'altère pas durablement la pref de l'utilisateur :
    sauvegarde la valeur initiale, restaure à la fin du test."""
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


def test_save_load_roundtrip_preserves_frame():
    """1. save → load → frame quasi identique (origin et taille)."""
    rect = AppKit.NSMakeRect(120.0, 240.0, 600.0, 480.0)
    preferences.save_frame(rect)
    loaded = preferences.load_frame()
    assert loaded is not None
    assert loaded.origin.x == pytest.approx(120.0)
    assert loaded.origin.y == pytest.approx(240.0)
    assert loaded.size.width == pytest.approx(600.0)
    assert loaded.size.height == pytest.approx(480.0)


def test_load_with_no_key_returns_none():
    """2. load sans clé → None."""
    preferences.clear_frame()
    assert preferences.load_frame() is None


def test_load_with_corrupted_value_returns_none():
    """3. Valeur corrompue dans NSUserDefaults → None (graceful)."""
    AppKit.NSUserDefaults.standardUserDefaults().setObject_forKey_(
        "garbage_not_a_rect", preferences.HUD_FRAME_KEY
    )
    # NSRectFromString sur "garbage" retourne {{0,0},{0,0}} → notre
    # garde-fou width/height <= 0 doit retourner None.
    assert preferences.load_frame() is None


def test_is_frame_visible_on_main_screen_returns_true():
    """4. Frame normale dans main screen → visible."""
    main = AppKit.NSScreen.mainScreen().frame()
    rect = AppKit.NSMakeRect(
        main.origin.x + 50, main.origin.y + 50, 400, 300
    )
    assert preferences.is_frame_visible(rect) is True


def test_is_frame_visible_off_screen_returns_false():
    """5. Frame -9999/-9999 (écran déconnecté) → non visible."""
    rect = AppKit.NSMakeRect(-9999.0, -9999.0, 100.0, 100.0)
    assert preferences.is_frame_visible(rect) is False


def test_clamp_to_min_size_corrects_undersized_frame():
    """6. Frame 399×399 → corrigée à au moins HUD_MIN, origine inchangée.

    HUD_MIN_H passé de 350 à 400 par N12 (résout Q-0012).
    """
    rect = AppKit.NSMakeRect(50.0, 60.0, 399.0, 399.0)
    clamped = preferences.clamp_to_min_size(rect)
    assert clamped.size.width == pytest.approx(preferences.HUD_MIN_W)
    assert clamped.size.height == pytest.approx(preferences.HUD_MIN_H)
    assert clamped.origin.x == pytest.approx(50.0)
    assert clamped.origin.y == pytest.approx(60.0)


# ─── N12 — bornes max + clamp_to_max_size ────────────────────────────────────

def test_hud_bounds_match_brief():
    """N12 — les bornes brief Mathieu : 400×400 min, 1200×900 max."""
    assert preferences.HUD_MIN_W == 400.0
    assert preferences.HUD_MIN_H == 400.0
    assert preferences.HUD_MAX_W == 1200.0
    assert preferences.HUD_MAX_H == 900.0


def test_clamp_to_max_size_corrects_oversized_frame():
    """N12 — Frame 1500×1000 → corrigée à 1200×900, origine inchangée."""
    rect = AppKit.NSMakeRect(80.0, 90.0, 1500.0, 1000.0)
    clamped = preferences.clamp_to_max_size(rect)
    assert clamped.size.width == pytest.approx(1200.0)
    assert clamped.size.height == pytest.approx(900.0)
    assert clamped.origin.x == pytest.approx(80.0)
    assert clamped.origin.y == pytest.approx(90.0)


def test_clamp_to_max_size_does_not_grow_smaller_frame():
    """N12 — Frame 600×500 (déjà sous max) → inchangée."""
    rect = AppKit.NSMakeRect(0.0, 0.0, 600.0, 500.0)
    clamped = preferences.clamp_to_max_size(rect)
    assert clamped.size.width == pytest.approx(600.0)
    assert clamped.size.height == pytest.approx(500.0)


def test_combined_clamp_min_then_max_keeps_in_bounds():
    """N12 — Frame 200×2000 → min puis max → 400×900."""
    rect = AppKit.NSMakeRect(0.0, 0.0, 200.0, 2000.0)
    after_min = preferences.clamp_to_min_size(rect)
    after_max = preferences.clamp_to_max_size(after_min)
    assert after_max.size.width == pytest.approx(400.0)
    assert after_max.size.height == pytest.approx(900.0)
