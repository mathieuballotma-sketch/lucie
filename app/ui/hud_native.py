# app/ui/hud_native.py
# HUD v3 — Design Apple-quality, machine à états, spring animations

from __future__ import annotations

# Configurer le root logger AVANT tout autre import qui instancie des loggers
# (pipeline, intent_classifier, retriever, …). Sans ça, les logger.info() du
# namespace lucie_v1_standalone.* sont silencieusement jetés et Mathieu ne voit
# rien dans son terminal malgré PYTHONUNBUFFERED=1.
from lucie_v1_standalone.logging_config import setup_logging

setup_logging()

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
ALPHA = 0.82  # légèrement plus opaque pour meilleur contraste en light mode

# Pre-computed Y positions (0 = bottom of window in AppKit coords)
_STATUS_Y = 6                                        # bottom status bar
_INPUT_Y = _STATUS_Y + STATUS_H + 6                 # 32
_INPUT_TOP = _INPUT_Y + INPUT_H                     # 72
_TEXT_Y = _INPUT_TOP + PADDING                      # 86
_HEADER_Y = WINDOW_H - HEADER_H                     # 444
_AGENT_BAR_Y = _HEADER_Y - AGENT_BAR_H             # 422
_TEXT_H = _AGENT_BAR_Y - 2 - _TEXT_Y               # 334
_TEXT_W = WINDOW_W - PADDING * 2                    # 492

# Pipeline stages zone (« Lucie réfléchit »), insérée au-dessus du texte
# quand le pipeline travaille. Dimensions : 4 lignes * 16px + gaps + padding.
_STAGES_H = 80                                      # hauteur de la zone
_STAGES_Y = _AGENT_BAR_Y - 2 - _STAGES_H           # 340 (juste sous sep2)
_TEXT_H_ACTIVE = _STAGES_Y - 4 - _TEXT_Y           # 250 (text scroll réduit)
_RETRY_H = 22                                       # hauteur du bouton Ré-essayer

# Streaming parameters — word-chunk feel
_STREAM_CHUNK = 4        # chars advanced per timer tick
_STREAM_INTERVAL = 0.04  # seconds between ticks (~100 chars/s)


# ─── State machine ───────────────────────────────────────────────────────────

class LucieState:
    IDLE      = "idle"
    THINKING  = "thinking"
    SEARCHING = "searching"
    WRITING   = "writing"
    EXECUTING = "executing"
    DONE      = "done"
    ERROR     = "error"


# (dot_rgba, status_text, sound_name_or_None)
_STATE_CONFIG: Dict[str, Tuple[Tuple[float, ...], str, Optional[str]]] = {
    LucieState.IDLE:      ((0.20, 0.85, 0.40, 0.9), "Prête",                   None),
    LucieState.THINKING:  ((1.00, 0.60, 0.00, 0.9), "Lucie réfléchit…",       None),
    LucieState.SEARCHING: ((0.27, 0.52, 0.97, 0.9), "Recherche en cours…",    None),
    LucieState.WRITING:   ((0.70, 0.40, 1.00, 0.9), "Rédaction en cours…",    None),
    LucieState.EXECUTING: ((1.00, 0.60, 0.00, 0.9), "Exécution…",             "Funk"),
    LucieState.DONE:      ((0.20, 0.85, 0.40, 0.9), "Terminé",                "Hero"),
    LucieState.ERROR:     ((1.00, 0.25, 0.20, 0.9), "Erreur",                 "Basso"),
}


# ─── Color helpers ───────────────────────────────────────────────────────────
def ns_color(r: float, g: float, b: float, a: float = 1.0) -> Any:
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a)


def ns_white(w: float, a: float = 1.0) -> Any:
    return AppKit.NSColor.colorWithCalibratedWhite_alpha_(w, a)


def _adaptive_text() -> Any:
    """Couleur du texte principal — noir en light, blanc en dark."""
    return AppKit.NSColor.labelColor()


def _adaptive_secondary() -> Any:
    """Couleur texte secondaire — adapte automatiquement au mode."""
    return AppKit.NSColor.secondaryLabelColor()


def _adaptive_tertiary() -> Any:
    """Couleur texte tertiaire (hints, timestamps)."""
    return AppKit.NSColor.tertiaryLabelColor()


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


def ns_color_hex(hex_str: str, a: float = 1.0) -> Any:
    """`#rrggbb` → NSColor sRGB. Alpha optionnel (multiplicateur)."""
    s = hex_str.lstrip("#")
    r = int(s[0:2], 16) / 255.0
    g = int(s[2:4], 16) / 255.0
    b = int(s[4:6], 16) / 255.0
    return ns_color(r, g, b, a)


# Palette carte document pro + ProposalCard
CARD_BG_LIGHT = ns_color_hex("#fafaf8")
CARD_BORDER_SUBTLE = ns_color_hex("#000000", 0.08)
ACCENT_NAVY = ns_color_hex("#1a2847")
ACCENT_NAVY_HOVER = ns_color_hex("#24345c")


# ─── ProgressLineView ────────────────────────────────────────────────────────
class ProgressLineView(AppKit.NSView):  # type: ignore[misc]
    """Ligne lumineuse fine (3px) en haut du HUD, pulse doucement pendant le traitement.

    Utilise un CAGradientLayer qui change de couleur selon l'état :
    thinking=orange, searching=bleu, writing=violet, done/error=fade out.
    """
    _LINE_H: float = 3.0

    def initWithFrame_(self, frame: Any) -> Any:
        self = objc.super(ProgressLineView, self).initWithFrame_(frame)
        if self is not None:
            self.setWantsLayer_(True)
            # Track de fond très subtil
            track = Quartz.CALayer.layer()
            track.setFrame_(Quartz.CGRectMake(0, 0, WINDOW_W, self._LINE_H))
            track.setBackgroundColor_(ns_white(1.0, 0.06).CGColor())
            self.layer().addSublayer_(track)
            # Gradient lumineux (scan horizontal)
            self._glow = Quartz.CAGradientLayer.layer()
            self._glow.setFrame_(Quartz.CGRectMake(0, 0, WINDOW_W, self._LINE_H))
            self._glow.setStartPoint_(Quartz.CGPointMake(0.0, 0.5))
            self._glow.setEndPoint_(Quartz.CGPointMake(1.0, 0.5))
            self._set_glow_color((0.27, 0.52, 0.97, 0.9))
            self.layer().addSublayer_(self._glow)
            self.setAlphaValue_(0.0)
        return self

    def _set_glow_color(self, rgba: Tuple[float, ...]) -> None:
        r, g, b, _ = rgba
        c0 = ns_color(r, g, b, 0.0).CGColor()
        c1 = ns_color(r, g, b, 0.9).CGColor()
        c2 = ns_color(r, g, b, 0.0).CGColor()
        self._glow.setColors_([c0, c1, c2])

    def start_pulsing(self, rgba: Tuple[float, ...]) -> None:
        """Affiche et pulse la ligne avec la couleur de l'état actif."""
        self._set_glow_color(rgba)
        self._glow.removeAllAnimations()
        # Pulse opacité
        pulse = Quartz.CABasicAnimation.animationWithKeyPath_("opacity")
        pulse.setFromValue_(0.25)
        pulse.setToValue_(1.0)
        pulse.setDuration_(0.9)
        pulse.setAutoreverses_(True)
        pulse.setRepeatCount_(float("inf"))
        pulse.setTimingFunction_(
            Quartz.CAMediaTimingFunction.functionWithName_(
                Quartz.kCAMediaTimingFunctionEaseInEaseOut
            )
        )
        self._glow.addAnimation_forKey_(pulse, "pulse")
        # Fade in view
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.2)
        self.animator().setAlphaValue_(1.0)
        AppKit.NSAnimationContext.endGrouping()

    def stop_pulsing(self) -> None:
        """Arrête la pulse et fait disparaître la ligne."""
        self._glow.removeAllAnimations()
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.4)
        self.animator().setAlphaValue_(0.0)
        AppKit.NSAnimationContext.endGrouping()

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


# ─── PipelineStagesView ──────────────────────────────────────────────────────
class PipelineStagesView(AppKit.NSView):  # type: ignore[misc]
    """Zone "Lucie réfléchit" — liste verticale d'étapes avec état visuel.

    Rendu minimal, une ligne par étape : icône d'état (⏸ ⏳ ✅ ❌) à gauche,
    libellé utilisateur (traduit depuis le nom interne via stage_labels) au
    milieu, durée à droite (affichée après complétion).

    Les noms techniques internes (lecteur, retriever, redacteur, verificateur)
    restent à l'intérieur et ne sont JAMAIS affichés — protection IP + UX.
    Les libellés affichés arrivent déjà traduits par l'appelant.

    Les lignes sont créées dynamiquement au fur et à mesure que les events
    arrivent. Ordre = ordre d'arrivée de started pour chaque stage.
    """

    _ROW_H: float = 16.0
    _ROW_GAP: float = 2.0
    _ICON_W: float = 20.0
    _DUR_W: float = 72.0
    _TOP_PAD: float = 6.0
    _MAX_ROWS: int = 4

    def initWithFrame_(self, frame: Any) -> Any:
        self = objc.super(PipelineStagesView, self).initWithFrame_(frame)
        if self is not None:
            self.setWantsLayer_(True)
            self._rows: Dict[str, Dict[str, Any]] = {}
            self._order: List[str] = []
        return self

    def isOpaque(self) -> bool:
        return False

    def reset(self) -> None:
        """Vide toutes les lignes — à appeler en début de nouvelle requête."""
        for row in self._rows.values():
            for view in (row["icon"], row["label"], row["duration"]):
                view.removeFromSuperview()
        self._rows.clear()
        self._order.clear()
        self.setAlphaValue_(0.0)
        self.setHidden_(True)

    def _create_row(self, stage_key: str, label_text: str) -> Dict[str, Any]:
        idx = len(self._order)
        frame_h = float(self.frame().size.height)
        y = frame_h - self._TOP_PAD - (idx + 1) * self._ROW_H - idx * self._ROW_GAP
        width = float(self.frame().size.width)

        icon = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(0.0, y, self._ICON_W, self._ROW_H)
        )
        icon.setStringValue_("⏳")
        icon.setEditable_(False)
        icon.setBezeled_(False)
        icon.setDrawsBackground_(False)
        icon.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        icon.setTextColor_(_adaptive_tertiary())
        icon.setAlignment_(AppKit.NSTextAlignmentCenter)
        icon.setWantsLayer_(True)
        self.addSubview_(icon)

        label_x = self._ICON_W + 4.0
        label_w = width - label_x - self._DUR_W - 4.0
        label = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(label_x, y, label_w, self._ROW_H)
        )
        label.setStringValue_(label_text)
        label.setEditable_(False)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setFont_(AppKit.NSFont.systemFontOfSize_(11.5))
        label.setTextColor_(_adaptive_text())
        label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
        self.addSubview_(label)

        dur = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(width - self._DUR_W, y, self._DUR_W, self._ROW_H)
        )
        dur.setStringValue_("")
        dur.setEditable_(False)
        dur.setBezeled_(False)
        dur.setDrawsBackground_(False)
        dur.setFont_(AppKit.NSFont.systemFontOfSize_(10))
        dur.setTextColor_(_adaptive_tertiary())
        dur.setAlignment_(AppKit.NSTextAlignmentRight)
        self.addSubview_(dur)

        return {
            "icon": icon,
            "label": label,
            "duration": dur,
            "state": "pending",
            "base_label": label_text,
        }

    def ensure_row(self, stage_key: str, label_text: str) -> None:
        """Crée la ligne pour ce stage si elle n'existe pas déjà."""
        if stage_key in self._rows:
            return
        if len(self._order) >= self._MAX_ROWS:
            return
        self._rows[stage_key] = self._create_row(stage_key, label_text)
        self._order.append(stage_key)

    def mark_started(self, stage_key: str, label_text: str) -> None:
        self.ensure_row(stage_key, label_text)
        row = self._rows.get(stage_key)
        if row is None:
            return
        row["state"] = "started"
        row["icon"].setStringValue_("⏳")
        row["icon"].setTextColor_(_accent())
        row["label"].setTextColor_(_adaptive_text())
        row["label"].setStringValue_(label_text)
        row["base_label"] = label_text
        # Pulse opacity sur l'icône
        layer = row["icon"].layer()
        if layer is not None:
            layer.removeAllAnimations()
            pulse = Quartz.CABasicAnimation.animationWithKeyPath_("opacity")
            pulse.setFromValue_(0.35)
            pulse.setToValue_(1.0)
            pulse.setDuration_(0.85)
            pulse.setAutoreverses_(True)
            pulse.setRepeatCount_(float("inf"))
            pulse.setTimingFunction_(
                Quartz.CAMediaTimingFunction.functionWithName_(
                    Quartz.kCAMediaTimingFunctionEaseInEaseOut
                )
            )
            layer.addAnimation_forKey_(pulse, "pulse")

    def mark_completed(self, stage_key: str, duration_ms: float) -> None:
        row = self._rows.get(stage_key)
        if row is None:
            return
        row["state"] = "completed"
        row["icon"].setStringValue_("✓")
        row["icon"].setTextColor_(_green())
        layer = row["icon"].layer()
        if layer is not None:
            layer.removeAllAnimations()
        if duration_ms > 0:
            secs = duration_ms / 1000.0
            row["duration"].setStringValue_(f"{secs:.1f} s".replace(".", ","))

    def mark_error(self, stage_key: str, message: str, label_text: str) -> None:
        self.ensure_row(stage_key, label_text)
        row = self._rows.get(stage_key)
        if row is None:
            return
        row["state"] = "error"
        row["icon"].setStringValue_("✕")
        row["icon"].setTextColor_(_red())
        layer = row["icon"].layer()
        if layer is not None:
            layer.removeAllAnimations()
        short = message.strip()
        if len(short) > 48:
            short = short[:48] + "…"
        if short:
            row["label"].setStringValue_(f"{row['base_label']} — {short}")
        row["label"].setTextColor_(_red())

    def fade_in(self) -> None:
        self.setHidden_(False)
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.15)
        self.animator().setAlphaValue_(1.0)
        AppKit.NSAnimationContext.endGrouping()

    def fade_out(self, duration: float = 0.4, on_complete: Any = None) -> None:
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(duration)
        if on_complete is not None:
            AppKit.NSAnimationContext.currentContext().setCompletionHandler_(on_complete)
        self.animator().setAlphaValue_(0.0)
        AppKit.NSAnimationContext.endGrouping()

    def any_error(self) -> bool:
        return any(r.get("state") == "error" for r in self._rows.values())


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

    def mouseDownCanMoveWindow(self) -> bool:
        # Non-opaque view — must return True so setMovableByWindowBackground_ works
        return True

    def mouseDown_(self, event: Any) -> None:
        # Clicks reaching the content view (empty background) become window drags
        self.window().performWindowDragWithEvent_(event)

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


# ─── DraggableFileCard ────────────────────────────────────────────────────────
class DraggableFileCard(AppKit.NSView):  # type: ignore[misc]
    """Carte document premium — drag-to-Finder + double-clic pour NSSavePanel.

    - Rendu premium : fond clair, ombre douce, icône du type de fichier, nom +
      métadonnées (kind · taille · date).
    - Simple clic/drag → commence une session de drag vers Finder/Mail/Slack.
    - Double-clic → ouvre NSSavePanel pour ranger le fichier où l'avocat veut.
    - Clic droit → menu contextuel (Ouvrir / Enregistrer sous / Copier chemin).
    """

    _CARD_W: int = 380
    _CARD_H: int = 72
    # Seuil minimal de déplacement avant de déclencher un drag (évite drag parasite).
    _DRAG_THRESHOLD: float = 4.0

    def initWithFrame_(self, frame: Any) -> Any:
        self = objc.super(DraggableFileCard, self).initWithFrame_(frame)
        if self is not None:
            self._path: Optional[str] = None
            self._mouse_down_loc: Optional[Any] = None
            self._hud_ref: Optional[Any] = None  # set by HUDWindow.handle_dropped_path
            self._hovered: bool = False
            self.setWantsLayer_(True)
            layer = self.layer()
            layer.setCornerRadius_(10.0)
            layer.setBackgroundColor_(CARD_BG_LIGHT.CGColor())
            layer.setBorderWidth_(1.0)
            layer.setBorderColor_(CARD_BORDER_SUBTLE.CGColor())

            # Ombre douce : offset (0, -2 en coords AppKit = vers le bas visuellement),
            # blur 24, alpha 0.08. NSShadow est attaché via setShadow_.
            shadow = AppKit.NSShadow.alloc().init()
            shadow.setShadowOffset_(AppKit.NSMakeSize(0, -2))
            shadow.setShadowBlurRadius_(24.0)
            shadow.setShadowColor_(
                AppKit.NSColor.colorWithWhite_alpha_(0.0, 0.08)
            )
            self.setShadow_(shadow)

            # Icône du type de fichier (24×24).
            icon_size = 24
            icon_x = 14
            icon_y = (self._CARD_H - icon_size) / 2
            self._icon_view = AppKit.NSImageView.alloc().initWithFrame_(
                make_rect(icon_x, icon_y, icon_size, icon_size)
            )
            self._icon_view.setImageScaling_(AppKit.NSImageScaleProportionallyDown)
            self.addSubview_(self._icon_view)

            # Nom du fichier (titre, 14pt semibold).
            text_x = icon_x + icon_size + 12
            text_w = self._CARD_W - text_x - 48  # 48 = espace à droite pour "drag →"
            self._label = AppKit.NSTextField.alloc().initWithFrame_(
                make_rect(text_x, self._CARD_H - 34, text_w, 20)
            )
            self._label.setStringValue_("—")
            self._label.setEditable_(False)
            self._label.setBezeled_(False)
            self._label.setDrawsBackground_(False)
            self._label.setFont_(
                AppKit.NSFont.systemFontOfSize_weight_(14, AppKit.NSFontWeightSemibold)
            )
            self._label.setTextColor_(AppKit.NSColor.labelColor())
            self._label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingMiddle)
            self.addSubview_(self._label)

            # Métadonnées (12pt regular, gris).
            self._meta = AppKit.NSTextField.alloc().initWithFrame_(
                make_rect(text_x, 12, text_w, 18)
            )
            self._meta.setStringValue_("")
            self._meta.setEditable_(False)
            self._meta.setBezeled_(False)
            self._meta.setDrawsBackground_(False)
            self._meta.setFont_(AppKit.NSFont.systemFontOfSize_(12))
            self._meta.setTextColor_(AppKit.NSColor.secondaryLabelColor())
            self._meta.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
            self.addSubview_(self._meta)

            # Hint "drag →" discret à droite.
            hint = AppKit.NSTextField.alloc().initWithFrame_(
                make_rect(self._CARD_W - 44, (self._CARD_H - 14) / 2, 36, 14)
            )
            hint.setStringValue_("drag →")
            hint.setEditable_(False)
            hint.setBezeled_(False)
            hint.setDrawsBackground_(False)
            hint.setFont_(AppKit.NSFont.systemFontOfSize_(9))
            hint.setTextColor_(AppKit.NSColor.tertiaryLabelColor())
            hint.setAlignment_(AppKit.NSTextAlignmentRight)
            self.addSubview_(hint)

            # Tracking area pour le hover.
            self._update_tracking_area()
        return self

    @objc.python_method  # type: ignore[untyped-decorator]
    def _update_tracking_area(self) -> None:
        # Nettoyage + ré-installation (à appeler sur resize)
        for area in list(self.trackingAreas() or []):
            self.removeTrackingArea_(area)
        area = AppKit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            (
                AppKit.NSTrackingMouseEnteredAndExited
                | AppKit.NSTrackingActiveInKeyWindow
                | AppKit.NSTrackingInVisibleRect
            ),
            self,
            None,
        )
        self.addTrackingArea_(area)

    def updateTrackingAreas(self) -> None:
        objc.super(DraggableFileCard, self).updateTrackingAreas()
        self._update_tracking_area()

    def mouseEntered_(self, event: Any) -> None:
        if self._hovered:
            return
        self._hovered = True
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.18)
        # Ombre plus marquée
        shadow = AppKit.NSShadow.alloc().init()
        shadow.setShadowOffset_(AppKit.NSMakeSize(0, -3))
        shadow.setShadowBlurRadius_(30.0)
        shadow.setShadowColor_(
            AppKit.NSColor.colorWithWhite_alpha_(0.0, 0.14)
        )
        self.animator().setShadow_(shadow)
        AppKit.NSAnimationContext.endGrouping()

    def mouseExited_(self, event: Any) -> None:
        if not self._hovered:
            return
        self._hovered = False
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.18)
        shadow = AppKit.NSShadow.alloc().init()
        shadow.setShadowOffset_(AppKit.NSMakeSize(0, -2))
        shadow.setShadowBlurRadius_(24.0)
        shadow.setShadowColor_(
            AppKit.NSColor.colorWithWhite_alpha_(0.0, 0.08)
        )
        self.animator().setShadow_(shadow)
        AppKit.NSAnimationContext.endGrouping()

    @objc.python_method  # type: ignore[untyped-decorator]
    def set_filepath(self, path: str) -> None:
        """Update the card to display the given file path."""
        self._path = path
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        self._label.setStringValue_(name)

        # Icône système du type de fichier (fallback emoji si indispo).
        try:
            workspace = AppKit.NSWorkspace.sharedWorkspace()
            icon = workspace.iconForFile_(path) if os.path.exists(path) else None
            if icon is None:
                icon = workspace.iconForFileType_(ext.lstrip(".") or "public.data")
            self._icon_view.setImage_(icon)
        except Exception:
            pass

        # Métadonnées : {type} · {taille} · {date}
        kind_labels = {
            ".docx": "Document Word", ".pdf": "PDF", ".md": "Markdown",
            ".txt": "Texte", ".rtf": "RTF",
        }
        kind_label = kind_labels.get(ext, ext.lstrip(".").upper() or "Fichier")
        try:
            size = os.path.getsize(path)
            if size < 1024:
                size_str = f"{size} o"
            elif size < 1024 * 1024:
                size_str = f"{size // 1024} Ko"
            else:
                size_str = f"{size / (1024 * 1024):.1f} Mo"
        except OSError:
            size_str = "—"
        from datetime import datetime as _dt
        try:
            mtime = _dt.fromtimestamp(os.path.getmtime(path))
            date_str = mtime.strftime("%d %b %Y").lower()
        except OSError:
            date_str = ""
        parts = [kind_label, size_str]
        if date_str:
            parts.append(date_str)
        self._meta.setStringValue_(" · ".join(parts))

    def mouseDown_(self, event: Any) -> None:
        # Double-clic → ouvrir NSSavePanel (enregistrer sous).
        if event.clickCount() == 2:
            self._open_save_panel()
            return
        self._mouse_down_loc = event.locationInWindow()

    def mouseDragged_(self, event: Any) -> None:
        if self._path is None or self._mouse_down_loc is None:
            return
        # Seuil minimal pour éviter de déclencher un drag sur un clic maintenu
        loc = event.locationInWindow()
        dx = loc.x - self._mouse_down_loc.x
        dy = loc.y - self._mouse_down_loc.y
        if (dx * dx + dy * dy) < (self._DRAG_THRESHOLD * self._DRAG_THRESHOLD):
            return
        pb_item = AppKit.NSPasteboardItem.alloc().init()
        url = AppKit.NSURL.fileURLWithPath_(self._path)
        pb_item.setString_forType_(url.absoluteString(), AppKit.NSPasteboardTypeFileURL)
        drag_item = AppKit.NSDraggingItem.alloc().initWithPasteboardWriter_(pb_item)
        icon = AppKit.NSWorkspace.sharedWorkspace().iconForFile_(self._path)
        frame_in_win = self.convertRect_toView_(self.bounds(), None)
        drag_item.setDraggingFrame_contents_(frame_in_win, icon)
        self.beginDraggingSessionWithItems_event_source_([drag_item], event, self)

    def mouseUp_(self, event: Any) -> None:
        self._mouse_down_loc = None

    def rightMouseDown_(self, event: Any) -> None:
        """Menu contextuel : Ouvrir / Enregistrer sous / Copier chemin / Supprimer."""
        if self._path is None:
            return
        menu = AppKit.NSMenu.alloc().initWithTitle_("")

        def _add(title: str, selector: str) -> None:
            item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, selector, ""
            )
            item.setTarget_(self)
            menu.addItem_(item)

        _add("Ouvrir", "contextOpen:")
        _add("Enregistrer sous…", "contextSaveAs:")
        _add("Copier le chemin", "contextCopyPath:")
        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        _add("Supprimer", "contextDelete:")

        AppKit.NSMenu.popUpContextMenu_withEvent_forView_(menu, event, self)

    @objc.IBAction  # type: ignore[untyped-decorator]
    def contextOpen_(self, sender: Any) -> None:
        if self._path and os.path.exists(self._path):
            AppKit.NSWorkspace.sharedWorkspace().openFile_(self._path)

    @objc.IBAction  # type: ignore[untyped-decorator]
    def contextSaveAs_(self, sender: Any) -> None:
        self._open_save_panel()

    @objc.IBAction  # type: ignore[untyped-decorator]
    def contextCopyPath_(self, sender: Any) -> None:
        if not self._path:
            return
        pb = AppKit.NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(self._path, AppKit.NSPasteboardTypeString)

    @objc.IBAction  # type: ignore[untyped-decorator]
    def contextDelete_(self, sender: Any) -> None:
        if self._path and os.path.exists(self._path):
            try:
                os.unlink(self._path)
            except OSError:
                pass
        self._path = None
        if self._hud_ref is not None and hasattr(self._hud_ref, "_hide_output_card"):
            self._hud_ref._hide_output_card()

    @objc.python_method  # type: ignore[untyped-decorator]
    def _open_save_panel(self) -> None:
        """Ouvre NSSavePanel et copie le fichier au chemin choisi par l'utilisateur."""
        if not self._path or not os.path.exists(self._path):
            return
        panel = AppKit.NSSavePanel.savePanel()
        panel.setNameFieldStringValue_(os.path.basename(self._path))
        ext = os.path.splitext(self._path)[1].lstrip(".")
        if ext:
            try:
                panel.setAllowedFileTypes_([ext])
            except Exception:
                pass
        try:
            home = os.path.expanduser("~/Documents")
            panel.setDirectoryURL_(AppKit.NSURL.fileURLWithPath_(home))
        except Exception:
            pass
        panel.setMessage_("Enregistrer le document dans Finder")
        panel.setPrompt_("Enregistrer")

        if panel.runModal() != AppKit.NSModalResponseOK:
            return
        dest_url = panel.URL()
        if dest_url is None or not dest_url.isFileURL():
            return
        dest = str(dest_url.path())
        try:
            import shutil
            shutil.copy(self._path, dest)
        except Exception as exc:
            logger.error(f"NSSavePanel copy failed: {exc}")
            return
        if self._hud_ref is not None and hasattr(self._hud_ref, "append_message_safe"):
            self._hud_ref.append_message_safe(
                "Lucie", f"✅ Enregistré dans {dest}", False
            )

    def draggingSession_sourceOperationMaskForDraggingContext_(
        self, session: Any, context: int
    ) -> int:
        return AppKit.NSDragOperationCopy

    def isOpaque(self) -> bool:
        return False


# ─── Button styles (helpers) ─────────────────────────────────────────────────

def _make_primary_button(frame: Any, title: str, target: Any, action: str) -> Any:
    """Bouton « accent navy » (fond bleu-nuit, texte blanc)."""
    btn = AppKit.NSButton.alloc().initWithFrame_(frame)
    btn.setBordered_(False)
    btn.setWantsLayer_(True)
    btn.layer().setCornerRadius_(6.0)
    btn.layer().setBackgroundColor_(ACCENT_NAVY.CGColor())
    btn.setTitle_(title)
    btn.setFont_(
        AppKit.NSFont.systemFontOfSize_weight_(12, AppKit.NSFontWeightMedium)
    )
    attr_title = AppKit.NSAttributedString.alloc().initWithString_attributes_(
        title,
        {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_weight_(
                12, AppKit.NSFontWeightMedium
            ),
            AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor(),
        },
    )
    btn.setAttributedTitle_(attr_title)
    btn.setTarget_(target)
    btn.setAction_(action)
    return btn


def _make_secondary_button(frame: Any, title: str, target: Any, action: str) -> Any:
    """Bouton outline discret (fond transparent, bord, texte label)."""
    btn = AppKit.NSButton.alloc().initWithFrame_(frame)
    btn.setBordered_(False)
    btn.setWantsLayer_(True)
    btn.layer().setCornerRadius_(6.0)
    btn.layer().setBorderWidth_(1.0)
    btn.layer().setBorderColor_(
        AppKit.NSColor.colorWithWhite_alpha_(0.0, 0.15).CGColor()
    )
    btn.layer().setBackgroundColor_(
        AppKit.NSColor.colorWithWhite_alpha_(1.0, 0.0).CGColor()
    )
    attr_title = AppKit.NSAttributedString.alloc().initWithString_attributes_(
        title,
        {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_weight_(
                12, AppKit.NSFontWeightRegular
            ),
            AppKit.NSForegroundColorAttributeName: AppKit.NSColor.labelColor(),
        },
    )
    btn.setAttributedTitle_(attr_title)
    btn.setTarget_(target)
    btn.setAction_(action)
    return btn


# ─── ProposalCardView ────────────────────────────────────────────────────────
class ProposalCardView(AppKit.NSView):  # type: ignore[misc]
    """Carte de proposition — texte + 2 boutons (Oui produire / Non).

    Utilisée quand le pipeline détecte une demande de production (rédige,
    projet de…) pour demander confirmation avant de dépenser les cycles LLM.

    Les callbacks (`_yes_block`, `_no_block`) sont des callables Python sans
    argument. Assignés via `configure(question, yes_cb, no_cb)`.
    """

    _CARD_W: int = 492  # WINDOW_W - PADDING * 2
    _CARD_H: int = 104  # 2 lignes de texte + gap + row de boutons

    def initWithFrame_(self, frame: Any) -> Any:
        self = objc.super(ProposalCardView, self).initWithFrame_(frame)
        if self is not None:
            self._yes_block: Optional[Any] = None
            self._no_block: Optional[Any] = None
            self.setWantsLayer_(True)
            layer = self.layer()
            layer.setCornerRadius_(10.0)
            layer.setBackgroundColor_(CARD_BG_LIGHT.CGColor())
            layer.setBorderWidth_(1.0)
            layer.setBorderColor_(CARD_BORDER_SUBTLE.CGColor())

            shadow = AppKit.NSShadow.alloc().init()
            shadow.setShadowOffset_(AppKit.NSMakeSize(0, -2))
            shadow.setShadowBlurRadius_(24.0)
            shadow.setShadowColor_(
                AppKit.NSColor.colorWithWhite_alpha_(0.0, 0.08)
            )
            self.setShadow_(shadow)

            # Texte de la question (2 lignes max, wrapping).
            text_h = 44
            self._text_label = AppKit.NSTextField.alloc().initWithFrame_(
                make_rect(14, self._CARD_H - text_h - 10, self._CARD_W - 28, text_h)
            )
            self._text_label.setStringValue_("")
            self._text_label.setEditable_(False)
            self._text_label.setBezeled_(False)
            self._text_label.setDrawsBackground_(False)
            self._text_label.setFont_(AppKit.NSFont.systemFontOfSize_(13))
            self._text_label.setTextColor_(AppKit.NSColor.labelColor())
            self._text_label.cell().setWraps_(True)
            self._text_label.cell().setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
            self.addSubview_(self._text_label)

            # Row de boutons en bas.
            btn_h = 32
            btn_y = 12
            yes_w = 130
            no_w = 210
            gap = 8
            total_w = yes_w + gap + no_w
            start_x = (self._CARD_W - total_w) / 2

            self._yes_btn = _make_primary_button(
                make_rect(start_x, btn_y, yes_w, btn_h),
                "Oui, produire",
                self,
                "yesClicked:",
            )
            self.addSubview_(self._yes_btn)

            self._no_btn = _make_secondary_button(
                make_rect(start_x + yes_w + gap, btn_y, no_w, btn_h),
                "Non, répondre directement",
                self,
                "noClicked:",
            )
            self.addSubview_(self._no_btn)
        return self

    @objc.python_method  # type: ignore[untyped-decorator]
    def configure(self, question: str, yes_cb: Any, no_cb: Any,
                  yes_label: str = "Oui, produire",
                  no_label: str = "Non, répondre directement") -> None:
        """Met à jour le texte, les labels et les callbacks."""
        self._text_label.setStringValue_(question)
        self._yes_block = yes_cb
        self._no_block = no_cb
        # Re-styler les labels des boutons (peuvent changer entre proposition et
        # suggested_replies génériques).
        for btn, label, color in (
            (self._yes_btn, yes_label, AppKit.NSColor.whiteColor()),
            (self._no_btn, no_label, AppKit.NSColor.labelColor()),
        ):
            attr = AppKit.NSAttributedString.alloc().initWithString_attributes_(
                label,
                {
                    AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_weight_(
                        12, AppKit.NSFontWeightMedium
                    ),
                    AppKit.NSForegroundColorAttributeName: color,
                },
            )
            btn.setAttributedTitle_(attr)

    @objc.IBAction  # type: ignore[untyped-decorator]
    def yesClicked_(self, sender: Any) -> None:
        cb = self._yes_block
        self._yes_block = None
        self._no_block = None
        if cb is not None:
            cb()

    @objc.IBAction  # type: ignore[untyped-decorator]
    def noClicked_(self, sender: Any) -> None:
        cb = self._no_block
        self._yes_block = None
        self._no_block = None
        if cb is not None:
            cb()

    def isOpaque(self) -> bool:
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
        # Allow dragging from any non-control background area
        self.setMovableByWindowBackground_(True)

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
        # Live streaming (Ollama tokens temps réel) : _streaming_full_text grossit
        # dynamiquement, le timer continue de révéler même quand remaining=0 tant que
        # _streaming_live_done est False. Le PipelineResponse final bascule le flag.
        self._streaming_live: bool = False
        self._streaming_live_done: bool = False

        # Scroll auto-follow gating — si l'utilisateur remonte dans le chat pendant
        # un streaming, on cesse de forcer scrollRangeToVisible à chaque token. Les
        # flags sont mis à jour par scrollBoundsDidChange_ (observer NSView bounds).
        self._scroll_view: Optional[Any] = None
        self._is_user_at_bottom: bool = True
        self._unread_token_count: int = 0
        self._scroll_to_bottom_btn: Optional[Any] = None

        # Drop state — file or folder attached to next query
        self._current_document: Optional[str] = None
        self._current_dossier_path: Optional[str] = None

        # Méta de la dernière PipelineResponse (produces_document, document_path,
        # suggested_replies, document_kind). Peuplé par _process_query avant le
        # streaming, consulté par _on_streaming_complete pour décider quoi afficher.
        self._last_response_meta: Optional[Dict[str, Any]] = None
        self._last_query: str = ""

        # Replace default content view with drop-aware version
        _drop = DropContentView.alloc().initWithFrame_(self.contentView().frame())
        _drop._hud_ref = self
        self.setContentView_(_drop)

        self._setup_ui()
        self._setup_space_observer()
        self._setup_scroll_observer()
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
        # NSVisualEffectMaterialHUDWindow (22) — adapts to light/dark, rendu HUD
        # Fallback sur Sidebar (7) si matériau HUD non disponible
        try:
            vfx.setMaterial_(22)  # NSVisualEffectMaterialHUDWindow
        except Exception:
            vfx.setMaterial_(7)   # NSVisualEffectMaterialSidebar
        vfx.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        vfx.setState_(AppKit.NSVisualEffectStateActive)
        vfx.setWantsLayer_(True)
        vfx.layer().setCornerRadius_(CORNER_R)
        vfx.layer().setBorderWidth_(0.5)
        vfx.layer().setBorderColor_(ns_white(1.0, 0.08).CGColor())
        content.addSubview_(vfx)

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
            make_rect(ind_x + ind_w + 6, header_center_y, 120, 20)
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
        self._latency_label.setTextColor_(_adaptive_tertiary())
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
        self._text_view.setTextColor_(_adaptive_text())  # adapte light/dark
        self._text_view.setFont_(AppKit.NSFont.systemFontOfSize_(12.5))
        self._text_view.textContainer().setLineFragmentPadding_(6)
        self._text_view.setTextContainerInset_(AppKit.NSMakeSize(4, 8))
        self._text_view.setLinkTextAttributes_({
            AppKit.NSForegroundColorAttributeName: _accent(),
            AppKit.NSUnderlineStyleAttributeName: 1,
        })
        self._text_view.setDelegate_(self)

        scroll = AppKit.NSScrollView.alloc().initWithFrame_(
            make_rect(PADDING, _TEXT_Y, _TEXT_W, _TEXT_H_ACTIVE)
        )
        scroll.setDocumentView_(self._text_view)
        scroll.setHasVerticalScroller_(True)
        scroll.setBackgroundColor_(AppKit.NSColor.clearColor())
        scroll.setDrawsBackground_(False)
        scroll.verticalScroller().setAlphaValue_(0.15)
        content.addSubview_(scroll)
        self._scroll_view = scroll

        # ══ PIPELINE STAGES ZONE (« Lucie réfléchit ») ═══════════════════════
        # Zone au-dessus du texte qui affiche les étapes en temps réel. Cachée
        # par défaut, montrée au premier event "started", fade-out à la fin.
        self._stages_view = PipelineStagesView.alloc().initWithFrame_(
            make_rect(PADDING, _STAGES_Y, _TEXT_W, _STAGES_H)
        )
        self._stages_view.setAlphaValue_(0.0)
        self._stages_view.setHidden_(True)
        content.addSubview_(self._stages_view)

        # Bouton « Ré-essayer » affiché sous la zone d'étapes en cas d'erreur.
        retry_w = 110.0
        self._retry_btn = AppKit.NSButton.alloc().initWithFrame_(
            make_rect(WINDOW_W - PADDING - retry_w, _STAGES_Y - _RETRY_H - 2,
                      retry_w, _RETRY_H)
        )
        self._retry_btn.setTitle_("↻  Ré-essayer")
        self._retry_btn.setBezelStyle_(AppKit.NSBezelStyleInline)
        self._retry_btn.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        self._retry_btn.setTarget_(self)
        self._retry_btn.setAction_("retryLastQuery:")
        self._retry_btn.setHidden_(True)
        content.addSubview_(self._retry_btn)

        # Separator: text area / input
        sep3 = AppKit.NSBox.alloc().initWithFrame_(
            make_rect(0, _INPUT_TOP + 6, WINDOW_W, 1)
        )
        sep3.setBoxType_(AppKit.NSBoxSeparator)
        sep3.setAlphaValue_(0.08)
        content.addSubview_(sep3)

        # ══ INPUT ROW ════════════════════════════════════════════════════════
        folder_btn_w = 32
        input_w = WINDOW_W - PADDING * 2 - folder_btn_w - 6  # 6 = gap

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

        folder_x = PADDING + input_w + 6
        self._folder_btn = AppKit.NSButton.alloc().initWithFrame_(
            make_rect(folder_x, _INPUT_Y, folder_btn_w, INPUT_H)
        )
        try:
            folder_img = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "folder", "Ouvrir un document"
            )
            self._folder_btn.setImage_(folder_img)
            self._folder_btn.setImageScaling_(AppKit.NSImageScaleProportionallyDown)
        except Exception:
            self._folder_btn.setTitle_("📁")
        self._folder_btn.setBordered_(False)
        self._folder_btn.setToolTip_("Déposer ou choisir un document")
        self._folder_btn.setTarget_(self)
        self._folder_btn.setAction_("openFilePicker:")
        content.addSubview_(self._folder_btn)

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
        self._status_text.setTextColor_(_adaptive_secondary())
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
        # setHidden_ excludes from hitTest — setAlphaValue_(0) alone does not
        self._drop_highlight.setHidden_(True)
        content.addSubview_(self._drop_highlight)

        # ══ OUTPUT DRAG CARD (visible quand Lucie a produit un résultat) ═════
        # Nouvelles dimensions : 380×72, placée en overlay au-dessus de l'input.
        card_x = (WINDOW_W - DraggableFileCard._CARD_W) / 2
        self._output_card = DraggableFileCard.alloc().initWithFrame_(
            make_rect(
                card_x,
                _INPUT_TOP + 6,
                DraggableFileCard._CARD_W,
                DraggableFileCard._CARD_H,
            )
        )
        self._output_card._hud_ref = self  # pour notifications & NSSavePanel callback
        self._output_card.setHidden_(True)
        self._output_card.setAlphaValue_(0.0)
        content.addSubview_(self._output_card)

        # ══ PROPOSAL CARD (visible quand Lucie propose une production) ═══════
        proposal_x = PADDING
        self._proposal_card = ProposalCardView.alloc().initWithFrame_(
            make_rect(
                proposal_x,
                _INPUT_TOP + 6,
                ProposalCardView._CARD_W,
                ProposalCardView._CARD_H,
            )
        )
        self._proposal_card.setHidden_(True)
        self._proposal_card.setAlphaValue_(0.0)
        content.addSubview_(self._proposal_card)

        # ══ PROGRESS LINE (top edge du HUD) ══════════════════════════════════
        self._progress_line = ProgressLineView.alloc().initWithFrame_(
            make_rect(0, WINDOW_H - ProgressLineView._LINE_H, WINDOW_W, ProgressLineView._LINE_H)
        )
        content.addSubview_(self._progress_line)

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

    # ── Scroll auto-follow gating ─────────────────────────────────────────────

    @objc.python_method  # type: ignore[untyped-decorator]
    def _setup_scroll_observer(self) -> None:
        """Observe bounds du clipView de la scrollView chat pour détecter si
        l'utilisateur a remonté. `setPostsBoundsChangedNotifications_` doit être
        True sinon NSNotificationCenter ne reçoit rien."""
        if not self._scroll_view:
            return
        clip = self._scroll_view.contentView()
        clip.setPostsBoundsChangedNotifications_(True)
        nc = Foundation.NSNotificationCenter.defaultCenter()
        nc.addObserver_selector_name_object_(
            self,
            "scrollBoundsDidChange:",
            AppKit.NSViewBoundsDidChangeNotification,
            clip,
        )

    def scrollBoundsDidChange_(self, notification: Any) -> None:
        """Recalcule `_is_user_at_bottom` depuis documentVisibleRect.
        Idempotent : ne distingue pas scroll programmatique vs user — si un scroll
        programmatique nous met en bas, le flag repasse proprement à True."""
        now_at_bottom = self._is_at_bottom_now()
        if now_at_bottom and not self._is_user_at_bottom:
            # Transition False → True : reset compteur + hide bouton
            self._unread_token_count = 0
        self._is_user_at_bottom = now_at_bottom
        self._update_scroll_button_visibility()

    @objc.python_method  # type: ignore[untyped-decorator]
    def _is_at_bottom_now(self) -> bool:
        """True si la scrollview est à moins de 50 px du bas (ou vide / non init)."""
        sv = self._scroll_view
        if not sv:
            return True
        doc = sv.documentView()
        if not doc:
            return True
        rect = sv.documentVisibleRect()
        doc_h = doc.frame().size.height
        visible_bottom = rect.origin.y + rect.size.height
        return (doc_h - visible_bottom) <= 50.0

    @objc.python_method  # type: ignore[untyped-decorator]
    def _update_scroll_button_visibility(self) -> None:
        """Show le bouton ↓ si l'user a scrollé up ET au moins un token a été
        ignoré depuis. No-op si le bouton n'existe pas encore (commit 1)."""
        btn = self._scroll_to_bottom_btn
        if btn is None:
            return
        should_show = (not self._is_user_at_bottom) and self._unread_token_count > 0
        btn.setHidden_(not should_show)

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

        self._submit_query(query, display_query=query)

    @objc.python_method  # type: ignore[untyped-decorator]
    def _submit_query(self, query: str, display_query: Optional[str] = None) -> None:
        """Envoie une query au pipeline (thread worker).

        `query` peut contenir un marqueur de décision interne (`__decision__:…`)
        transmis au pipeline sans être affiché. `display_query` est la version
        visible par l'utilisateur (par défaut identique).
        """
        from lucie_v1_standalone.pipeline import _DECISION_MARKER  # lazy import
        self._is_processing = True
        self._processing_start_time = float(time.time())
        self._last_query = (
            query.split("|original=", 1)[1]
            if query.startswith(_DECISION_MARKER) and "|original=" in query
            else query
        )
        if display_query:
            self.append_message_safe("Toi", display_query, user=True)

        self._hide_output_card()
        self._hide_proposal_card()
        self.set_state(LucieState.THINKING)

        threading.Thread(target=self._process_query, args=(query,), daemon=True).start()

    @objc.python_method  # type: ignore[untyped-decorator]
    def _send_decision_to_pipeline(self, value: str, original_query: str) -> None:
        """Relance le pipeline avec une décision utilisateur (bouton Oui/Non cliqué).

        Affiche un message utilisateur court (« Oui » / « Non ») pour garder
        une trace conversationnelle lisible, puis transmet `__decision__:<value>|
        original=<query>` au pipeline.
        """
        if self._is_processing:
            return
        from lucie_v1_standalone.pipeline import _DECISION_MARKER  # lazy import
        user_echo = {
            "yes": "Oui",
            "yes_produce": "Oui, produire",
            "no": "Non",
            "no_text": "Non, répondre directement",
        }.get(value, value)
        internal_query = f"{_DECISION_MARKER}{value}|original={original_query}"
        self._submit_query(internal_query, display_query=user_echo)

    @objc.IBAction  # type: ignore[untyped-decorator]
    def openFilePicker_(self, sender: Any) -> None:
        panel = AppKit.NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(False)
        panel.setPrompt_("Ouvrir")
        panel.setMessage_("Choisissez un document ou un dossier à analyser")
        try:
            panel.setAllowedFileTypes_(["pdf", "docx", "txt", "md"])
        except Exception:
            pass
        if panel.runModal() == AppKit.NSModalResponseOK:
            url = panel.URL()
            if url and url.isFileURL():
                self.handle_dropped_path(str(url.path()))

    # ── Drop handling ─────────────────────────────────────────────────────────

    @objc.python_method  # type: ignore[untyped-decorator]
    def handle_dropped_path(self, path: str) -> None:
        """Called (on main thread) when a file or folder is dropped onto the HUD."""
        self._play_sound("Pop")
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
            # Immediate feedback — extraction runs in background to avoid UI freeze
            self.append_message_safe(
                "Lucie",
                f"📄 Lecture de **{name}**…",
                False,
            )

            def _extract() -> None:
                text = self._read_file_text(path)
                if text:
                    self._current_document = text
                    self._current_dossier_path = None
                    size_kb = os.path.getsize(path) // 1024
                    size_str = f"{size_kb} Ko" if size_kb < 1024 else f"{size_kb // 1024} Mo"
                    AppHelper.callAfter(
                        self.append_message_safe,
                        "Lucie",
                        f"✅ **{name}** prêt ({size_str}, {len(text)} car.) — posez votre question.",
                        False,
                    )
                    AppHelper.callAfter(
                        self._input.setPlaceholderString_,
                        f"Question sur {name}…",
                    )
                else:
                    AppHelper.callAfter(
                        self.append_message_safe,
                        "Lucie",
                        f"⚠️ Impossible de lire **{name}**. Formats supportés : PDF, DOCX, TXT, MD.",
                        False,
                    )

            threading.Thread(target=_extract, daemon=True).start()

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

            # Meta accumulées pour _on_streaming_complete (visibilité carte / boutons).
            meta: Dict[str, Any] = {}

            # ── Mode dossier : court-circuit du pipeline standard ────────────
            if dossier_path:
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
                response_text = _da.format_report(report)

            else:
                # ── Pipeline standard : streaming tokens si activé ──────────
                from lucie_v1_standalone import pipeline as _lv1

                # Streaming live actif dès que LUCIE_STREAM=1 (défaut). En Level
                # 3 avec document, pas de tokens intermédiaires mais la zone
                # d'étapes affiche bien Lecteur → Retriever → Rédacteur → Vérif.
                use_live_stream = _lv1.streaming_enabled()

                if use_live_stream:
                    self._run_live_streaming_pipeline(query, _lv1, document_text=document)
                    return

                response = _asyncio.run(
                    _lv1.run(
                        query,
                        document_text=document,
                        force=False,
                        verbose=False,
                    )
                )
                response_text = str(response) if response else ""
                meta = {
                    "produces_document": getattr(response, "produces_document", False),
                    "document_kind": getattr(response, "document_kind", None),
                    "document_path": getattr(response, "document_path", None),
                    "suggested_replies": getattr(response, "suggested_replies", []) or [],
                }

            if not response_text or not response_text.strip():
                response_text = "(Aucune réponse générée)"

            # Reset placeholder after successful response
            AppHelper.callAfter(
                self._input.setPlaceholderString_, "Commande ou question…"
            )
            # Stocker les meta AVANT de démarrer le streaming : _on_streaming_complete
            # les consultera à la fin.
            self._last_response_meta = meta
            AppHelper.callAfter(self._start_streaming, "Lucie", response_text, False)

        except Exception as e:
            logger.error(f"Erreur _process_query: {e}", exc_info=True)
            AppHelper.callAfter(self._on_response_error, f"Erreur : {e}")

    @objc.python_method  # type: ignore[untyped-decorator]
    def _run_live_streaming_pipeline(
        self, query: str, lv1: Any, document_text: Optional[str] = None
    ) -> None:
        """Exécute pipeline.run_stream et pousse les chunks au HUD en temps réel.

        Appelé depuis _process_query (thread de fond). Utilise AppHelper.callAfter
        pour toutes les mises à jour UI (qui doivent rester sur main thread).
        """
        import asyncio as _asyncio
        from lucie_v1_standalone.perf.events import PipelineEvent
        from lucie_v1_standalone.pipeline import PipelineResponse

        meta: Dict[str, Any] = {}
        got_chunks = False

        # Contexte pour les libellés utilisateur (IP-safe) : document chargé ?
        # action/courrier attendu ? Le stage label est calculé à chaque event.
        self._stream_has_document = document_text is not None
        self._stream_produces_document = False
        self._stream_mode = None

        # Reset zone d'étapes avant le run (main thread).
        AppHelper.callAfter(self._reset_pipeline_stages)

        async def _consume() -> None:
            nonlocal meta, got_chunks
            AppHelper.callAfter(self._begin_live_stream, "Lucie")

            async for evt in lv1.run_stream(query, document_text=document_text, force=False):
                if isinstance(evt, str):
                    if evt:
                        got_chunks = True
                        AppHelper.callAfter(self._feed_stream_chunk, evt)
                elif isinstance(evt, PipelineEvent):
                    AppHelper.callAfter(self._on_pipeline_event, evt)
                elif isinstance(evt, PipelineResponse):
                    meta = {
                        "produces_document": getattr(evt, "produces_document", False),
                        "document_kind": getattr(evt, "document_kind", None),
                        "document_path": getattr(evt, "document_path", None),
                        "suggested_replies": getattr(evt, "suggested_replies", []) or [],
                    }
                    # Path SMALL_TALK / blocage : pas de chunks précédents,
                    # on affiche la réponse complète en une fois.
                    if not got_chunks:
                        text = str(evt) if evt else ""
                        if text:
                            AppHelper.callAfter(self._feed_stream_chunk, text)

        try:
            _asyncio.run(_consume())
        except Exception as e:
            logger.error(f"Erreur streaming live : {e}", exc_info=True)
            AppHelper.callAfter(self._on_response_error, f"Erreur : {e}")
            return

        if not got_chunks and not meta:
            AppHelper.callAfter(self._feed_stream_chunk, "(Aucune réponse générée)")

        AppHelper.callAfter(
            self._input.setPlaceholderString_, "Commande ou question…"
        )
        self._last_response_meta = meta
        AppHelper.callAfter(self._mark_stream_done)
        AppHelper.callAfter(self._finalize_pipeline_stages)

    # ── Streaming (word-chunk mode) ───────────────────────────────────────────

    def _start_streaming(self, sender: str, full_text: Any, user: bool = False) -> None:
        self.set_state(LucieState.WRITING)
        if self._streaming_timer is not None:
            self._streaming_timer.invalidate()
            self._streaming_timer = None

        self._streaming_sender = sender
        self._streaming_full_text = str(full_text) if full_text else ""
        self._streaming_text = ""
        self._streaming_index = 0
        self._streaming_live = False
        self._streaming_live_done = False

        storage = self._text_view.textStorage()
        start_pos = len(storage.string())
        self.append_message_safe(sender, "", user)
        end_pos = len(storage.string())
        self._streaming_range = (start_pos, end_pos)

        self._streaming_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            _STREAM_INTERVAL, self, "streamingTimerFired:", None, True
        )

    # ── Live streaming (Ollama tokens temps réel) ───────────────────────────

    @objc.python_method  # type: ignore[untyped-decorator]
    def _begin_live_stream(self, sender: str) -> None:
        """Prépare l'affichage avant l'arrivée des premiers tokens (main thread)."""
        self.set_state(LucieState.WRITING)
        if self._streaming_timer is not None:
            self._streaming_timer.invalidate()
            self._streaming_timer = None

        self._streaming_sender = sender
        self._streaming_full_text = ""
        self._streaming_text = ""
        self._streaming_index = 0
        self._streaming_live = True
        self._streaming_live_done = False

        storage = self._text_view.textStorage()
        start_pos = len(storage.string())
        self.append_message_safe(sender, "", False)
        end_pos = len(storage.string())
        self._streaming_range = (start_pos, end_pos)

        self._streaming_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            _STREAM_INTERVAL, self, "streamingTimerFired:", None, True
        )

    @objc.python_method  # type: ignore[untyped-decorator]
    def _feed_stream_chunk(self, chunk: str) -> None:
        """Alimente le buffer avec un nouveau chunk de tokens (main thread)."""
        if not chunk:
            return
        # Premier token → Rédacteur passe à ✓ (Level 2 n'émet pas completed).
        if not self._streaming_full_text:
            self._mark_redacteur_if_started()
        self._streaming_full_text += chunk
        # Le timer révèle à sa cadence depuis _streaming_full_text. Si jamais
        # le timer a été coupé (dans de rares transitions), on le relance.
        if self._streaming_timer is None and self._streaming_live:
            self._streaming_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                _STREAM_INTERVAL, self, "streamingTimerFired:", None, True
            )

    @objc.python_method  # type: ignore[untyped-decorator]
    def _mark_stream_done(self) -> None:
        """Signale la fin du flux — le timer terminera dès qu'il rattrape le buffer."""
        self._streaming_live_done = True

    @objc.IBAction  # type: ignore[untyped-decorator]
    def streamingTimerFired_(self, timer: Any) -> None:
        remaining = len(self._streaming_full_text) - self._streaming_index
        # En mode live, on attend que la source ait signalé la fin avant de terminer.
        # Sinon la première pause (chunks pas encore arrivés) couperait l'affichage.
        if remaining <= 0 and (not self._streaming_live or self._streaming_live_done):
            timer.invalidate()
            self._streaming_timer = None
            self._is_processing = False
            latency = time.time() - self._processing_start_time
            self._latency_label.setStringValue_(f"{latency:.2f}s")
            self._is_dragging = False
            self.set_state(LucieState.DONE)  # Hero sound + green + "Terminé"
            # Décision d'affichage post-streaming : ProposalCard / DraggableFileCard
            # / boutons Oui-Non / rien, selon les meta du PipelineResponse.
            self._on_streaming_complete()
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
            AppKit.NSForegroundColorAttributeName: _adaptive_text(),
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
        if self._is_user_at_bottom:
            self._text_view.scrollRangeToVisible_(Foundation.NSMakeRange(total_len, 0))
        else:
            self._unread_token_count += 1
            self._update_scroll_button_visibility()

    def _on_response_error(self, error_text: str) -> None:
        self.append_message_safe("Lucie", error_text, False)
        self._is_processing = False
        self._is_dragging = False
        self.set_state(LucieState.ERROR)  # Basso sound + red + "Erreur"
        # Zone d'étapes : si une ligne est en erreur, on garde visible + bouton
        # Ré-essayer ; sinon on fade-out proprement.
        if hasattr(self, "_stages_view") and not self._stages_view.isHidden():
            if self._stages_view.any_error():
                if hasattr(self, "_retry_btn"):
                    self._retry_btn.setHidden_(False)
            else:
                self._finalize_pipeline_stages()

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
            AppKit.NSForegroundColorAttributeName: _adaptive_text(),
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
        if self._is_user_at_bottom:
            self._text_view.scrollRangeToVisible_(Foundation.NSMakeRange(end, 0))
        else:
            self._unread_token_count += 1
            self._update_scroll_button_visibility()
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
            if self._is_user_at_bottom:
                self._text_view.scrollRangeToVisible_(Foundation.NSMakeRange(end, 0))
            else:
                self._unread_token_count += 1
                self._update_scroll_button_visibility()
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

    # ── State machine ─────────────────────────────────────────────────────────

    @objc.python_method  # type: ignore[untyped-decorator]
    def set_state(self, state: str) -> None:
        """Transition vers un nouvel état — met à jour couleur, texte, sons, indicateur."""
        if not hasattr(self, "_lucie_state"):
            self._lucie_state = LucieState.IDLE
        if self._lucie_state == state:
            return
        self._lucie_state = state

        cfg = _STATE_CONFIG.get(state, _STATE_CONFIG[LucieState.IDLE])
        rgba, status_text, sound = cfg
        color = ns_color(*rgba)

        # Dot + status text
        self._status.setTextColor_(color)
        self._status_text.setStringValue_(status_text)

        # Thinking label + indicator
        active_states = {LucieState.THINKING, LucieState.SEARCHING,
                         LucieState.WRITING, LucieState.EXECUTING}
        if state in active_states:
            self._thinking_indicator.startAnimating()
            # Cross-fade label text
            AppKit.NSAnimationContext.beginGrouping()
            AppKit.NSAnimationContext.currentContext().setDuration_(0.12)
            self._thinking_label.animator().setAlphaValue_(0.0)
            AppKit.NSAnimationContext.endGrouping()
            self._thinking_label.setStringValue_(status_text)
            AppKit.NSAnimationContext.beginGrouping()
            AppKit.NSAnimationContext.currentContext().setDuration_(0.18)
            self._thinking_label.animator().setAlphaValue_(1.0)
            AppKit.NSAnimationContext.endGrouping()
        else:
            self._thinking_indicator.stopAnimating()
            AppKit.NSAnimationContext.beginGrouping()
            AppKit.NSAnimationContext.currentContext().setDuration_(0.25)
            self._thinking_label.animator().setAlphaValue_(0.0)
            AppKit.NSAnimationContext.endGrouping()

        # Progress line
        if hasattr(self, "_progress_line"):
            if state in active_states:
                self._progress_line.start_pulsing(rgba)
            else:
                self._progress_line.stop_pulsing()

        # Sound feedback
        if sound:
            self._play_sound(sound)

        # Propagate state to menubar icon
        delegate = AppKit.NSApp.delegate()
        menubar = getattr(delegate, "_menubar", None)
        if menubar is not None:
            menubar.set_state(state)

    @objc.python_method  # type: ignore[untyped-decorator]
    def _play_sound(self, name: str) -> None:
        try:
            snd = AppKit.NSSound.soundNamed_(name)
            if snd:
                snd.play()
        except Exception:
            pass

    # ── Output drag card ──────────────────────────────────────────────────────

    @objc.python_method  # type: ignore[untyped-decorator]
    def _save_output_for_drag(self) -> None:
        """Write streaming response to a temp file and surface it as a drag card.

        Called on the main thread after streaming completes, only when the
        response is substantial (> 200 chars). Cleans up previous temp file.
        """
        import uuid
        text = self._streaming_full_text
        if len(text) <= 200:
            return
        temp_dir = str(Foundation.NSTemporaryDirectory())
        fname = f"lucie_{uuid.uuid4().hex[:8]}.md"
        path = os.path.join(temp_dir, fname)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            old = getattr(self, "_last_output_path", None)
            if old and os.path.exists(old):
                try:
                    os.unlink(old)
                except Exception:
                    pass
            self._last_output_path = path
            self._show_output_card(path)
        except Exception as exc:
            logger.debug(f"_save_output_for_drag: {exc}")

    @objc.python_method  # type: ignore[untyped-decorator]
    def _show_output_card(self, path: str) -> None:
        """Fade in the draggable output card for the given temp file."""
        self._output_card.set_filepath(path)
        self._output_card.setHidden_(False)
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.25)
        self._output_card.animator().setAlphaValue_(1.0)
        AppKit.NSAnimationContext.endGrouping()

    @objc.python_method  # type: ignore[untyped-decorator]
    def _hide_output_card(self) -> None:
        """Fade out and hide the drag card (called when a new query starts)."""
        if self._output_card.isHidden():
            return
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.15)
        self._output_card.animator().setAlphaValue_(0.0)
        AppKit.NSAnimationContext.endGrouping()
        AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.2, self, "_hideOutputCardTimer:", None, False
        )

    @objc.IBAction  # type: ignore[untyped-decorator]
    def _hideOutputCardTimer_(self, timer: Any) -> None:
        self._output_card.setHidden_(True)

    # ── Pipeline stages zone (« Lucie réfléchit ») ────────────────────────────

    @objc.python_method  # type: ignore[untyped-decorator]
    def _reset_pipeline_stages(self) -> None:
        """Réinitialise la zone d'étapes au début d'un nouveau run (main thread)."""
        if not hasattr(self, "_stages_view"):
            return
        self._stages_view.reset()
        if hasattr(self, "_retry_btn"):
            self._retry_btn.setHidden_(True)

    @objc.python_method  # type: ignore[untyped-decorator]
    def _on_pipeline_event(self, evt: Any) -> None:
        """Dispatch d'un PipelineEvent depuis la coro `_consume` vers la UI.

        Règles :
        - Cache hit : la zone reste cachée (réponse servie en <5 ms).
        - `started`: montre la zone si cachée, crée la ligne avec label IP-safe.
        - `completed`: passe la ligne à ✓ avec durée.
        - `error`: ✕ + message, affiche le bouton « Ré-essayer ».
        - Rédacteur `completed` n'est jamais émis en Level 2 ; le premier token
          reçu marque implicitement la fin de cette étape (cf.
          `_mark_redacteur_if_started`).
        """
        from lucie_v1_standalone.stage_labels import user_label

        if not hasattr(self, "_stages_view"):
            return

        stage = evt.stage
        status = evt.status

        # Cache hit : court-circuit, on ne montre rien.
        if stage == "cache" and status == "cached":
            self._stages_view.reset()
            return

        # Meta contextuelles (mode, production de document) pour la variante
        # du libellé. Les flags sont seedés par _run_live_streaming_pipeline
        # et peuvent être mis à jour par un PipelineResponse intermédiaire.
        has_document = bool(getattr(self, "_stream_has_document", False))
        produces_document = bool(getattr(self, "_stream_produces_document", False))
        mode = getattr(self, "_stream_mode", None)

        label = user_label(
            stage,
            has_document=has_document,
            produces_document=produces_document,
            mode=mode,
        )

        if status == "started":
            if self._stages_view.isHidden():
                self._stages_view.fade_in()
            self._stages_view.mark_started(stage, label)
        elif status == "completed":
            self._stages_view.mark_completed(stage, float(evt.duration_ms or 0.0))
        elif status == "error":
            if self._stages_view.isHidden():
                self._stages_view.fade_in()
            self._stages_view.mark_error(stage, str(evt.message or ""), label)
            if hasattr(self, "_retry_btn"):
                self._retry_btn.setHidden_(False)
        elif status == "skipped":
            # Ligne grisée, pas de pulse ni de check
            self._stages_view.mark_completed(stage, 0.0)

    @objc.python_method  # type: ignore[untyped-decorator]
    def _mark_redacteur_if_started(self) -> None:
        """Appelé au premier token : passe la ligne Rédacteur à ✓ sans durée.

        Compense l'absence de `redacteur.completed` explicite en Level 2 : on
        considère que l'étape est « terminée » du point de vue utilisateur dès
        que le premier mot apparaît dans la zone texte.
        """
        if not hasattr(self, "_stages_view"):
            return
        rows = getattr(self._stages_view, "_rows", {})
        row = rows.get("redacteur")
        if row is not None and row.get("state") == "started":
            self._stages_view.mark_completed("redacteur", 0.0)

    @objc.python_method  # type: ignore[untyped-decorator]
    def _finalize_pipeline_stages(self) -> None:
        """Fin de run : fade-out 400 ms si succès, zone conservée si erreur."""
        if not hasattr(self, "_stages_view"):
            return
        if self._stages_view.isHidden():
            return
        if self._stages_view.any_error():
            return
        self._stages_view.fade_out(
            0.4,
            on_complete=lambda: self._stages_view.setHidden_(True),
        )

    @objc.IBAction  # type: ignore[untyped-decorator]
    def retryLastQuery_(self, sender: Any) -> None:
        """Relance la dernière query (utilisé par le bouton « Ré-essayer »)."""
        if self._is_processing:
            return
        query = getattr(self, "_last_query", "") or ""
        if not query:
            return
        if hasattr(self, "_retry_btn"):
            self._retry_btn.setHidden_(True)
        self._submit_query(query, display_query=None)

    # ── Decision flow (ProposalCard + suggested_replies) ──────────────────────

    @objc.python_method  # type: ignore[untyped-decorator]
    def _on_streaming_complete(self) -> None:
        """Décide de l'affichage post-streaming selon les meta PipelineResponse.

        Ordre de priorité :
          1. `document_path` présent → carte document pro (après "yes_produce")
          2. `produces_document` True → ProposalCard avec 2 boutons
          3. `suggested_replies` non vides → ProposalCard générique
          4. Sinon → rien (réponse factuelle — plus de .md temporaire auto)
        """
        meta = self._last_response_meta or {}
        original_query = self._last_query

        document_path = meta.get("document_path")
        if document_path and os.path.exists(document_path):
            self._show_output_card(document_path)
            return

        if meta.get("produces_document"):
            question = self._streaming_full_text.strip() or (
                "Voulez-vous que je produise ce document ?"
            )
            self._show_proposal_card(
                question=question,
                yes_cb=lambda: self._send_decision_to_pipeline("yes_produce", original_query),
                no_cb=lambda: self._send_decision_to_pipeline("no_text", original_query),
                yes_label="Oui, produire",
                no_label="Non, répondre directement",
            )
            return

        replies = meta.get("suggested_replies") or []
        if replies and len(replies) >= 2:
            yes, no = replies[0], replies[1]
            question = self._streaming_full_text.strip() or "Voulez-vous ?"
            self._show_proposal_card(
                question=question,
                yes_cb=lambda: self._send_decision_to_pipeline(yes.get("value", "yes"), original_query),
                no_cb=lambda: self._send_decision_to_pipeline(no.get("value", "no"), original_query),
                yes_label=yes.get("label", "Oui"),
                no_label=no.get("label", "Non"),
            )

    @objc.python_method  # type: ignore[untyped-decorator]
    def _show_proposal_card(self, question: str, yes_cb: Any, no_cb: Any,
                            yes_label: str = "Oui, produire",
                            no_label: str = "Non, répondre directement") -> None:
        """Affiche la ProposalCard avec fade-in."""
        self._proposal_card.configure(question, yes_cb, no_cb, yes_label, no_label)
        self._proposal_card.setHidden_(False)
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.22)
        self._proposal_card.animator().setAlphaValue_(1.0)
        AppKit.NSAnimationContext.endGrouping()

    @objc.python_method  # type: ignore[untyped-decorator]
    def _hide_proposal_card(self) -> None:
        """Fade-out et masque la ProposalCard (nouveau tour utilisateur)."""
        if self._proposal_card.isHidden():
            return
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.15)
        self._proposal_card.animator().setAlphaValue_(0.0)
        AppKit.NSAnimationContext.endGrouping()
        AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.2, self, "_hideProposalCardTimer:", None, False
        )

    @objc.IBAction  # type: ignore[untyped-decorator]
    def _hideProposalCardTimer_(self, timer: Any) -> None:
        self._proposal_card.setHidden_(True)

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
        """Spring entrance Spotlight-quality: scale 0.93→1.0 + fade, CASpringAnimation."""
        self.setAlphaValue_(0.0)
        content = self.contentView()
        # Fade in
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.28)
        self.animator().setAlphaValue_(ALPHA)
        AppKit.NSAnimationContext.endGrouping()
        # Spring scale — try CASpringAnimation (macOS 10.11+), fallback to EaseOut
        layer = content.layer()
        try:
            spring = Quartz.CASpringAnimation.animationWithKeyPath_("transform.scale")
            spring.setMass_(1.0)
            spring.setStiffness_(300.0)
            spring.setDamping_(25.0)
            spring.setInitialVelocity_(2.0)
            spring.setFromValue_(0.93)
            spring.setToValue_(1.0)
            spring.setDuration_(max(0.4, spring.settlingDuration()))
            layer.addAnimation_forKey_(spring, "springIn")
        except AttributeError:
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
    def animateOut(self) -> None:
        """Spring exit: scale 1.0→0.95 + fade-out, puis orderOut."""
        content = self.contentView()
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.18)
        self.animator().setAlphaValue_(0.0)
        AppKit.NSAnimationContext.endGrouping()
        layer = content.layer()
        anim = Quartz.CABasicAnimation.animationWithKeyPath_("transform.scale")
        anim.setFromValue_(1.0)
        anim.setToValue_(0.95)
        anim.setDuration_(0.16)
        anim.setTimingFunction_(
            Quartz.CAMediaTimingFunction.functionWithName_(
                Quartz.kCAMediaTimingFunctionEaseIn
            )
        )
        anim.setFillMode_(Quartz.kCAFillModeForwards)
        anim.setRemovedOnCompletion_(False)
        layer.addAnimation_forKey_(anim, "springOut")
        # OrderOut après la durée de l'animation
        AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.20, self, "orderOutAfterAnimation:", None, False
        )

    @objc.IBAction  # type: ignore[untyped-decorator]
    def orderOutAfterAnimation_(self, timer: Any) -> None:
        """Retire la fenêtre après animateOut."""
        self.orderOut_(None)
        # Réinitialiser la scale pour la prochaine apparition
        try:
            self.contentView().layer().removeAnimationForKey_("springOut")
        except Exception:
            pass

    @objc.python_method  # type: ignore[untyped-decorator]
    def _show_drop_highlight(self, visible: bool) -> None:
        """Show/hide blue drop-target border."""
        self._drop_highlight.setHidden_(not visible)
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
        # NSWorkspace.notificationCenter() et NSNotificationCenter.defaultCenter()
        # sont DEUX centres distincts — notre observer bounds est sur le default.
        Foundation.NSNotificationCenter.defaultCenter().removeObserver_(self)
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

            # Raccourci global Cmd+Shift+L — doit rester en vie tant que l'app tourne
            from .hotkey_manager import HotkeyManager
            self._hotkey = HotkeyManager(self.window)

            # Icône menubar persistante — accessible même quand le HUD est caché
            from .menubar_controller import MenuBarController
            self._menubar = MenuBarController.alloc().initWithHUD_(self.window)

            logger.info("HUD prêt (Cmd+Shift+L pour toggle, icône menubar active)")
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
        if hasattr(self, "_hotkey"):
            self._hotkey.stop()
        if hasattr(self, "_menubar"):
            self._menubar.remove()
        # Nettoyer le fichier temp de drag-out si présent
        if hasattr(self, "window"):
            path = getattr(self.window, "_last_output_path", None)
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception:
                    pass


# ─── Entry point ─────────────────────────────────────────────────────────────
def run_hud(engine: Optional[Any] = None) -> None:
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    delegate = AppDelegate.alloc().initWithEngine_(None)
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    run_hud()
