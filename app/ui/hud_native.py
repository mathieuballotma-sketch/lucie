# app/ui/hud_native.py
# HUD v2 — Bloc 6 BMAD — Design modernisé

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import AppKit
import Foundation
import objc
import Quartz
from PyObjCTools import AppHelper

from ..core.config import Config
from ..core.engine import LucidEngine
from ..utils.logger import logger

# ─── Layout constants ────────────────────────────────────────────────────────
WINDOW_W = 520
WINDOW_H = 500
CORNER_R = 16.0
PADDING = 14
HEADER_H = 56
INPUT_H = 40
STATUS_H = 20
AGENT_BAR_H = 22
ALPHA = 0.78

# Pre-computed Y positions (0 = bottom of window in AppKit coords)
_STATUS_Y = 6                                        # bottom status bar
_INPUT_Y = _STATUS_Y + STATUS_H + 6                 # 32
_INPUT_TOP = _INPUT_Y + INPUT_H                     # 72
_TEXT_Y = _INPUT_TOP + PADDING                      # 86
_HEADER_Y = WINDOW_H - HEADER_H                     # 444
_AGENT_BAR_Y = _HEADER_Y - AGENT_BAR_H             # 422
_TEXT_H = _AGENT_BAR_Y - 2 - _TEXT_Y               # 334
_TEXT_W = WINDOW_W - PADDING * 2                    # 492

# Streaming parameters — word-chunk feel
_STREAM_CHUNK = 4        # chars advanced per timer tick
_STREAM_INTERVAL = 0.04  # seconds between ticks (~100 chars/s)


# ─── Color helpers ───────────────────────────────────────────────────────────
def ns_color(r: float, g: float, b: float, a: float = 1.0) -> Any:
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a)


def ns_white(w: float, a: float = 1.0) -> Any:
    return AppKit.NSColor.colorWithCalibratedWhite_alpha_(w, a)


def make_rect(x: float, y: float, w: float, h: float) -> Any:
    return AppKit.NSMakeRect(x, y, w, h)


def _accent(a: float = 0.9) -> Any:
    """macOS system blue accent."""
    return ns_color(0.27, 0.52, 0.97, a)


def _green(a: float = 0.9) -> Any:
    return ns_color(0.2, 0.85, 0.40, a)


def _orange(a: float = 0.9) -> Any:
    return ns_color(1.0, 0.60, 0.00, a)


def _red(a: float = 0.9) -> Any:
    return ns_color(1.0, 0.25, 0.20, a)


# ─── DraggableView ───────────────────────────────────────────────────────────
class DraggableView(AppKit.NSView):  # type: ignore[misc]
    def initWithFrame_(self, frame: Any) -> Any:
        self = objc.super(DraggableView, self).initWithFrame_(frame)
        if self is not None:
            self._drag_start: Any = None
        return self

    def mouseDown_(self, event: Any) -> None:
        self._drag_start = event.locationInWindow()

    def mouseDragged_(self, event: Any) -> None:
        if self._drag_start is None:
            return
        loc = event.locationInWindow()
        dx = loc.x - self._drag_start.x
        dy = loc.y - self._drag_start.y
        win = self.window()
        if win:
            f = win.frame()
            win.setFrameOrigin_((f.origin.x + dx, f.origin.y + dy))

    def mouseUp_(self, event: Any) -> None:
        self._drag_start = None

    def isOpaque(self) -> bool:
        return False


# ─── ThinkingIndicatorView ───────────────────────────────────────────────────
class ThinkingIndicatorView(AppKit.NSView):  # type: ignore[misc]
    """3 pulsing dots shown during LLM processing (staggered pulse animation)."""
    _DOT_SIZE: float = 6.0
    _DOT_GAP: float = 4.0

    def initWithFrame_(self, frame: Any) -> Any:
        self = objc.super(ThinkingIndicatorView, self).initWithFrame_(frame)
        if self is not None:
            self.setWantsLayer_(True)
            self._dots: List[Any] = []
            for i in range(3):
                dot = Quartz.CALayer.layer()
                x = i * (self._DOT_SIZE + self._DOT_GAP)
                dot.setFrame_(Quartz.CGRectMake(x, 0.0, self._DOT_SIZE, self._DOT_SIZE))
                dot.setCornerRadius_(self._DOT_SIZE / 2)
                dot.setBackgroundColor_(ns_white(1.0, 0.15).CGColor())
                self.layer().addSublayer_(dot)
                self._dots.append(dot)
        return self

    def startAnimating(self) -> None:
        now = Quartz.CACurrentMediaTime()
        for i, dot in enumerate(self._dots):
            dot.setBackgroundColor_(_accent().CGColor())
            anim = Quartz.CABasicAnimation.animationWithKeyPath_("transform.scale")
            anim.setFromValue_(0.5)
            anim.setToValue_(1.0)
            anim.setDuration_(0.5)
            anim.setBeginTime_(now + i * 0.15)
            anim.setAutoreverses_(True)
            anim.setRepeatCount_(float("inf"))
            dot.addAnimation_forKey_(anim, "pulse")

    def stopAnimating(self) -> None:
        for dot in self._dots:
            dot.removeAllAnimations()
            dot.setBackgroundColor_(ns_white(1.0, 0.15).CGColor())


# ─── DropContentView ─────────────────────────────────────────────────────────
class DropContentView(AppKit.NSView):  # type: ignore[misc]
    """Content view with file/folder drag-and-drop support.

    Registered as drag destination for the whole HUD surface.
    Interactive subviews (input, buttons) are on top in z-order so they receive
    mouse events normally; file drops that miss registered subviews bubble up to
    this view via the standard AppKit drag-destination traversal.
    """

    def initWithFrame_(self, frame: Any) -> Any:
        self = objc.super(DropContentView, self).initWithFrame_(frame)
        if self is not None:
            self._hud_ref: Optional[Any] = None
            self.registerForDraggedTypes_([AppKit.NSPasteboardTypeFileURL])
        return self

    def draggingEntered_(self, sender: Any) -> int:
        if self._hud_ref is not None:
            self._hud_ref._show_drop_highlight(True)
        return AppKit.NSDragOperationCopy

    def draggingUpdated_(self, sender: Any) -> int:
        return AppKit.NSDragOperationCopy

    def draggingExited_(self, sender: Any) -> None:
        if self._hud_ref is not None:
            self._hud_ref._show_drop_highlight(False)

    def prepareForDragOperation_(self, sender: Any) -> bool:
        return True

    def performDragOperation_(self, sender: Any) -> bool:
        if self._hud_ref is not None:
            self._hud_ref._show_drop_highlight(False)
        pb = sender.draggingPasteboard()
        path: Optional[str] = None

        # Modern: NSPasteboardTypeFileURL
        try:
            urls = pb.readObjectsForClasses_options_([AppKit.NSURL], {})
            for url in (urls or []):
                if hasattr(url, "isFileURL") and url.isFileURL():
                    path = str(url.path())
                    break
        except Exception:
            pass

        # Fallback: legacy NSFilenamesPboardType
        if not path:
            try:
                filenames = pb.propertyListForType_("NSFilenamesPboardType")
                if filenames:
                    path = str(filenames[0])
            except Exception:
                pass

        if path and self._hud_ref is not None:
            AppHelper.callAfter(self._hud_ref.handle_dropped_path, path)
            return True
        return False


# ─── HUDWindow ───────────────────────────────────────────────────────────────
class HUDWindow(AppKit.NSPanel):  # type: ignore[misc]

    def init(self) -> Any:
        rect = make_rect(
            100,
            AppKit.NSScreen.mainScreen().frame().size.height - WINDOW_H - 100,
            WINDOW_W,
            WINDOW_H,
        )
        style = (
            AppKit.NSWindowStyleMaskBorderless
            | AppKit.NSWindowStyleMaskNonactivatingPanel
        )
        self = objc.super(HUDWindow, self).initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False
        )
        if self is None:
            return None

        self.setFloatingPanel_(True)
        self.setBecomesKeyOnlyIfNeeded_(False)
        self.setHidesOnDeactivate_(False)
        self.setLevel_(Quartz.kCGFloatingWindowLevel + 1)
        self.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )
        self.setOpaque_(False)
        self.setBackgroundColor_(AppKit.NSColor.clearColor())
        self.setAlphaValue_(ALPHA)
        self.setHasShadow_(True)

        self._is_dragging: bool = False
        self._is_processing: bool = False
        self._processing_start_time: float = 0.0
        self.engine: Optional[Any] = None

        # Streaming state
        self._streaming_text: str = ""
        self._streaming_index: int = 0
        self._streaming_timer: Optional[Any] = None
        self._streaming_sender: str = ""
        self._streaming_full_text: str = ""
        self._streaming_range: Optional[Tuple[int, int]] = None

        # Drop state — file or folder attached to next query
        self._current_document: Optional[str] = None
        self._current_dossier_path: Optional[str] = None

        # Replace default content view with drop-aware version
        _drop = DropContentView.alloc().initWithFrame_(self.contentView().frame())
        _drop._hud_ref = self
        self.setContentView_(_drop)

        self._setup_ui()
        self._setup_space_observer()
        # NOTE: watchdog intentionally removed — window level is maintained by
        # _setup_space_observer + NSWindowCollectionBehaviorCanJoinAllSpaces.
        # The old 2s orderFrontRegardless was intrusive (stole focus from other apps).

        logger.info("HUD v2 initialisé (520×500)")
        return self

    def canBecomeKeyWindow(self) -> bool:
        return True

    def canBecomeMainWindow(self) -> bool:
        return True

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        content = self.contentView()
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(CORNER_R)
        content.layer().setMasksToBounds_(True)

        # ── Vibrancy background ──────────────────────────────────────────────
        vfx = AppKit.NSVisualEffectView.alloc().initWithFrame_(
            make_rect(0, 0, WINDOW_W, WINDOW_H)
        )
        # NSVisualEffectMaterialSidebar (7) — modern, adapts to light/dark mode
        vfx.setMaterial_(7)
        vfx.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        vfx.setState_(AppKit.NSVisualEffectStateActive)
        vfx.setWantsLayer_(True)
        vfx.layer().setCornerRadius_(CORNER_R)
        vfx.layer().setBorderWidth_(0.5)
        vfx.layer().setBorderColor_(ns_white(1.0, 0.08).CGColor())
        content.addSubview_(vfx)

        # Drag overlay (full window, transparent)
        drag_view = DraggableView.alloc().initWithFrame_(
            make_rect(0, 0, WINDOW_W, WINDOW_H)
        )
        content.addSubview_(drag_view)

        # ══ HEADER ═══════════════════════════════════════════════════════════
        header_center_y = _HEADER_Y + (HEADER_H - 22) / 2  # vertically center 22px text

        icon_lbl = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(PADDING, header_center_y, 26, 22)
        )
        icon_lbl.setStringValue_("✦")
        icon_lbl.setEditable_(False)
        icon_lbl.setBezeled_(False)
        icon_lbl.setDrawsBackground_(False)
        icon_lbl.setFont_(
            AppKit.NSFont.systemFontOfSize_weight_(17, AppKit.NSFontWeightLight)
        )
        icon_lbl.setTextColor_(ns_white(0.9, 0.75))
        content.addSubview_(icon_lbl)

        title_lbl = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(PADDING + 32, header_center_y, 80, 22)
        )
        title_lbl.setStringValue_("LUCIE")
        title_lbl.setEditable_(False)
        title_lbl.setBezeled_(False)
        title_lbl.setDrawsBackground_(False)
        title_lbl.setFont_(
            AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(14, AppKit.NSFontWeightRegular)
        )
        title_lbl.setTextColor_(ns_white(0.95, 0.9))
        content.addSubview_(title_lbl)

        # Thinking indicator (3 pulsing dots)
        ind_w, ind_h = 26, 6
        ind_x = PADDING + 32 + 80 + 10
        ind_y = header_center_y + (22 - ind_h) / 2
        self._thinking_indicator = ThinkingIndicatorView.alloc().initWithFrame_(
            make_rect(ind_x, ind_y, ind_w, ind_h)
        )
        content.addSubview_(self._thinking_indicator)

        # Thinking status label
        self._thinking_label = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(ind_x + ind_size + 6, header_center_y, 120, 20)
        )
        self._thinking_label.setStringValue_("")
        self._thinking_label.setEditable_(False)
        self._thinking_label.setBezeled_(False)
        self._thinking_label.setDrawsBackground_(False)
        self._thinking_label.setFont_(AppKit.NSFont.systemFontOfSize_(10))
        self._thinking_label.setTextColor_(ns_white(0.65, 0.8))
        self._thinking_label.setAlphaValue_(0.0)
        content.addSubview_(self._thinking_label)

        # Latency display (right-aligned)
        self._latency_label = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(WINDOW_W - 88, header_center_y + 1, 80, 18)
        )
        self._latency_label.setStringValue_("")
        self._latency_label.setEditable_(False)
        self._latency_label.setBezeled_(False)
        self._latency_label.setDrawsBackground_(False)
        self._latency_label.setAlignment_(AppKit.NSTextAlignmentRight)
        self._latency_label.setFont_(
            AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(9, AppKit.NSFontWeightLight)
        )
        self._latency_label.setTextColor_(ns_white(0.45, 0.7))
        content.addSubview_(self._latency_label)

        # Separator: header / agent bar
        sep1 = AppKit.NSBox.alloc().initWithFrame_(
            make_rect(0, _HEADER_Y - 1, WINDOW_W, 1)
        )
        sep1.setBoxType_(AppKit.NSBoxSeparator)
        sep1.setAlphaValue_(0.08)
        content.addSubview_(sep1)

        # ══ AGENT STATUS BAR ═════════════════════════════════════════════════
        bar_center_y = _AGENT_BAR_Y + (AGENT_BAR_H - 12) / 2

        self._llm_dot = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(PADDING, bar_center_y, 10, 12)
        )
        self._llm_dot.setStringValue_("●")
        self._llm_dot.setEditable_(False)
        self._llm_dot.setBezeled_(False)
        self._llm_dot.setDrawsBackground_(False)
        self._llm_dot.setFont_(AppKit.NSFont.systemFontOfSize_(8))
        self._llm_dot.setTextColor_(_green())
        content.addSubview_(self._llm_dot)

        self._llm_label = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(PADDING + 14, bar_center_y, 70, 12)
        )
        self._llm_label.setStringValue_("Ollama")
        self._llm_label.setEditable_(False)
        self._llm_label.setBezeled_(False)
        self._llm_label.setDrawsBackground_(False)
        self._llm_label.setFont_(AppKit.NSFont.systemFontOfSize_(9))
        self._llm_label.setTextColor_(ns_white(0.55, 0.8))
        content.addSubview_(self._llm_label)

        # Active agents (right-aligned)
        self._agents_label = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(PADDING + 90, bar_center_y, WINDOW_W - PADDING * 2 - 90, 12)
        )
        self._agents_label.setStringValue_("")
        self._agents_label.setEditable_(False)
        self._agents_label.setBezeled_(False)
        self._agents_label.setDrawsBackground_(False)
        self._agents_label.setFont_(AppKit.NSFont.systemFontOfSize_(9))
        self._agents_label.setTextColor_(ns_white(0.45, 0.7))
        self._agents_label.setAlignment_(AppKit.NSTextAlignmentRight)
        content.addSubview_(self._agents_label)

        # Separator: agent bar / text area
        sep2 = AppKit.NSBox.alloc().initWithFrame_(
            make_rect(0, _AGENT_BAR_Y - 1, WINDOW_W, 1)
        )
        sep2.setBoxType_(AppKit.NSBoxSeparator)
        sep2.setAlphaValue_(0.08)
        content.addSubview_(sep2)

        # ══ TEXT AREA (results scroll view) ══════════════════════════════════
        self._text_view = AppKit.NSTextView.alloc().initWithFrame_(
            make_rect(0, 0, _TEXT_W, 9999)
        )
        self._text_view.setEditable_(False)
        self._text_view.setSelectable_(True)
        self._text_view.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._text_view.setTextColor_(ns_white(0.92, 0.9))
        self._text_view.setFont_(AppKit.NSFont.systemFontOfSize_(12.5))
        self._text_view.textContainer().setLineFragmentPadding_(6)
        self._text_view.setTextContainerInset_(AppKit.NSMakeSize(4, 8))
        self._text_view.setLinkTextAttributes_({
            AppKit.NSForegroundColorAttributeName: _accent(),
            AppKit.NSUnderlineStyleAttributeName: 1,
        })
        self._text_view.setDelegate_(self)

        scroll = AppKit.NSScrollView.alloc().initWithFrame_(
            make_rect(PADDING, _TEXT_Y, _TEXT_W, _TEXT_H)
        )
        scroll.setDocumentView_(self._text_view)
        scroll.setHasVerticalScroller_(True)
        scroll.setBackgroundColor_(AppKit.NSColor.clearColor())
        scroll.setDrawsBackground_(False)
        scroll.verticalScroller().setAlphaValue_(0.15)
        content.addSubview_(scroll)

        # Separator: text area / input
        sep3 = AppKit.NSBox.alloc().initWithFrame_(
            make_rect(0, _INPUT_TOP + 6, WINDOW_W, 1)
        )
        sep3.setBoxType_(AppKit.NSBoxSeparator)
        sep3.setAlphaValue_(0.08)
        content.addSubview_(sep3)

        # ══ INPUT ROW ════════════════════════════════════════════════════════
        btn_w = 36
        wf_btn_w = 36
        input_w = WINDOW_W - PADDING * 2 - btn_w - wf_btn_w - 12  # 12 = gaps

        self._input = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(PADDING, _INPUT_Y, input_w, INPUT_H)
        )
        self._input.setPlaceholderString_("Commande ou question…")
        self._input.setBezeled_(True)
        self._input.setBezelStyle_(AppKit.NSTextFieldRoundedBezel)
        self._input.setBackgroundColor_(ns_white(0.12, 0.25))
        self._input.setTextColor_(ns_white(0.95, 0.9))
        self._input.setFont_(AppKit.NSFont.systemFontOfSize_(13))
        self._input.setEditable_(True)
        self._input.setSelectable_(True)
        self._input.setTarget_(self)
        self._input.setAction_("sendQuery:")
        content.addSubview_(self._input)

        btn_x = PADDING + input_w + 6
        self._send_btn = AppKit.NSButton.alloc().initWithFrame_(
            make_rect(btn_x, _INPUT_Y, btn_w, INPUT_H)
        )
        self._send_btn.setBezelStyle_(AppKit.NSRoundedBezelStyle)
        self._send_btn.setTitle_("↗")
        self._send_btn.setFont_(
            AppKit.NSFont.systemFontOfSize_weight_(15, AppKit.NSFontWeightLight)
        )
        self._send_btn.setTarget_(self)
        self._send_btn.setAction_("sendQuery:")
        self._send_btn.setAttributedTitle_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(
                "↗", {AppKit.NSForegroundColorAttributeName: ns_white(0.8, 0.7)}
            )
        )
        content.addSubview_(self._send_btn)

        wf_x = btn_x + btn_w + 4
        self._workflow_btn = AppKit.NSButton.alloc().initWithFrame_(
            make_rect(wf_x, _INPUT_Y, wf_btn_w, INPUT_H)
        )
        self._workflow_btn.setBezelStyle_(AppKit.NSRoundedBezelStyle)
        self._workflow_btn.setToolTip_("Ouvrir l'éditeur de workflows")
        self._workflow_btn.setTarget_(self)
        self._workflow_btn.setAction_("openWorkflowEditor:")
        self._workflow_btn.setAttributedTitle_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(
                "⚡", {AppKit.NSForegroundColorAttributeName: ns_color(1.0, 0.85, 0.2, 0.85)}
            )
        )
        content.addSubview_(self._workflow_btn)

        # ══ BOTTOM STATUS BAR ════════════════════════════════════════════════
        self._status = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(PADDING, _STATUS_Y + 4, 14, 14)
        )
        self._status.setStringValue_("●")
        self._status.setEditable_(False)
        self._status.setBezeled_(False)
        self._status.setDrawsBackground_(False)
        self._status.setFont_(AppKit.NSFont.systemFontOfSize_(10))
        self._status.setTextColor_(_green())
        content.addSubview_(self._status)

        self._status_text = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(PADDING + 18, _STATUS_Y + 4, 140, 14)
        )
        self._status_text.setStringValue_("Prêt")
        self._status_text.setEditable_(False)
        self._status_text.setBezeled_(False)
        self._status_text.setDrawsBackground_(False)
        self._status_text.setFont_(AppKit.NSFont.systemFontOfSize_(9))
        self._status_text.setTextColor_(ns_white(0.65, 0.8))
        content.addSubview_(self._status_text)

        self._energy_label = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(WINDOW_W - PADDING - 120, _STATUS_Y + 4, 120, 14)
        )
        self._energy_label.setStringValue_("")
        self._energy_label.setEditable_(False)
        self._energy_label.setBezeled_(False)
        self._energy_label.setDrawsBackground_(False)
        self._energy_label.setFont_(AppKit.NSFont.systemFontOfSize_(9))
        self._energy_label.setTextColor_(_green())
        self._energy_label.setAlignment_(AppKit.NSTextAlignmentRight)
        content.addSubview_(self._energy_label)

        # Energy timer — every 15s (not too frequent)
        self._energy_timer = Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            15.0, self, "updateEnergyIndicator:", None, True
        )

        # Drop highlight overlay (shown during folder/file drag-over)
        self._drop_highlight = AppKit.NSView.alloc().initWithFrame_(
            make_rect(2, 2, WINDOW_W - 4, WINDOW_H - 4)
        )
        self._drop_highlight.setWantsLayer_(True)
        self._drop_highlight.layer().setCornerRadius_(CORNER_R - 1)
        self._drop_highlight.layer().setBorderWidth_(2.0)
        self._drop_highlight.layer().setBorderColor_(
            ns_color(0.27, 0.52, 0.97, 0.9).CGColor()
        )
        self._drop_highlight.layer().setBackgroundColor_(
            ns_color(0.27, 0.52, 0.97, 0.05).CGColor()
        )
        self._drop_highlight.setAlphaValue_(0.0)
        content.addSubview_(self._drop_highlight)

        # Predictor monitor — reschedules itself in typingTimerFired_
        self._last_text: str = ""
        self._typing_timer: Optional[Any] = None
        self._start_typing_monitor()

    # ── Space observer ────────────────────────────────────────────────────────

    def _setup_space_observer(self) -> None:
        nc = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        nc.addObserver_selector_name_object_(
            self,
            "spaceDidChange:",
            AppKit.NSWorkspaceActiveSpaceDidChangeNotification,
            None,
        )

    def spaceDidChange_(self, notification: Any) -> None:
        """Passive: re-assert floating level on space change (no orderFrontRegardless)."""
        if self.isVisible():
            self.setLevel_(Quartz.kCGFloatingWindowLevel + 1)

    # ── Typing predictor monitor ──────────────────────────────────────────────

    def _start_typing_monitor(self) -> None:
        self._typing_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, "typingTimerFired:", None, False
        )

    @objc.IBAction  # type: ignore[untyped-decorator]
    def typingTimerFired_(self, timer: Any) -> None:
        current = self._input.stringValue()
        if not current:
            # Field is empty — reset, do NOT call predictor
            self._last_text = ""
        elif current != self._last_text:
            self._last_text = current
            threading.Thread(
                target=self._send_to_predictor, args=(current,), daemon=True
            ).start()
        # Reschedule (non-repeating to avoid accumulation)
        self._typing_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, "typingTimerFired:", None, False
        )

    def _send_to_predictor(self, text: str) -> None:
        if (
            hasattr(self, "engine")
            and self.engine
            and hasattr(self.engine, "cortex")
            and getattr(self.engine.cortex, "predictor", None) is not None
        ):
            self.engine.cortex.predictor.update_partial_input(text)

    # ── Send query ────────────────────────────────────────────────────────────

    @objc.IBAction  # type: ignore[untyped-decorator]
    def sendQuery_(self, sender: Any) -> None:
        if self._is_processing:
            return
        query = self._input.stringValue().strip()
        if not query:
            return
        self._input.setStringValue_("")
        self._last_text = ""

        # Intercept during onboarding
        onboarding = getattr(self, "_onboarding_flow", None)
        if onboarding is not None:
            onboarding.handle_input(query)
            return

        self._is_processing = True
        self._processing_start_time = float(time.time())
        self.append_message_safe("Toi", query, user=True)

        self._set_status("●", _orange(), "Traitement…")
        self._send_btn.setEnabled_(False)
        self._thinking_indicator.startAnimating()
        self._thinking_label.setStringValue_("En cours…")
        self._thinking_label.setAlphaValue_(1.0)

        threading.Thread(target=self._process_query, args=(query,), daemon=True).start()

    @objc.IBAction  # type: ignore[untyped-decorator]
    def openWorkflowEditor_(self, sender: Any) -> None:
        def _launch() -> None:
            import importlib.util
            spec = importlib.util.find_spec("webview")
            if spec is None:
                AppHelper.callAfter(
                    self.append_message_safe,
                    "Lucie",
                    "⚡ L'éditeur de workflows nécessite pywebview.\nInstallez-le avec : pip install pywebview",
                    False,
                )
                return
            try:
                project_root = os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
                env = os.environ.copy()
                env.setdefault("PYTHONPATH", project_root)
                subprocess.Popen(
                    [sys.executable, "-c",
                     "from app.workflows.bridge import launch_editor; launch_editor()"],
                    cwd=project_root, env=env,
                )
                logger.info("Éditeur de workflows lancé")
            except Exception as e:
                logger.error(f"Erreur lancement éditeur workflows : {e}")
                AppHelper.callAfter(
                    self.append_message_safe, "Lucie",
                    f"⚡ Erreur lors de l'ouverture de l'éditeur : {e}", False,
                )
        threading.Thread(target=_launch, daemon=True).start()

    # ── Drop handling ─────────────────────────────────────────────────────────

    @objc.python_method  # type: ignore[untyped-decorator]
    def handle_dropped_path(self, path: str) -> None:
        """Called (on main thread) when a file or folder is dropped onto the HUD."""
        import os
        name = os.path.basename(path.rstrip("/"))
        if os.path.isdir(path):
            self._current_dossier_path = path
            self._current_document = None
            self.append_message_safe(
                "Lucie",
                f"📁 Dossier **{name}** prêt — posez votre question pour lancer l'analyse.",
                False,
            )
            self._input.setPlaceholderString_(f"Question sur le dossier {name}…")
        else:
            text = self._read_file_text(path)
            if text:
                self._current_document = text
                self._current_dossier_path = None
                self.append_message_safe(
                    "Lucie",
                    f"📄 **{name}** attaché ({len(text)} car.) — posez votre question.",
                    False,
                )
                self._input.setPlaceholderString_(f"Question sur {name}…")
            else:
                self.append_message_safe(
                    "Lucie",
                    f"⚠️ Impossible de lire **{name}**. Formats supportés : PDF, DOCX, TXT, MD.",
                    False,
                )

    @objc.python_method  # type: ignore[untyped-decorator]
    def _read_file_text(self, path: str) -> Optional[str]:
        """Extract text from a supported file using the standalone pipeline's extractor."""
        try:
            from lucie_v1_standalone.dossier_analyzer import extract_text
            from pathlib import Path as _Path
            return extract_text(_Path(path))
        except Exception as e:
            logger.error(f"_read_file_text({path}): {e}")
            return None

    # ── Query processing ──────────────────────────────────────────────────────

    def _process_query(self, query: str) -> None:
        import asyncio as _asyncio
        try:
            # Snapshot and clear drop state
            document = self._current_document
            dossier_path = self._current_dossier_path
            self._current_document = None
            self._current_dossier_path = None

            # ── 3-level routing ───────────────────────────────────────────────
            from lucie_v1_standalone.router import route as lv1_route
            routing = lv1_route(query, document_text=document)
            level = routing["level"]

            if dossier_path:
                # ── Dossier mode: batch analysis with progress ─────────────
                from lucie_v1_standalone import dossier_analyzer as _da

                def _progress(current: int, total: int) -> None:
                    AppHelper.callAfter(
                        self._thinking_label.setStringValue_,
                        f"Dossier {current}/{total}…",
                    )

                report = _asyncio.run(
                    _da.analyze_dossier(
                        folder_path=dossier_path,
                        instruction=query or "Analyse juridique complète du dossier",
                        verbose=False,
                        progress_callback=_progress,
                    )
                )
                response = _da.format_report(report)

            elif level == "direct":
                # ── Fast path: existing engine (greetings, simple questions) ─
                assert self.engine is not None
                response, _ = self.engine.process(query)

            else:
                # ── Legal pipeline: search (juridique) or document (avec texte)
                from lucie_v1_standalone import pipeline as _lv1
                response = _asyncio.run(
                    _lv1.run(
                        query,
                        document_text=document,
                        force=False,
                        verbose=False,
                    )
                )

            if not response or not str(response).strip():
                response = "(Aucune réponse générée)"

            # Reset placeholder after successful response
            AppHelper.callAfter(
                self._input.setPlaceholderString_, "Commande ou question…"
            )
            AppHelper.callAfter(self._start_streaming, "Lucie", str(response), False)

        except Exception as e:
            logger.error(f"Erreur _process_query: {e}", exc_info=True)
            AppHelper.callAfter(self._on_response_error, f"Erreur : {e}")

    # ── Streaming (word-chunk mode) ───────────────────────────────────────────

    def _start_streaming(self, sender: str, full_text: Any, user: bool = False) -> None:
        if self._streaming_timer is not None:
            self._streaming_timer.invalidate()
            self._streaming_timer = None

        self._streaming_sender = sender
        self._streaming_full_text = str(full_text) if full_text else ""
        self._streaming_text = ""
        self._streaming_index = 0

        storage = self._text_view.textStorage()
        start_pos = len(storage.string())
        self.append_message_safe(sender, "", user)
        end_pos = len(storage.string())
        self._streaming_range = (start_pos, end_pos)

        self._streaming_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            _STREAM_INTERVAL, self, "streamingTimerFired:", None, True
        )

    @objc.IBAction  # type: ignore[untyped-decorator]
    def streamingTimerFired_(self, timer: Any) -> None:
        remaining = len(self._streaming_full_text) - self._streaming_index
        if remaining <= 0:
            timer.invalidate()
            self._streaming_timer = None
            self._is_processing = False
            latency = time.time() - self._processing_start_time
            self._thinking_indicator.stopAnimating()
            self._thinking_label.setAlphaValue_(0.0)
            self._latency_label.setStringValue_(f"{latency:.2f}s")
            self._set_status("●", _green(), "Prêt")
            self._send_btn.setEnabled_(True)
            self._is_dragging = False
            # Success sound + notification
            try:
                AppKit.NSSound.soundNamed_("Hero").play()
            except Exception:
                pass
            self._send_notification("Lucie", f"Réponse prête en {latency:.1f}s")
            # Onboarding: schedule next step
            next_step = getattr(self, "_onboard_next_step", None)
            if next_step is not None:
                self._onboard_next_step = None
                AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    1.5, self, "onboardNextStep:", None, False
                )
                self._onboard_next_step_fn = next_step
            return

        # Advance by chunk (word-boundary-friendly: 4 chars)
        chunk_size = min(_STREAM_CHUNK, remaining)
        chunk = self._streaming_full_text[
            self._streaming_index: self._streaming_index + chunk_size
        ]
        self._streaming_text += chunk
        self._streaming_index += chunk_size

        storage = self._text_view.textStorage()
        if self._streaming_range is None:
            return
        start, end = self._streaming_range

        is_user = self._streaming_sender == "Toi"
        sender_color = ns_color(0.6, 0.8, 1.0, 0.9) if is_user else _accent(0.9)
        sender_attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_weight_(
                10, AppKit.NSFontWeightMedium
            ),
            AppKit.NSForegroundColorAttributeName: sender_color,
        }
        msg_attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(12.5),
            AppKit.NSForegroundColorAttributeName: ns_white(0.92, 0.9),
        }
        new_attributed = AppKit.NSMutableAttributedString.alloc().init()
        new_attributed.appendAttributedString_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(
                f"{self._streaming_sender}\n", sender_attrs
            )
        )
        new_attributed.appendAttributedString_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(
                f"{self._streaming_text}\n", msg_attrs
            )
        )
        storage.replaceCharactersInRange_withAttributedString_(
            Foundation.NSMakeRange(start, end - start), new_attributed
        )
        new_len = len(new_attributed.string())
        self._streaming_range = (start, start + new_len)

        self._text_view.setNeedsDisplay_(True)
        total_len = len(storage.string())
        self._text_view.scrollRangeToVisible_(Foundation.NSMakeRange(total_len, 0))

    def _on_response_error(self, error_text: str) -> None:
        self.append_message_safe("Lucie", error_text, False)
        self._thinking_indicator.stopAnimating()
        self._thinking_label.setAlphaValue_(0.0)
        self._set_status("●", _red(), "Erreur")
        self._send_btn.setEnabled_(True)
        self._is_processing = False
        self._is_dragging = False
        try:
            AppKit.NSSound.soundNamed_("Basso").play()
        except Exception:
            pass

    # ── Message display ───────────────────────────────────────────────────────

    @objc.python_method  # type: ignore[untyped-decorator]
    def append_message_safe(self, sender: str, text: str, user: bool = True) -> None:
        """Thread-safe append to text area."""
        if threading.current_thread().name != "MainThread":
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                self._append_message_on_main, (sender, text, user), False
            )
        else:
            self._append_message_on_main((sender, text, user))

    @objc.python_method  # type: ignore[untyped-decorator]
    def _append_message_on_main(self, args: Any) -> None:
        sender, text, user = args
        storage = self._text_view.textStorage()
        current = storage.string()
        prefix = "\n" if current else ""

        sender_color = ns_color(0.6, 0.8, 1.0, 0.9) if user else _accent(0.9)
        sender_attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_weight_(
                10, AppKit.NSFontWeightMedium
            ),
            AppKit.NSForegroundColorAttributeName: sender_color,
        }
        msg_attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(12.5),
            AppKit.NSForegroundColorAttributeName: ns_white(0.92, 0.9),
        }
        full = AppKit.NSMutableAttributedString.alloc().init()
        full.appendAttributedString_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(
                f"{prefix}{sender}\n", sender_attrs
            )
        )
        full.appendAttributedString_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(
                f"{text}\n", msg_attrs
            )
        )
        storage.appendAttributedString_(full)
        self._text_view.setNeedsDisplay_(True)
        self._text_view.displayIfNeeded()
        end = storage.length()
        self._text_view.scrollRangeToVisible_(Foundation.NSMakeRange(end, 0))
        sv = self._text_view.enclosingScrollView()
        if sv:
            sv.setNeedsDisplay_(True)
            sv.displayIfNeeded()

    # ── File card display ─────────────────────────────────────────────────────

    @objc.python_method  # type: ignore[untyped-decorator]
    def format_file_card(self, filepath: str, agent_name: str = "Agent") -> Any:
        """Build an NSAttributedString card for a file result.

        The filename is rendered as a clickable link (file:// URL).
        The textView_clickedOnLink_atIndex_ delegate method opens it.
        """
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filename)[1].lower()
        icon_map = {
            ".pdf": "📄", ".docx": "📝", ".doc": "📝", ".txt": "📋",
            ".xlsx": "📊", ".csv": "📊", ".py": "🐍", ".md": "📖",
            ".png": "🖼", ".jpg": "🖼", ".jpeg": "🖼",
            ".mp3": "🎵", ".mp4": "🎬", ".zip": "📦",
        }
        icon = icon_map.get(ext, "📁")

        card = AppKit.NSMutableAttributedString.alloc().init()

        # Agent badge line
        badge_attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_weight_(
                9, AppKit.NSFontWeightMedium
            ),
            AppKit.NSForegroundColorAttributeName: _accent(0.8),
        }
        storage = self._text_view.textStorage()
        prefix = "\n" if storage.string() else ""
        card.appendAttributedString_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(
                f"{prefix}{agent_name}  →  ", badge_attrs
            )
        )

        # Filename as clickable link
        file_url = AppKit.NSURL.fileURLWithPath_(filepath)
        link_attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(12.5),
            AppKit.NSForegroundColorAttributeName: ns_white(0.92, 0.95),
            AppKit.NSLinkAttributeName: file_url,
        }
        card.appendAttributedString_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(
                f"{icon} {filename}", link_attrs
            )
        )

        # Directory path hint
        dir_path = os.path.dirname(filepath)
        path_attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(9),
            AppKit.NSForegroundColorAttributeName: ns_white(0.45, 0.7),
        }
        card.appendAttributedString_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(
                f"\n{dir_path}\n", path_attrs
            )
        )
        return card

    @objc.python_method  # type: ignore[untyped-decorator]
    def show_file_card(self, filepath: str, agent_name: str = "Agent") -> None:
        """Display a file result card. Thread-safe."""
        def _on_main() -> None:
            card = self.format_file_card(filepath, agent_name)
            storage = self._text_view.textStorage()
            storage.appendAttributedString_(card)
            self._text_view.setNeedsDisplay_(True)
            end = storage.length()
            self._text_view.scrollRangeToVisible_(Foundation.NSMakeRange(end, 0))
        AppHelper.callAfter(_on_main)

    # ── NSTextView delegate — clickable file links ────────────────────────────

    def textView_clickedOnLink_atIndex_(
        self, text_view: Any, link: Any, char_index: int
    ) -> bool:
        """Open file:// links in Finder/default app when clicked in the text view."""
        try:
            if isinstance(link, AppKit.NSURL) and link.isFileURL():
                AppKit.NSWorkspace.sharedWorkspace().openURL_(link)
                return True
        except Exception as e:
            logger.debug(f"Link click: {e}")
        return False

    # ── Status helpers ────────────────────────────────────────────────────────

    @objc.python_method  # type: ignore[untyped-decorator]
    def _set_status(self, dot: str, color: Any, label: str) -> None:
        self._status.setStringValue_(dot)
        self._status.setTextColor_(color)
        self._status_text.setStringValue_(label)

    @objc.python_method  # type: ignore[untyped-decorator]
    def update_agent_status(self, agents: Dict[str, bool]) -> None:
        """Update the agent strip. agents = {name: is_active}"""
        parts = [("● " if active else "○ ") + name for name, active in agents.items()]
        self._agents_label.setStringValue_("  ".join(parts))

    @objc.python_method  # type: ignore[untyped-decorator]
    def set_llm_status(self, connected: bool) -> None:
        """Update Ollama connection indicator."""
        if connected:
            self._llm_dot.setTextColor_(_green())
            self._llm_label.setStringValue_("Ollama")
        else:
            self._llm_dot.setTextColor_(_red())
            self._llm_label.setStringValue_("Ollama ✗")

    def updateEnergyIndicator_(self, timer: Any) -> None:
        engine = getattr(self, "engine", None)
        if engine is None or not hasattr(engine, "energy"):
            return
        try:
            status = engine.energy.get_status_for_hud()
            mode = status.get("mode", "balanced")
            thermal = status.get("thermal_name", "nominal")
            mode_labels = {
                "performance": "Perf", "balanced": "Balanced",
                "eco": "Eco", "critical": "Chauffe",
            }
            thermal_colors = {
                "nominal": _green(),
                "fair": ns_color(1.0, 0.85, 0.2, 0.8),
                "serious": _orange(),
                "critical": _red(),
            }
            label = mode_labels.get(mode, mode)
            color = thermal_colors.get(thermal, _green())
            battery_pct = status.get("battery_percent")
            if battery_pct is not None and status.get("on_battery"):
                text = f"{label} | {battery_pct}%"
            else:
                text = label
            self._energy_label.setStringValue_(text)
            self._energy_label.setTextColor_(color)
        except Exception:
            pass

    # ── Onboarding timer callbacks ────────────────────────────────────────────

    @objc.IBAction  # type: ignore[untyped-decorator]
    def onboardCleanup_(self, timer: Any) -> None:
        fn: Optional[Any] = getattr(self, "_onboard_cleanup", None)
        if fn is not None:
            fn()
            self._onboard_cleanup = None

    @objc.IBAction  # type: ignore[untyped-decorator]
    def onboardNextStep_(self, timer: Any) -> None:
        fn: Optional[Any] = getattr(self, "_onboard_next_step_fn", None)
        if fn is not None:
            self._onboard_next_step_fn = None
            fn()

    # ── Window appearance animation ───────────────────────────────────────────

    @objc.python_method  # type: ignore[untyped-decorator]
    def animateIn(self) -> None:
        """Spring entrance: scale 0.95→1.0 + fade-in."""
        self.setAlphaValue_(0.0)
        content = self.contentView()
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.25)
        self.animator().setAlphaValue_(ALPHA)
        AppKit.NSAnimationContext.endGrouping()
        layer = content.layer()
        anim = Quartz.CABasicAnimation.animationWithKeyPath_("transform.scale")
        anim.setFromValue_(0.95)
        anim.setToValue_(1.0)
        anim.setDuration_(0.3)
        anim.setTimingFunction_(
            Quartz.CAMediaTimingFunction.functionWithName_(
                Quartz.kCAMediaTimingFunctionEaseOut
            )
        )
        layer.addAnimation_forKey_(anim, "springIn")

    @objc.python_method  # type: ignore[untyped-decorator]
    def _show_drop_highlight(self, visible: bool) -> None:
        """Show/hide blue drop-target border."""
        self._drop_highlight.setAlphaValue_(1.0 if visible else 0.0)

    @objc.python_method  # type: ignore[untyped-decorator]
    def _send_notification(self, title: str, body: str) -> None:
        """Send a macOS user notification."""
        try:
            note = AppKit.NSUserNotification.alloc().init()
            note.setTitle_(title)
            note.setInformativeText_(body)
            centre = AppKit.NSUserNotificationCenter.defaultUserNotificationCenter()
            centre.deliverNotification_(note)
        except Exception as e:
            logger.debug(f"Notification error: {e}")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        if hasattr(self, "_energy_timer") and self._energy_timer:
            self._energy_timer.invalidate()
        if hasattr(self, "_typing_timer") and self._typing_timer:
            self._typing_timer.invalidate()
        nc = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        nc.removeObserver_(self)
        objc.super(HUDWindow, self).close()


# ─── AppDelegate ─────────────────────────────────────────────────────────────
class AppDelegate(AppKit.NSObject):  # type: ignore[misc]
    def initWithEngine_(self, engine: Any) -> Any:
        self = objc.super(AppDelegate, self).init()
        if self is not None:
            self.engine = engine
        return self

    def applicationDidFinishLaunching_(self, notification: Any) -> None:
        try:
            self.window = HUDWindow.alloc().init()
            self.window.engine = self.engine

            self.window.makeKeyAndOrderFront_(None)
            self.window.orderFrontRegardless()
            self.window.display()
            self.window.animateIn()

            if hasattr(self.window, "_input"):
                self.window.makeFirstResponder_(self.window._input)

            centre = AppKit.NSUserNotificationCenter.defaultUserNotificationCenter()
            centre.setDelegate_(self)
            logger.info("HUD prêt")
        except Exception as e:
            logger.error(f"Erreur initialisation : {e}", exc_info=True)
            sys.exit(1)

    def userNotificationCenter_didActivateNotification_(
        self, center: Any, notification: Any
    ) -> None:
        user_info = notification.userInfo()
        if user_info and user_info.get("action") == "open_file":
            filepath = user_info.get("filepath")
            if filepath and os.path.exists(filepath):
                subprocess.run(["open", filepath])

    def applicationWillTerminate_(self, notification: Any) -> None:
        if hasattr(self, "engine"):
            self.engine.stop()


# ─── Entry point ─────────────────────────────────────────────────────────────
def run_hud(engine: Optional[Any] = None) -> None:
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    if engine is None:
        config = Config()
        engine = LucidEngine(config)

    delegate = AppDelegate.alloc().initWithEngine_(engine)
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    run_hud()
