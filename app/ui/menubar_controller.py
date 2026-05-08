# app/ui/menubar_controller.py
# NSStatusItem menubar icon for Lucie — minimal, non-intrusive.
# Three visual states: idle (sparkle), thinking (wand.and.stars), done (sparkle).
# Click → toggle HUD. Right-click → mini menu (3 items max).

from __future__ import annotations

from typing import Any, Optional

import AppKit
import objc

from ..utils.logger import logger


class MenuBarController(AppKit.NSObject):  # type: ignore[misc]
    """Controls the NSStatusItem in the system menubar.

    Persists even when the HUD is hidden so the user always has a way
    to bring Lucie back without remembering Cmd+Shift+L.
    """

    def initWithHUD_(self, hud: Any) -> Any:
        self = objc.super(MenuBarController, self).init()
        if self is not None:
            self._hud = hud
            bar = AppKit.NSStatusBar.systemStatusBar()
            self._item = bar.statusItemWithLength_(AppKit.NSSquareStatusItemLength)
            btn = self._item.button()
            self._apply_icon("sparkle")
            # Left click → toggle; right-click detected in handler
            btn.setAction_("handleClick:")
            btn.setTarget_(self)
            btn.sendActionOn_(
                AppKit.NSEventMaskLeftMouseUp | AppKit.NSEventMaskRightMouseUp
            )
            self._menu = self._build_menu()
            self._current_state: str = "idle"
        return self

    @objc.python_method  # type: ignore[untyped-decorator]
    def _apply_icon(self, symbol: str) -> None:
        btn = self._item.button()
        try:
            img = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                symbol, "Beaume"
            )
            if img:
                img.setTemplate_(True)   # adapts to light/dark mode
                btn.setImage_(img)
        except Exception as exc:
            logger.debug(f"MenuBar icon '{symbol}': {exc}")
            btn.setTitle_("✦")          # text fallback if SF Symbol unavailable

    @objc.python_method  # type: ignore[untyped-decorator]
    def _build_menu(self) -> Any:
        menu = AppKit.NSMenu.alloc().init()

        toggle = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Afficher / Masquer Beaume", "toggleHUD:", "l"
        )
        toggle.setKeyEquivalentModifierMask_(
            AppKit.NSEventModifierFlagCommand | AppKit.NSEventModifierFlagShift
        )
        toggle.setTarget_(self)
        menu.addItem_(toggle)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        about = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "À propos de Beaume", "showAbout:", ""
        )
        about.setTarget_(self)
        menu.addItem_(about)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        quit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quitter Beaume", "terminate:", "q"
        )
        # terminate: is handled by NSApp — no target override needed
        menu.addItem_(quit_item)

        return menu

    @objc.IBAction  # type: ignore[untyped-decorator]
    def handleClick_(self, sender: Any) -> None:
        event = AppKit.NSApp.currentEvent()
        is_right = event and event.type() == AppKit.NSEventTypeRightMouseUp
        is_ctrl = event and bool(
            event.modifierFlags() & AppKit.NSEventModifierFlagControl
        )
        if is_right or is_ctrl:
            self._item.popUpStatusItemMenu_(self._menu)
        else:
            self.toggleHUD_(sender)

    @objc.IBAction  # type: ignore[untyped-decorator]
    def toggleHUD_(self, sender: Any) -> None:
        if self._hud.isVisible():
            self._hud.animateOut()
        else:
            self._hud.animateIn()

    @objc.IBAction  # type: ignore[untyped-decorator]
    def showAbout_(self, sender: Any) -> None:
        AppKit.NSApp.orderFrontStandardAboutPanel_(sender)

    @objc.python_method  # type: ignore[untyped-decorator]
    def set_state(self, state: str) -> None:
        """Update icon to reflect Lucie's activity state.

        idle  → sparkle (normal opacity)
        thinking / searching / writing → wand.and.stars
        done / error → sparkle (revert)
        """
        if state == self._current_state:
            return
        self._current_state = state
        active = {"thinking", "searching", "writing", "executing"}
        self._apply_icon("wand.and.stars" if state in active else "sparkle")

    @objc.python_method  # type: ignore[untyped-decorator]
    def remove(self) -> None:
        """Remove the status item on app termination to avoid ghost icons."""
        try:
            AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(self._item)
        except Exception:
            pass
