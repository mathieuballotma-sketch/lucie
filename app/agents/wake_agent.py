"""
WakeAgent — Détection wake word + transcription vocale.

Pipeline : OpenWakeWord (hey_lucie) → VAD silence →
           faster-whisper → engine.
100% local, zéro cloud, zéro API externe.
"""

import collections
import os
import tempfile
import threading
import time
import wave
from typing import Any, Callable, List, Optional

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from openwakeword.model import Model as WakeModel

from app.agents.base_agent import BaseAgent
from app.utils.logger import logger

# ── Constantes audio ──────────────────────────────────────
SAMPLE_RATE = 16000
CHUNK_MS = 80
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_MS / 1000)
LISTEN_SECONDS_MAX = 6       # durée max d'écoute commande
SILENCE_THRESHOLD = 0.005     # amplitude RMS seuil silence (fallback)
SILENCE_DURATION = 1.2       # secondes de silence → arrêt
WAKE_THRESHOLD = 0.35         # seuil détection wake word
WAKE_WORD = "hey_lucie"     # modèle OpenWakeWord utilisé
KALMAN_CALIBRATION_FRAMES = 50  # frames pour calibrer le bruit ambiant
KALMAN_SPEECH_FACTOR = 3.0     # seuil = estimation silence × ce facteur


class KalmanVAD:
    """Filtre de Kalman 1D pour VAD adaptative.

    x̂_k = x̂_{k-1} + K × (z_k - x̂_{k-1})
    K = P / (P + R)
    Seuil adaptatif = estimation_silence × KALMAN_SPEECH_FACTOR
    """

    def __init__(self, calibration_frames: int = KALMAN_CALIBRATION_FRAMES):
        self._calibration_frames = calibration_frames
        self._calibration_buffer: List[float] = []
        self._calibrated = False
        # État Kalman
        self._x_hat = 0.0     # estimation lissée du niveau sonore
        self._P = 1.0         # covariance d'estimation
        self._R = 0.001       # variance du bruit (estimée à la calibration)
        self._Q = 0.0001      # bruit de processus
        self._silence_estimate = 0.005  # estimation du silence (défaut = seuil RMS fixe)
        # Détection changement d'environnement
        self._recent_rms: List[float] = []
        self._env_change_counter = 0

    def update(self, rms: float) -> float:
        """Met à jour le filtre et retourne le seuil adaptatif."""
        # Phase calibration
        if not self._calibrated:
            self._calibration_buffer.append(rms)
            if len(self._calibration_buffer) >= self._calibration_frames:
                self._calibrate()
            return self._silence_estimate * KALMAN_SPEECH_FACTOR

        # Mise à jour Kalman
        K = self._P / (self._P + self._R)
        self._x_hat = self._x_hat + K * (rms - self._x_hat)
        self._P = (1.0 - K) * self._P + self._Q

        # Détection changement d'environnement (> 3s de shift)
        self._recent_rms.append(rms)
        if len(self._recent_rms) > 38:  # ~3s à 80ms/chunk
            self._recent_rms = self._recent_rms[-38:]
            recent_mean = sum(self._recent_rms) / len(self._recent_rms)
            if abs(recent_mean - self._silence_estimate) > self._silence_estimate * 2.0:
                self._env_change_counter += 1
                if self._env_change_counter > 38:
                    logger.info("🎙️ VAD Kalman recalibrée (changement environnement)")
                    self._calibration_buffer = list(self._recent_rms)
                    self._calibrate()
                    self._env_change_counter = 0
            else:
                self._env_change_counter = 0

        return self._silence_estimate * KALMAN_SPEECH_FACTOR

    def is_silence(self, rms: float) -> bool:
        """Retourne True si le RMS est sous le seuil adaptatif."""
        threshold = self.update(rms)
        return rms < threshold

    def _calibrate(self) -> None:
        """Calibre le filtre sur les frames collectées."""
        if not self._calibration_buffer:
            return
        arr = self._calibration_buffer
        mean = sum(arr) / len(arr)
        variance = sum((x - mean) ** 2 for x in arr) / len(arr)
        self._R = max(variance, 1e-8)
        self._x_hat = mean
        self._silence_estimate = mean
        self._calibrated = True
        logger.info(
            f"🎙️ VAD Kalman initialisée (seuil adaptatif, "
            f"silence={mean:.6f}, calibration {len(arr)} frames)"
        )


class WakeAgent(BaseAgent):
    """
    Agent de détection vocale continue.
    Écoute en arrière-plan, détecte 'Hey Lucie',
    transcrit la commande, et l'envoie au moteur.

    - Barge-in : coupe Aurélie dès wake word détecté
    - VAD : arrêt dynamique au silence (pas 6s fixe)
    - Pas d'EventBus depuis le thread audio
    """

    def __init__(self, llm_service: Any, bus: Any, config: Any) -> None:
        super().__init__("WakeAgent", llm_service, bus)
        # Callbacks injectés depuis engine.py
        self._engine_callback: Optional[Callable[[str], None]] = None
        self._voice_speak_callback: Optional[Callable[[str], None]] = None
        self._voice_stop_callback: Optional[Callable[[], None]] = None
        self._voice_is_speaking_fn: Optional[Callable[[], bool]] = None
        # État interne
        self._running = False
        self._is_speaking = False  # True quand Aurélie parle
        self._thread: Optional[threading.Thread] = None
        self._wake_model: Optional[WakeModel] = None
        self._whisper: Optional[WhisperModel] = None
        # VAD Kalman adaptative (remplace le seuil RMS fixe)
        self._kalman_vad = KalmanVAD()
        # Config
        self._device_index: int = config.get("mic_device", 1)
        self._enabled: bool = config.get("wake_enabled", True)
        logger.info("🎙️ WakeAgent initialisé")

    # ── Injection callbacks ────────────────────────────────

    def set_engine_callback(
        self, callback: Callable[[str], None]
    ) -> None:
        """Injecte la fonction d'envoi au moteur."""
        self._engine_callback = callback

    def set_voice_speak_callback(
        self, callback: Callable[[str], None]
    ) -> None:
        """Injecte la fonction de synthèse vocale."""
        self._voice_speak_callback = callback

    def set_voice_stop_callback(
        self, callback: Callable[[], None]
    ) -> None:
        """Injecte la fonction d'arrêt vocal (barge-in)."""
        self._voice_stop_callback = callback

    def set_voice_is_speaking_callback(
        self, callback: Callable[[], bool]
    ) -> None:
        """Injecte la fonction de vérification synthèse en cours."""
        self._voice_is_speaking_fn = callback

    # ── Anti-écho : signaux depuis VoiceManager ───────────

    def on_speech_start(self) -> None:
        """Appelé quand Aurélie commence à parler."""
        self._is_speaking = True

    def on_speech_end(self) -> None:
        """Appelé quand Aurélie finit de parler."""
        self._is_speaking = False

    # ── Interface BaseAgent ───────────────────────────────

    def can_handle(self, query: str) -> bool:
        keywords = [
            "wake word", "écoute", "micro",
            "vocal", "activer voix", "désactiver voix",
        ]
        return any(kw in query.lower() for kw in keywords)

    async def handle(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["activ", "démarre", "lance"]):
            self.start()
            return (
                "🎙️ Écoute vocale activée — "
                "dis 'Hey Lucie' pour m'activer"
            )
        if any(w in q for w in ["désactiv", "arrête", "stop"]):
            self.stop()
            return "🎙️ Écoute vocale désactivée"
        status = "actif" if self._running else "inactif"
        return f"🎙️ Wake word : {status}"

    # ── Cycle de vie ──────────────────────────────────────

    def start(self) -> None:
        """Démarre l'écoute en arrière-plan."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name="WakeAgent-listener",
        )
        self._thread.start()
        logger.info("🎙️ WakeAgent démarré — en écoute")

    def stop(self) -> None:
        """Arrête l'écoute."""
        self._running = False
        logger.info("🎙️ WakeAgent arrêté")

    # ── Chargement modèles ────────────────────────────────

    def _load_models(self) -> bool:
        """Charge OpenWakeWord et Whisper au premier démarrage."""
        try:
            if self._wake_model is None:
                logger.info("🎙️ Chargement OpenWakeWord (hey_lucie)...")
                self._wake_model = WakeModel(
                    wakeword_models=[WAKE_WORD],
                    inference_framework="onnx",
                )
                logger.info("🎙️ OpenWakeWord chargé")

            if self._whisper is None:
                logger.info("🎙️ Chargement Whisper tiny...")
                self._whisper = WhisperModel(
                    "base",
                    device="cpu",
                    compute_type="int8",
                )
                logger.info("🎙️ Whisper tiny chargé")

            return True
        except Exception as e:
            logger.error(f"❌ Erreur chargement modèles WakeAgent: {e}")
            return False

    # ── Boucle principale ─────────────────────────────────

    def _listen_loop(self) -> None:
        """Boucle d'écoute continue — détecte le wake word."""
        if not self._load_models():
            self._running = False
            return

        # Buffer circulaire 2s
        buffer: collections.deque[Any] = collections.deque(
            maxlen=int(SAMPLE_RATE * 2 / CHUNK_SAMPLES)
        )

        logger.info(
            f"🎙️ Écoute active (device={self._device_index}, "
            f"threshold={WAKE_THRESHOLD})"
        )

        def audio_callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            if status:
                logger.debug(f"🎙️ Audio status: {status}")
            buffer.append(indata[:, 0].copy())

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK_SAMPLES,
                device=self._device_index,
                callback=audio_callback,
            ):
                while self._running:
                    time.sleep(0.05)

                    if not buffer:
                        continue

                    # Anti-écho : ignorer si Lucie parle
                    if self._is_speaking:
                        continue

                    chunk = buffer[-1]
                    chunk_int16 = (chunk * 32767).astype(np.int16)

                    # Détecter wake word
                    wake_model = self._wake_model
                    if wake_model is None:
                        continue
                    prediction = wake_model.predict(chunk_int16)
                    score = prediction.get(WAKE_WORD, 0.0)

                    if score >= WAKE_THRESHOLD:
                        logger.info(
                            f"🎙️ Wake word détecté! (score={score:.2f})"
                        )
                        buffer.clear()
                        wake_model.reset()
                        self._handle_wake()

        except Exception as e:
            logger.error(f"❌ Erreur boucle écoute: {e}")
            self._running = False

    # ── Gestion après détection ───────────────────────────

    def _handle_wake(self) -> None:
        """
        Après détection wake word :
        1. Barge-in : coupe Aurélie
        2. Feedback "J'écoute"
        3. Enregistrement avec VAD
        4. Transcription Whisper
        5. Envoi au moteur
        """
        # 1. Barge-in : couper Aurélie si elle parle
        if self._voice_stop_callback:
            try:
                self._voice_stop_callback()
            except Exception as _e:
                logger.debug(f"Barge-in voix échoué : {_e}")
        self._is_speaking = False

        # 2. Feedback vocal
        if self._voice_speak_callback:
            try:
                self.on_speech_start()
                self._voice_speak_callback("J'écoute")
            except Exception as _e:
                logger.debug(f"Feedback vocal échoué : {_e}")

        # 3. Attendre fin synthèse Aurélie puis enregistrer
        _waited = 0
        time.sleep(0.2)  # Laisser la synthèse démarrer
        while _waited < 60:
            if self._voice_is_speaking_fn is None:
                break
            if not self._voice_is_speaking_fn():
                break
            time.sleep(0.05)
            _waited += 1
        time.sleep(0.2)  # Marge après fin voix
        self.on_speech_end()
        logger.info("🎙️ Enregistrement commande...")
        audio_data = []
        silence_chunks = 0
        silence_limit = int(
            SILENCE_DURATION * SAMPLE_RATE / CHUNK_SAMPLES
        )
        max_chunks = int(
            LISTEN_SECONDS_MAX * SAMPLE_RATE / CHUNK_SAMPLES
        )

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK_SAMPLES,
                device=self._device_index,
            ) as stream:
                for _ in range(max_chunks):
                    chunk_raw, _ = stream.read(CHUNK_SAMPLES)
                    chunk = chunk_raw[:, 0]
                    audio_data.append(chunk.copy())

                    # Détection silence — VAD Kalman adaptative
                    rms = float(np.sqrt(np.mean(chunk ** 2)))
                    if self._kalman_vad.is_silence(rms):
                        silence_chunks += 1
                        if silence_chunks >= silence_limit:
                            logger.debug(
                                f"🎙️ Silence détecté après "
                                f"{len(audio_data)} chunks"
                            )
                            break
                    else:
                        silence_chunks = 0

        except Exception as e:
            logger.error(f"❌ Erreur enregistrement: {e}")
            return

        if not audio_data:
            logger.warning("🎙️ Aucun audio enregistré")
            return

        # 4. Transcription
        text = self._transcribe(audio_data)
        logger.info(f"🎙️ Transcrit : '{text}'")

        # 5. Envoi au moteur
        # IMPORTANT : pas d'EventBus ici — callback direct uniquement
        if text and self._engine_callback:
            try:
                self._engine_callback(text.lower().replace("ouvres ", "ouvre ").replace("fermes ", "ferme ").replace("lances ", "lance ").replace("crées ", "crée "))
            except Exception as e:
                logger.error(f"❌ Erreur envoi moteur: {e}")
        elif not text:
            logger.warning("🎙️ Transcription vide — commande ignorée")

    def _transcribe(self, audio_data: List[Any]) -> str:
        """Transcrit l'audio via faster-whisper."""
        if not self._whisper:
            return ""

        audio_array = np.concatenate(audio_data)
        tmp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False
            ) as tmp:
                tmp_path = tmp.name

            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                audio_int16 = (audio_array * 32767).astype(np.int16)
                wf.writeframes(audio_int16.tobytes())

            segments, _ = self._whisper.transcribe(
                tmp_path,
                language="fr",
                beam_size=1,
            )
            text = " ".join(s.text for s in segments).strip()
            # Filtre anti-hallucination Whisper
            hallucinations = [
                "au revoir", "merci", "sous-titres", "sous-titrage",
                "fin.", "c'est fin", "bonne journée", "à bientôt",
                "music", "silence", "applaudissements", "inaudible",
            ]
            text_lower = text.lower()
            if any(h in text_lower for h in hallucinations):
                logger.warning(f"🎙️ Hallucination détectée, ignorée : '{text}'") 
                return ""
            if len(text) < 3:
                return ""
            # Nettoyer ponctuation finale
            text = text.strip(".!?,;").strip()
            return text

        except Exception as e:
            logger.error(f"❌ Erreur transcription Whisper: {e}")
            return ""
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception as _e:
                    logger.debug(f"Suppression fichier temp échouée : {_e}")
