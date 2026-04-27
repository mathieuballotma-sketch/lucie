"""Persistance utilisateur du HUD via NSUserDefaults (H8 Sprint S1).

Wrapper minimal autour de `NSUserDefaults.standardUserDefaults()` pour
mémoriser la position et la taille de la fenêtre HUD entre sessions.

Conventions :
- Clé `lucie_hud_frame` : NSStringFromRect(NSRect) — string roundtrip via NSRectFromString.
- Garde-fous : si la clé est absente / corrompue → retourne None ; le caller
  applique son fallback (frame initiale 520x500 centrée).
- Garde-fous écran : `is_frame_visible(rect)` itère NSScreen.screens() et
  vérifie qu'au moins 100x100 pixels sont à l'intersection d'un écran réel —
  évite que le HUD réapparaisse sur un écran débranché.
- Min size : `clamp_to_min_size(rect, min_w, min_h)` corrige les frames
  héritées en dessous du minimum.

Réutilisable par d'autres préférences UI futures (ex. taille de police,
profil métier) — voir Q-0004 dans 06_OPEN_QUESTIONS.md.
"""
from __future__ import annotations

from typing import Any, Optional

import AppKit
import Foundation


HUD_FRAME_KEY = "lucie_hud_frame"

# Min/max imposés à la fenêtre HUD redimensionnable.
HUD_MIN_W = 400.0
HUD_MIN_H = 350.0
HUD_MAX_W = 9999.0
HUD_MAX_H = 9999.0


def _defaults() -> Any:
    return AppKit.NSUserDefaults.standardUserDefaults()


def save_frame(rect: Any) -> None:
    """Sauve une NSRect dans NSUserDefaults sous forme de string."""
    try:
        s = AppKit.NSStringFromRect(rect)
        _defaults().setObject_forKey_(s, HUD_FRAME_KEY)
    except Exception:
        pass


def load_frame() -> Optional[Any]:
    """Charge la NSRect persistée ou retourne None si absent / corrompu."""
    try:
        raw = _defaults().stringForKey_(HUD_FRAME_KEY)
    except Exception:
        return None
    if not raw:
        return None
    try:
        rect = AppKit.NSRectFromString(raw)
    except Exception:
        return None
    # NSRectFromString retourne {{0,0},{0,0}} si parsing impossible — invalide.
    if rect.size.width <= 0 or rect.size.height <= 0:
        return None
    return rect


def clear_frame() -> None:
    """Efface la frame persistée (utile pour debug / reset)."""
    try:
        _defaults().removeObjectForKey_(HUD_FRAME_KEY)
    except Exception:
        pass


def clamp_to_min_size(
    rect: Any,
    min_w: float = HUD_MIN_W,
    min_h: float = HUD_MIN_H,
) -> Any:
    """Corrige la taille minimum d'une NSRect, préserve l'origine."""
    new_w = max(rect.size.width, min_w)
    new_h = max(rect.size.height, min_h)
    return AppKit.NSMakeRect(rect.origin.x, rect.origin.y, new_w, new_h)


def is_frame_visible(rect: Any, min_overlap: float = 100.0) -> bool:
    """Vérifie qu'au moins `min_overlap` x `min_overlap` pixels du rect
    intersectent un écran réel.

    Protège contre les frames héritées d'écrans aujourd'hui débranchés.
    """
    try:
        screens = AppKit.NSScreen.screens()
    except Exception:
        return False
    if not screens or screens.count() == 0:
        return False
    for i in range(screens.count()):
        screen = screens.objectAtIndex_(i)
        screen_frame = screen.frame()
        intersection = AppKit.NSIntersectionRect(rect, screen_frame)
        if (
            intersection.size.width >= min_overlap
            and intersection.size.height >= min_overlap
        ):
            return True
    return False


__all__ = [
    "HUD_FRAME_KEY",
    "HUD_MIN_W",
    "HUD_MIN_H",
    "HUD_MAX_W",
    "HUD_MAX_H",
    "save_frame",
    "load_frame",
    "clear_frame",
    "clamp_to_min_size",
    "is_frame_visible",
]


# Aide types pour l'analyseur statique
try:  # pragma: no cover
    from typing import Any  # noqa: F401
except Exception:  # pragma: no cover
    pass
