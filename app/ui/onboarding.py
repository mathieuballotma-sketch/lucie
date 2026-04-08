# app/ui/onboarding.py
"""
Expérience premier lancement de Lucide.

Phase 1 — La chenille : petite fenêtre grise, barre de progression
Phase 2 — La révélation : expansion vers le HUD en verre
Phase 3 — Le prénom : "Comment tu t'appelles ?"
Phase 4 — Le guide : 3 démos interactives
"""

import threading
import time
from typing import Any, Callable, List, Optional

import AppKit
import objc
import Quartz
from PyObjCTools import AppHelper

from ..services.onboarding import run_onboarding, save_profile, load_profile

# Dimensions
COCOON_W = 300
COCOON_H = 180
HUD_W = 520
HUD_H = 500
CORNER_R = 24.0


def ns_color(r: float, g: float, b: float, a: float = 1.0) -> Any:
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a)


def ns_white(w: float, a: float = 1.0) -> Any:
    return AppKit.NSColor.colorWithCalibratedWhite_alpha_(w, a)


def make_rect(x: float, y: float, w: float, h: float) -> Any:
    return AppKit.NSMakeRect(x, y, w, h)


def center_rect(w: float, h: float) -> Any:
    """Retourne un rect centré sur l'écran principal."""
    screen = AppKit.NSScreen.mainScreen().frame()
    x = (screen.size.width - w) / 2
    y = (screen.size.height - h) / 2
    return make_rect(x, y, w, h)


# ──────────────────────────────────────────────────────────────────────
# Phase 1 — La chenille
# ──────────────────────────────────────────────────────────────────────

class CocoonWindow(AppKit.NSPanel):  # type: ignore[misc]
    """Petite fenêtre sobre qui s'affiche pendant le chargement."""

    def initWithCallback_(self, on_ready_callback: Any) -> Any:
        rect = center_rect(COCOON_W, COCOON_H)
        style = AppKit.NSWindowStyleMaskBorderless
        self = objc.super(CocoonWindow, self).initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False
        )
        if self is None:
            return None

        self.setFloatingPanel_(True)
        self.setBecomesKeyOnlyIfNeeded_(False)
        self.setHidesOnDeactivate_(False)
        self.setLevel_(Quartz.kCGFloatingWindowLevel + 2)
        self.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )
        self.setOpaque_(False)
        self.setBackgroundColor_(AppKit.NSColor.clearColor())
        self.setAlphaValue_(0.0)  # commence invisible, fade-in dans show()
        self.setHasShadow_(True)

        self._on_ready = on_ready_callback
        self._progress = 0.0
        self._progress_steps: List[str] = [
            "Connexion à Ollama…",
            "Chargement des modèles…",
            "Activation du RAG…",
            "Initialisation des agents…",
            "Préparation de l'interface…",
        ]
        self._current_step = 0
        self._dot_count = 0
        self._engine_ready = False

        self._setup_cocoon_ui()
        return self

    def _setup_cocoon_ui(self) -> None:
        content = self.contentView()
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(16.0)
        content.layer().setMasksToBounds_(True)

        # Fond gris foncé mat — volontairement sobre
        bg = AppKit.NSView.alloc().initWithFrame_(
            make_rect(0, 0, COCOON_W, COCOON_H)
        )
        bg.setWantsLayer_(True)
        bg.layer().setBackgroundColor_(ns_color(0.12, 0.12, 0.13, 0.95).CGColor())
        bg.layer().setCornerRadius_(16.0)
        content.addSubview_(bg)

        # Titre "✦ LUCIDE"
        title = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(0, 100, COCOON_W, 30)
        )
        title.setStringValue_("✦  LUCIDE")
        title.setEditable_(False)
        title.setBezeled_(False)
        title.setDrawsBackground_(False)
        title.setAlignment_(AppKit.NSTextAlignmentCenter)
        title.setFont_(
            AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(
                18, AppKit.NSFontWeightLight
            )
        )
        title.setTextColor_(ns_white(0.55, 0.8))
        content.addSubview_(title)

        # Texte de statut
        self._status_label = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(0, 65, COCOON_W, 18)
        )
        self._status_label.setStringValue_("initialisation…")
        self._status_label.setEditable_(False)
        self._status_label.setBezeled_(False)
        self._status_label.setDrawsBackground_(False)
        self._status_label.setAlignment_(AppKit.NSTextAlignmentCenter)
        self._status_label.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        self._status_label.setTextColor_(ns_white(0.35, 0.7))
        content.addSubview_(self._status_label)

        # Barre de progression — fond
        bar_w = 200
        bar_h = 3
        bar_x = (COCOON_W - bar_w) / 2
        bar_y = 45

        bar_bg = AppKit.NSView.alloc().initWithFrame_(
            make_rect(bar_x, bar_y, bar_w, bar_h)
        )
        bar_bg.setWantsLayer_(True)
        bar_bg.layer().setBackgroundColor_(ns_white(0.2, 0.3).CGColor())
        bar_bg.layer().setCornerRadius_(1.5)
        content.addSubview_(bar_bg)

        # Barre de progression — remplissage
        self._progress_bar = AppKit.NSView.alloc().initWithFrame_(
            make_rect(bar_x, bar_y, 0, bar_h)
        )
        self._progress_bar.setWantsLayer_(True)
        self._progress_bar.layer().setBackgroundColor_(ns_white(0.4, 0.6).CGColor())
        self._progress_bar.layer().setCornerRadius_(1.5)
        content.addSubview_(self._progress_bar)

        self._bar_x = bar_x
        self._bar_y = bar_y
        self._bar_w = bar_w
        self._bar_h = bar_h

    def show(self) -> None:
        """Affiche la fenêtre avec un fondu."""
        self.makeKeyAndOrderFront_(None)
        self.orderFrontRegardless()

        # Petit délai pour que le runloop démarre, puis fade in
        AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.1, self, "fadeInTick:", None, False
        )

    @objc.IBAction  # type: ignore[untyped-decorator]
    def fadeInTick_(self, timer: Any) -> None:
        """Déclenche le fade-in après que le runloop soit actif."""
        self.setAlphaValue_(0.0)
        self.orderFrontRegardless()
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.8)
        self.animator().setAlphaValue_(1.0)
        AppKit.NSAnimationContext.endGrouping()

        # Timer pour animation des points
        self._dot_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.4, self, "dotTick:", None, True
        )

    @objc.IBAction  # type: ignore[untyped-decorator]
    def dotTick_(self, timer: Any) -> None:
        self._dot_count = (self._dot_count + 1) % 4
        dots = "." * self._dot_count
        step_text = self._progress_steps[min(self._current_step, len(self._progress_steps) - 1)]
        base = step_text.rstrip("…").rstrip(".")
        self._status_label.setStringValue_(f"{base}{dots}")

    def set_progress(self, value: float, step: int = -1) -> None:
        """Met à jour la barre (0.0 → 1.0) depuis n'importe quel thread."""
        AppHelper.callAfter(self._update_progress, value, step)

    def _update_progress(self, value: float, step: int) -> None:
        self._progress = min(value, 1.0)
        if step >= 0:
            self._current_step = step

        new_w = self._bar_w * self._progress
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.3)
        self._progress_bar.animator().setFrame_(
            make_rect(self._bar_x, self._bar_y, new_w, self._bar_h)
        )
        # Couleur de la barre qui s'éclaire avec la progression
        brightness = 0.4 + self._progress * 0.4
        self._progress_bar.layer().setBackgroundColor_(
            ns_white(brightness, 0.7).CGColor()
        )
        AppKit.NSAnimationContext.endGrouping()

    def signal_ready(self) -> None:
        """Appelé quand l'engine est prêt — lance Phase 2."""
        self._engine_ready = True
        AppHelper.callAfter(self._complete_loading)

    def _complete_loading(self) -> None:
        # Remplir la barre à 100%
        self._update_progress(1.0, len(self._progress_steps) - 1)

        # Arrêter le timer des points
        if hasattr(self, "_dot_timer"):
            self._dot_timer.invalidate()

        self._status_label.setStringValue_("prêt")
        self._status_label.setTextColor_(ns_white(0.5, 0.8))

        # Pause 0.8s puis lancer Phase 2
        AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.8, self, "startPhase2:", None, False
        )

    @objc.IBAction  # type: ignore[untyped-decorator]
    def startPhase2_(self, timer: Any) -> None:
        """Déclenche la transition Phase 2."""
        if self._on_ready:
            self._on_ready(self)

    @objc.IBAction  # type: ignore[untyped-decorator]
    def crossfadeTick_(self, timer: Any) -> None:
        """Timer callback pour le crossfade cocoon → HUD."""
        if hasattr(self, "_crossfade_fn") and self._crossfade_fn:
            self._crossfade_fn()


# ──────────────────────────────────────────────────────────────────────
# Phase 2 — La révélation (expansion + verre)
# ──────────────────────────────────────────────────────────────────────

def animate_cocoon_to_hud(
    cocoon: CocoonWindow,
    hud_window: Any,
    on_complete: Callable[[], None],
) -> None:
    """
    Anime la transition de la petite fenêtre vers le HUD.
    1. Expand cocoon au format HUD (0.6s)
    2. Crossfade cocoon → HUD (0.5s)
    3. Supprime cocoon
    """
    # Position cible : centrée pour le HUD
    target = center_rect(HUD_W, HUD_H)

    # Préparer le HUD invisible à la même position
    hud_window.setFrame_display_(target, False)
    hud_window.setAlphaValue_(0.0)

    # Étape 1 : expansion du cocoon
    AppKit.NSAnimationContext.beginGrouping()
    ctx = AppKit.NSAnimationContext.currentContext()
    ctx.setDuration_(0.6)
    ctx.setTimingFunction_(
        Quartz.CAMediaTimingFunction.functionWithName_(
            Quartz.kCAMediaTimingFunctionEaseInEaseOut
        )
    )
    cocoon.animator().setFrame_display_(target, True)
    AppKit.NSAnimationContext.endGrouping()

    # Étape 2 : après 0.6s, crossfade
    def _crossfade() -> None:
        hud_window.makeKeyAndOrderFront_(None)
        hud_window.orderFrontRegardless()

        AppKit.NSAnimationContext.beginGrouping()
        ctx2 = AppKit.NSAnimationContext.currentContext()
        ctx2.setDuration_(0.5)
        hud_window.animator().setAlphaValue_(0.78)  # ALPHA du HUD normal
        cocoon.animator().setAlphaValue_(0.0)
        AppKit.NSAnimationContext.endGrouping()

        # Étape 3 : nettoyage après 0.6s
        def _cleanup() -> None:
            cocoon.close()
            on_complete()

        AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.6, hud_window, "onboardCleanup:", None, False
        )
        # Stocker le callback pour le timer
        hud_window._onboard_cleanup = _cleanup

    AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.65, cocoon, "crossfadeTick:", None, False
    )
    cocoon._crossfade_fn = _crossfade


# ──────────────────────────────────────────────────────────────────────
# Phase 3 & 4 — Onboarding interactif dans le HUD
# ──────────────────────────────────────────────────────────────────────

class OnboardingFlow:
    """
    Gère le flux conversationnel d'onboarding dans le HUD existant.
    Injecté dans HUDWindow après la Phase 2.
    """

    STEPS = [
        # (message_lucide, placeholder_input, handler_name)
        ("Bonjour. Comment tu t'appelles ?", "Ton prénom…", "_handle_name"),
        (None, "Ton métier ou ta passion…", "_handle_job"),  # message dynamique
        # Phase 4 — guide interactif
        (None, "Pose ta question ici…", "_handle_demo_question"),
        (None, "Ex: crée un fichier notes.txt sur le bureau", "_handle_demo_file"),
        (None, "Ex: explique la relativité en 3 phrases", "_handle_demo_complex"),
    ]

    def __init__(self, hud_window: Any, engine: Any) -> None:
        self.hud = hud_window
        self.engine = engine
        self.step = 0
        self.user_name = ""
        self.user_job = ""
        self._original_action: Optional[Any] = None

    def start(self) -> None:
        """Démarre le flux d'onboarding."""
        # Remplacer l'action d'envoi du HUD
        self._hijack_input()
        # Afficher le premier message
        self._show_step()

    def _hijack_input(self) -> None:
        """Redirige l'input du HUD vers notre handler."""
        self.hud._onboarding_flow = self
        self.hud._input.setPlaceholderString_(self.STEPS[0][1])

    def _show_step(self) -> None:
        """Affiche le message de l'étape courante."""
        if self.step >= len(self.STEPS):
            self._finish()
            return

        message, placeholder, _ = self.STEPS[self.step]

        if message:
            self.hud.append_message_safe("Lucide", message, False)

        self.hud._input.setPlaceholderString_(placeholder)
        self.hud.makeFirstResponder_(self.hud._input)

    def handle_input(self, text: str) -> None:
        """Appelé quand l'utilisateur envoie un message pendant l'onboarding."""
        if self.step >= len(self.STEPS):
            return

        _, _, handler_name = self.STEPS[self.step]
        handler = getattr(self, handler_name)
        handler(text)

    def _handle_name(self, name: str) -> None:
        """Phase 3 — Reçoit le prénom."""
        self.user_name = name.strip().capitalize()
        self.hud.append_message_safe("Toi", name, True)

        # Créer le modèle personnalisé en arrière-plan
        threading.Thread(
            target=self._create_model_background,
            args=(self.user_name,),
            daemon=True,
        ).start()

        # Message suivant avec prénom
        self.step = 1
        msg = f"Enchanté {self.user_name}. Qu'est-ce que tu fais dans la vie ?"
        self.STEPS[1] = (msg, self.STEPS[1][1], self.STEPS[1][2])
        self._show_step()

    def _create_model_background(self, name: str) -> None:
        """Crée le modèle personnalisé et sauvegarde le profil."""
        try:
            run_onboarding(name)
        except Exception as e:
            print(f"⚠️ Erreur création modèle: {e}")

    def _handle_job(self, job: str) -> None:
        """Phase 3 — Reçoit le métier."""
        self.user_job = job.strip()
        self.hud.append_message_safe("Toi", job, True)

        # Sauvegarder le métier dans le profil
        profile = load_profile()
        profile["job"] = self.user_job
        save_profile(profile)

        # Transition vers Phase 4
        self.step = 2
        msg = (
            f"{self.user_name}, voilà ce que je sais faire.\n"
            f"Essaie de me poser une vraie question."
        )
        self.STEPS[2] = (msg, self.STEPS[2][1], self.STEPS[2][2])
        self._show_step()

    def _handle_demo_question(self, question: str) -> None:
        """Phase 4 — Démo 1 : question libre."""
        self.hud.append_message_safe("Toi", question, True)
        self._process_demo(question, self._after_demo1)

    def _after_demo1(self) -> None:
        self.step = 3
        msg = "Bien. Maintenant, demande-moi de créer un fichier."
        self.STEPS[3] = (msg, self.STEPS[3][1], self.STEPS[3][2])
        AppHelper.callAfter(self._show_step)

    def _handle_demo_file(self, request: str) -> None:
        """Phase 4 — Démo 2 : création de fichier."""
        self.hud.append_message_safe("Toi", request, True)
        self._process_demo(request, self._after_demo2)

    def _after_demo2(self) -> None:
        self.step = 4
        msg = "Dernière chose. Demande-moi quelque chose de complexe."
        self.STEPS[4] = (msg, self.STEPS[4][1], self.STEPS[4][2])
        AppHelper.callAfter(self._show_step)

    def _handle_demo_complex(self, request: str) -> None:
        """Phase 4 — Démo 3 : requête complexe."""
        self.hud.append_message_safe("Toi", request, True)
        self._process_demo(request, self._after_demo3)

    def _after_demo3(self) -> None:
        self.step = len(self.STEPS)  # terminé
        msg = f"Je suis prêt. Qu'est-ce qu'on fait {self.user_name} ?"
        AppHelper.callAfter(self.hud.append_message_safe, "Lucide", msg, False)
        AppHelper.callAfter(self._finish)

    def _process_demo(self, query: str, on_done: Callable[[], None]) -> None:
        """Envoie une requête à l'engine et affiche la réponse."""
        self.hud._set_status("●", ns_color(1.0, 0.6, 0.0), "Réflexion…")
        self.hud._thinking_indicator.startAnimating()
        self.hud._thinking_label.setStringValue_("En cours de réflexion")
        self.hud._thinking_label.setAlphaValue_(1.0)
        self.hud._send_btn.setEnabled_(False)
        self.hud._is_processing = True
        self.hud._processing_start_time = time.time()

        def _run() -> None:
            try:
                response, latency = self.engine.process(query, use_rag=True)
                if not response or not str(response).strip():
                    response = "(Pas de réponse)"
                AppHelper.callAfter(self._show_demo_response, response, on_done)
            except Exception as e:
                AppHelper.callAfter(
                    self._show_demo_response, f"Erreur : {e}", on_done
                )

        threading.Thread(target=_run, daemon=True).start()

    def _show_demo_response(self, response: str, on_done: Callable[[], None]) -> None:
        """Affiche la réponse de la démo et passe à l'étape suivante."""
        self.hud._start_streaming("Lucide", str(response), False)

        # Attendre la fin du streaming puis enchaîner
        self.hud._onboard_next_step = on_done

        self.hud._thinking_indicator.stopAnimating()
        self.hud._thinking_label.setAlphaValue_(0.0)
        latency = time.time() - self.hud._processing_start_time
        self.hud._latency_label.setStringValue_(f"{latency:.2f}s")
        self.hud._set_status("●", ns_color(0.2, 0.9, 0.4), "Prêt")
        self.hud._send_btn.setEnabled_(True)
        self.hud._is_processing = False

    def _finish(self) -> None:
        """Termine l'onboarding — remet le HUD en mode normal."""
        self.hud._onboarding_flow = None
        self.hud._input.setPlaceholderString_("Votre message…")
        self.hud.makeFirstResponder_(self.hud._input)
        print(f"🎉 Onboarding terminé pour {self.user_name}")
