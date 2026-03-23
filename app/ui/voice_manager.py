"""
VoiceManager — Synthèse vocale natif macOS.

Utilise NSSpeechSynthesizer avec voix Thomas FR.
Zéro dépendance externe — 100% natif Apple.
"""

from __future__ import annotations

import re
from typing import Optional

import AppKit

from ..utils.logger import logger


class VoiceManager:
    """Gestionnaire de synthèse vocale natif macOS."""

    VOICES_FR = [
        "com.apple.voice.premium.fr-FR.Aurelie",
        "com.apple.voice.enhanced.fr-FR.Aurelie",
        "com.apple.ttsbundle.Aurelie-premium",
        "com.apple.ttsbundle.Aurelie-compact",
        "com.apple.voice.compact.fr-FR.Thomas",
    ]

    def __init__(self) -> None:
        self._synthesizer: Optional[AppKit.NSSpeechSynthesizer] = None
        self._enabled = True
        self._setup()

    def _setup(self) -> None:
        """Initialise le synthétiseur vocal. Voix FR prioritaire, fallback système."""
        for voice in self.VOICES_FR:
            synth = AppKit.NSSpeechSynthesizer.alloc().initWithVoice_(voice)
            if synth is not None:
                self._synthesizer = synth
                self._synthesizer.setRate_(180)
                self._synthesizer.setVolume_(0.9)
                logger.info(f"🔊 Voix initialisée : {voice.split('.')[-1]}")
                return

        # Fallback voix système
        self._synthesizer = AppKit.NSSpeechSynthesizer.alloc().init()
        logger.warning("🔊 Voix Thomas absente — fallback voix système")

    def speak(self, text: str) -> None:
        """Lit le texte à voix haute. Nettoie le markdown avant lecture."""
        if not self._enabled or not self._synthesizer:
            return
        if not text or not text.strip():
            return

        clean = self._clean_for_speech(text)
        if not clean:
            return

        # Stopper si déjà en train de parler
        if self._synthesizer.isSpeaking():
            self._synthesizer.stopSpeaking()

        self._synthesizer.startSpeakingString_(clean)
        logger.debug(f"🔊 Lecture : {clean[:50]}...")

    def is_speaking(self) -> bool:
        """Retourne True si la voix parle encore."""
        if self._synthesizer:
            return bool(self._synthesizer.isSpeaking())
        return False

    def stop(self) -> None:
        """Arrête la lecture en cours."""
        if self._synthesizer and self._synthesizer.isSpeaking():
            self._synthesizer.stopSpeaking()

    def toggle(self) -> bool:
        """Active/désactive la voix. Retourne le nouvel état."""
        self._enabled = not self._enabled
        if not self._enabled:
            self.stop()
        status = "activée" if self._enabled else "désactivée"
        logger.info(f"🔊 Voix {status}")
        return self._enabled

    def set_rate(self, rate: int) -> None:
        """Vitesse de lecture. 100=lent, 180=normal, 250=rapide."""
        if self._synthesizer:
            self._synthesizer.setRate_(rate)

    def _clean_for_speech(self, text: str) -> str:
        """Nettoie le texte pour la lecture vocale. Supprime markdown, URLs, emojis."""
        clean = text
        # Supprimer blocs code
        clean = re.sub(r'```[\s\S]*?```', 'bloc de code', clean)
        # Supprimer code inline
        clean = re.sub(r'`[^`]+`', '', clean)
        # Supprimer URLs
        clean = re.sub(r'http[s]?://\S+', 'lien', clean)
        # Supprimer markdown gras/italique
        clean = re.sub(r'\*+([^*]+)\*+', r'\1', clean)
        clean = re.sub(r'_+([^_]+)_+', r'\1', clean)
        # Supprimer titres markdown
        clean = re.sub(r'^#+\s+', '', clean, flags=re.MULTILINE)
        # Supprimer emojis courants
        clean = re.sub(r'[✅❌⚠️🔊🧠⚛️🎯🚀💾📄🔮👁️📋🐛⏱️🔍🔗📊]', '', clean)
        # Nettoyer espaces multiples
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()[:500]
