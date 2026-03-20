"""
SpeedProfile — Profils de vitesse pour les actions visibles.

Permet de basculer entre mode démo (rapide) et mode prudent (fiable)
sans modifier les agents eux-mêmes.
"""

from dataclasses import dataclass


@dataclass
class SpeedProfile:
    """Profil de vitesse pour les actions visibles."""

    name: str
    move_duration: float        # durée mouvement souris (s)
    type_interval: float        # délai entre frappes (s)
    animation_step_delay: float  # délai animation fenêtres (s)
    sleep_after_activate: float  # délai après activation app (s)
    sleep_after_cmd: float      # délai après commande clavier (s)


SPEED_DEMO = SpeedProfile(
    name="demo",
    move_duration=0.1,           # vs 0.5 par défaut
    type_interval=0.02,          # vs 0.05 par défaut
    animation_step_delay=0.015,  # vs 0.025 par défaut
    sleep_after_activate=0.15,   # vs 0.3-0.5 par défaut
    sleep_after_cmd=0.1,         # vs 0.2-0.5 par défaut
)

SPEED_NORMAL = SpeedProfile(
    name="normal",
    move_duration=0.3,
    type_interval=0.03,
    animation_step_delay=0.02,
    sleep_after_activate=0.2,
    sleep_after_cmd=0.15,
)

SPEED_CAREFUL = SpeedProfile(
    name="careful",
    move_duration=0.5,
    type_interval=0.05,
    animation_step_delay=0.025,
    sleep_after_activate=0.3,
    sleep_after_cmd=0.2,
)

# Profil actif — changeable via config ou au runtime
ACTIVE_PROFILE: SpeedProfile = SPEED_DEMO
