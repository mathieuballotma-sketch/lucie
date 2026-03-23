"""
Gestionnaire d'énergie pour Agent Lucide.
Surveille l'état thermique et la batterie du Mac, et adapte le comportement
de Lucie pour éviter de faire chauffer la machine.

Composants :
  - PowerMode : Enum des modes de fonctionnement
  - ThermalMonitor : Surveillance thermique via NSProcessInfo
  - PowerSourceWatcher : Détection batterie / secteur via pmset
  - EnergyOrchestrator : Orchestrateur central qui combine les deux
"""

import asyncio
import subprocess
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PowerMode — Enum des modes
# ─────────────────────────────────────────────────────────────────────────────
class PowerMode(Enum):
    """Modes de fonctionnement énergétique."""

    PERFORMANCE = "performance"   # Tous les coeurs, tout en RAM
    BALANCED = "balanced"         # Compromis (defaut)
    ECO = "eco"                   # E-cores, mmap FAISS, keep_alive court
    CRITICAL = "critical"         # Minimum vital — thermique critique


# ─────────────────────────────────────────────────────────────────────────────
# ThermalMonitor — Surveillance thermique via PyObjC
# ─────────────────────────────────────────────────────────────────────────────
class ThermalMonitor:
    """Monitore l'etat thermique du Mac via NSProcessInfo."""

    NOMINAL: int = 0
    FAIR: int = 1
    SERIOUS: int = 2
    CRITICAL: int = 3
    STATE_NAMES: Dict[int, str] = {0: "nominal", 1: "fair", 2: "serious", 3: "critical"}

    def __init__(self) -> None:
        self._callbacks: List[Callable[[int], None]] = []
        self._thermal_state: int = self.NOMINAL
        self._nsprocessinfo: Optional[Any] = None
        self._observer: Optional[Any] = None

        try:
            from Foundation import NSProcessInfo
            self._nsprocessinfo = NSProcessInfo.processInfo()
            self._thermal_state = int(self._nsprocessinfo.thermalState())
            self._register_notification()
            logger.info(
                f"ThermalMonitor actif — etat initial: "
                f"{self.STATE_NAMES.get(self._thermal_state, 'unknown')}"
            )
        except ImportError:
            logger.warning("NSProcessInfo indisponible — ThermalMonitor en mode fallback")
        except Exception as e:
            logger.warning(f"ThermalMonitor init error: {e}")

    def _register_notification(self) -> None:
        """Enregistre un observateur pour les changements thermiques."""
        try:
            from Foundation import (
                NSNotificationCenter,
            )
            center = NSNotificationCenter.defaultCenter()
            # NSProcessInfoThermalStateDidChangeNotification
            notification_name = "NSProcessInfoThermalStateDidChangeNotification"
            self._observer = center.addObserverForName_object_queue_usingBlock_(
                notification_name,
                None,
                None,
                lambda notif: self._on_thermal_change(),
            )
        except Exception as e:
            logger.debug(f"Notification thermique non enregistree: {e}")

    def _on_thermal_change(self) -> None:
        """Callback appele par le systeme lors d'un changement thermique."""
        if self._nsprocessinfo is not None:
            new_state = int(self._nsprocessinfo.thermalState())
            if new_state != self._thermal_state:
                old_state = self._thermal_state
                self._thermal_state = new_state
                logger.info(
                    f"Changement thermique: "
                    f"{self.STATE_NAMES.get(old_state, '?')} -> "
                    f"{self.STATE_NAMES.get(new_state, '?')}"
                )
                for cb in self._callbacks:
                    try:
                        cb(new_state)
                    except Exception as e:
                        logger.error(f"Thermal callback error: {e}")

    @property
    def thermal_state(self) -> int:
        """Retourne l'etat thermique actuel (0-3)."""
        if self._nsprocessinfo is not None:
            try:
                self._thermal_state = int(self._nsprocessinfo.thermalState())
            except Exception:
                pass
        return self._thermal_state

    @property
    def thermal_state_name(self) -> str:
        """Retourne le nom de l'etat thermique."""
        return self.STATE_NAMES.get(self.thermal_state, "unknown")

    def on_thermal_change(self, callback: Callable[[int], None]) -> None:
        """Enregistre un callback pour les changements thermiques."""
        self._callbacks.append(callback)

    def is_throttling_recommended(self) -> bool:
        """True si l'etat thermique est >= SERIOUS."""
        return self.thermal_state >= self.SERIOUS

    def cleanup(self) -> None:
        """Retire l'observateur de notifications."""
        if self._observer is not None:
            try:
                from Foundation import NSNotificationCenter
                center = NSNotificationCenter.defaultCenter()
                center.removeObserver_(self._observer)
                self._observer = None
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# PowerSourceWatcher — Detection batterie/secteur
# ─────────────────────────────────────────────────────────────────────────────
def is_on_battery() -> bool:
    """Detecte si le Mac fonctionne sur batterie via pmset."""
    try:
        result = subprocess.run(
            ["pmset", "-g", "batt"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return "'Battery Power'" in result.stdout
    except Exception:
        return False


def get_battery_percentage() -> Optional[int]:
    """Retourne le pourcentage de batterie ou None si non disponible."""
    try:
        result = subprocess.run(
            ["pmset", "-g", "batt"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        for line in result.stdout.split("\n"):
            if "%" in line:
                # Exemple : "-InternalBattery-0 (id=...)   87%; charging; ..."
                parts = line.split("\t")
                for part in parts:
                    if "%" in part:
                        pct_str = part.split("%")[0].strip().split()[-1]
                        return int(pct_str)
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# EnergyOrchestrator — Orchestrateur central
# ─────────────────────────────────────────────────────────────────────────────

# Profils par mode
ENERGY_PROFILES: Dict[PowerMode, Dict[str, Any]] = {
    PowerMode.PERFORMANCE: {
        "ollama_threads": 0,       # auto
        "keep_alive": "5m",
        "faiss_mode": "memory",
        "max_agents": 5,
        "inference_delay": 0.0,
    },
    PowerMode.BALANCED: {
        "ollama_threads": 6,
        "keep_alive": "2m",
        "faiss_mode": "memory",
        "max_agents": 3,
        "inference_delay": 0.0,
    },
    PowerMode.ECO: {
        "ollama_threads": 4,       # E-cores
        "keep_alive": "30s",
        "faiss_mode": "mmap",
        "max_agents": 2,
        "inference_delay": 0.5,
    },
    PowerMode.CRITICAL: {
        "ollama_threads": 2,
        "keep_alive": "0",         # decharger immediatement
        "faiss_mode": "mmap",
        "max_agents": 1,
        "inference_delay": 2.0,
    },
}


class EnergyOrchestrator:
    """Orchestrateur central de gestion d'energie."""

    def __init__(
        self,
        energy_mode: str = "auto",
        low_battery_threshold: int = 20,
        power_check_interval: int = 30,
    ) -> None:
        self._mode: PowerMode = PowerMode.BALANCED
        self._auto: bool = energy_mode == "auto"
        self._forced_mode: Optional[PowerMode] = None
        self._low_battery_threshold = low_battery_threshold
        self._power_check_interval = power_check_interval

        self._thermal_monitor = ThermalMonitor()
        self._thermal_monitor.on_thermal_change(self._on_thermal_change)

        self._mode_change_callbacks: List[Callable[[PowerMode], None]] = []
        self._running = False
        self._task: Optional[asyncio.Task[None]] = None
        self._maintenance_task: Optional[asyncio.Task[None]] = None

        # Appliquer le mode initial si force
        if energy_mode != "auto":
            try:
                self._forced_mode = PowerMode(energy_mode)
                self._mode = self._forced_mode
            except ValueError:
                logger.warning(f"Mode energie inconnu: {energy_mode}, fallback auto")
                self._auto = True

        logger.info(
            f"EnergyOrchestrator initialise — mode: {self._mode.value}, "
            f"auto: {self._auto}"
        )

    @property
    def mode(self) -> PowerMode:
        """Mode energetique actuel."""
        return self._mode

    @property
    def profile(self) -> Dict[str, Any]:
        """Profil de configuration pour le mode actuel."""
        return ENERGY_PROFILES[self._mode]

    @property
    def thermal_monitor(self) -> ThermalMonitor:
        """Acces au moniteur thermique."""
        return self._thermal_monitor

    def on_mode_change(self, callback: Callable[[PowerMode], None]) -> None:
        """Enregistre un callback pour les changements de mode."""
        self._mode_change_callbacks.append(callback)

    def _set_mode(self, new_mode: PowerMode) -> None:
        """Change le mode et notifie les callbacks."""
        if new_mode == self._mode:
            return
        old = self._mode
        self._mode = new_mode
        logger.info(f"Mode energie: {old.value} -> {new_mode.value}")
        for cb in self._mode_change_callbacks:
            try:
                cb(new_mode)
            except Exception as e:
                logger.error(f"Mode change callback error: {e}")

    def _on_thermal_change(self, thermal_state: int) -> None:
        """Reagit aux changements thermiques."""
        if not self._auto:
            return
        if thermal_state >= ThermalMonitor.CRITICAL:
            self._set_mode(PowerMode.CRITICAL)
        elif thermal_state >= ThermalMonitor.SERIOUS:
            self._set_mode(PowerMode.ECO)
        elif thermal_state == ThermalMonitor.FAIR:
            # Ne pas remonter au-dessus de BALANCED si on etait en dessous
            if self._mode in (PowerMode.CRITICAL, PowerMode.ECO):
                self._set_mode(PowerMode.BALANCED)
        elif thermal_state == ThermalMonitor.NOMINAL:
            # Remonter a BALANCED (pas PERFORMANCE automatiquement)
            if self._mode in (PowerMode.CRITICAL, PowerMode.ECO):
                self._set_mode(PowerMode.BALANCED)

    def _evaluate_power_source(self) -> None:
        """Evalue la source d'alimentation et ajuste le mode."""
        if not self._auto:
            return

        battery = is_on_battery()
        percentage = get_battery_percentage()

        if battery and percentage is not None and percentage < self._low_battery_threshold:
            self._set_mode(PowerMode.ECO)
        elif battery and self._mode == PowerMode.PERFORMANCE:
            self._set_mode(PowerMode.BALANCED)
        elif not battery and self._mode == PowerMode.ECO:
            # Sur secteur et pas de pression thermique -> remonter
            if not self._thermal_monitor.is_throttling_recommended():
                self._set_mode(PowerMode.BALANCED)

    async def start(self) -> None:
        """Demarre les boucles de surveillance."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._power_check_loop())
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())
        logger.info("EnergyOrchestrator demarre")

    async def stop(self) -> None:
        """Arrete les boucles de surveillance."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._maintenance_task and not self._maintenance_task.done():
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
        self._thermal_monitor.cleanup()
        logger.info("EnergyOrchestrator arrete")

    async def _power_check_loop(self) -> None:
        """Verifie la source d'alimentation periodiquement."""
        while self._running:
            try:
                self._evaluate_power_source()
            except Exception as e:
                logger.error(f"Power check error: {e}")
            await asyncio.sleep(self._power_check_interval)

    async def _maintenance_loop(self) -> None:
        """Boucle de maintenance (decharger modeles idle en mode eco/critical)."""
        while self._running:
            try:
                if self._mode in (PowerMode.ECO, PowerMode.CRITICAL):
                    logger.debug("Maintenance eco: verification des modeles idle")
                    # La decharge effective se fait via provider_manager.unload_idle_models()
                    # appele par l'engine
            except Exception as e:
                logger.error(f"Maintenance error: {e}")
            await asyncio.sleep(60)

    def get_status_for_hud(self) -> Dict[str, Any]:
        """Retourne un dictionnaire de statut pour le HUD."""
        thermal = self._thermal_monitor.thermal_state
        battery_pct = get_battery_percentage()
        on_battery = is_on_battery()

        return {
            "mode": self._mode.value,
            "thermal_state": thermal,
            "thermal_name": self._thermal_monitor.thermal_state_name,
            "on_battery": on_battery,
            "battery_percent": battery_pct,
            "profile": self.profile,
            "auto": self._auto,
        }

    def get_energy_config(self) -> Dict[str, Any]:
        """Retourne la configuration energetique pour le ProviderManager."""
        p = self.profile
        return {
            "num_thread": p["ollama_threads"],
            "keep_alive": p["keep_alive"],
        }
