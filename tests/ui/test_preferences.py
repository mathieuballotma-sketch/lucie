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
    """6. Frame 399×349 → corrigée à au moins 400×350, origine inchangée."""
    rect = AppKit.NSMakeRect(50.0, 60.0, 399.0, 349.0)
    clamped = preferences.clamp_to_min_size(rect)
    assert clamped.size.width == pytest.approx(400.0)
    assert clamped.size.height == pytest.approx(350.0)
    assert clamped.origin.x == pytest.approx(50.0)
    assert clamped.origin.y == pytest.approx(60.0)
