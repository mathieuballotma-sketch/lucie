"""
HardwareProfiler — Détecte les specs du Mac et choisit la config modèle adaptée.

Salvagé depuis app/core/system_profiler.py (archive/pre-cleanup).
Modifications :
- Retrait de la dépendance app.utils.logger → logging stdlib
- Retrait des PROFILES hard-codés Gemma 4 → ModelConfig dynamique
- Ajout choose_model_config() avec seuils documentés
- subprocess.run utilisé avec timeout=2, sans shell=True (safe)
"""

from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass
from typing import List

import psutil

logger = logging.getLogger(__name__)


@dataclass
class HardwareProfile:
    """Snapshot des specs matérielles détectées."""
    ram_gb: float           # RAM totale (Go)
    storage_free_gb: float  # Espace disque libre (Go)
    is_apple_silicon: bool
    chip_generation: str    # "M1", "M2", "M3", "M4", "x86_64", "arm64"
    gpu_cores: int
    ram_available_gb: float  # RAM disponible en temps réel


@dataclass
class ModelConfig:
    """Configuration de modèles recommandée selon le profil matériel."""
    primary: str        # Modèle principal (qualité)
    fast: str           # Modèle rapide (extraction / vérification)
    use_mlx: bool       # Activer MLX (Apple Silicon ≥32 Go)

    def __str__(self) -> str:
        mlx = "+MLX" if self.use_mlx else ""
        return f"primary={self.primary}, fast={self.fast}{mlx}"


# Seuils RAM pour la sélection du profil
_LOW_RAM_GB = 16.0    # < 16 Go → fast only
_MID_RAM_GB = 32.0    # 16–31 Go → primary + fast, sans MLX


class HardwareProfiler:
    """
    Détecte les specs du Mac et recommande la configuration de modèles.

    Seuils :
      < 16 Go  → fast only (E2B)
      16–31 Go → primary (E4B) + fast (E2B), MLX désactivé
      ≥ 32 Go  → primary (E4B) + fast (E2B) + MLX activé
    """

    def detect(self) -> HardwareProfile:
        """Détecte RAM, disque, chip, GPU cores. Retourne un HardwareProfile."""
        mem = psutil.virtual_memory()
        ram_gb = mem.total / (1024 ** 3)
        ram_available_gb = mem.available / (1024 ** 3)

        disk = psutil.disk_usage("/")
        storage_free_gb = disk.free / (1024 ** 3)

        chip = self._detect_chip()
        is_apple_silicon = chip in ("M1", "M2", "M3", "M4", "arm64")
        gpu_cores = self._detect_gpu_cores(chip)

        profile = HardwareProfile(
            ram_gb=round(ram_gb, 1),
            storage_free_gb=round(storage_free_gb, 1),
            is_apple_silicon=is_apple_silicon,
            chip_generation=chip,
            gpu_cores=gpu_cores,
            ram_available_gb=round(ram_available_gb, 1),
        )
        logger.info(
            "HardwareProfiler: chip=%s ram=%.1fGo libre=%.1fGo",
            chip, ram_gb, storage_free_gb,
        )
        return profile

    def get_available_ram(self) -> float:
        """RAM disponible en temps réel (Go)."""
        return psutil.virtual_memory().available / (1024 ** 3)

    def should_swap_to_fast(self) -> bool:
        """True si RAM disponible critique (< 2 Go) → basculer sur modèle fast."""
        return self.get_available_ram() < 2.0

    def recommend_warnings(self) -> List[str]:
        """Avertissements proactifs sur l'état du système."""
        warnings: List[str] = []

        disk = psutil.disk_usage("/")
        if disk.free / (1024 ** 3) < 5.0:
            warnings.append(
                f"Stockage faible ({disk.free / (1024**3):.1f} Go libre). "
                "Nettoyage recommandé avant de continuer."
            )

        ram_available = self.get_available_ram()
        if ram_available < 4.0:
            warnings.append(
                f"RAM disponible faible ({ram_available:.1f} Go). "
                "Mode économique activé automatiquement."
            )

        return warnings

    # ------------------------------------------------------------------
    # Méthodes internes
    # ------------------------------------------------------------------

    def _detect_chip(self) -> str:
        machine = platform.machine()
        if machine != "arm64":
            return machine  # "x86_64" ou autre architecture

        # Apple Silicon — détection précise M1/M2/M3/M4
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            brand = result.stdout.strip().lower()
            for gen in ("m4", "m3", "m2", "m1"):
                if gen in brand:
                    return gen.upper()
        except Exception:
            pass

        return "arm64"

    def _detect_gpu_cores(self, chip: str) -> int:
        _GPU_CORES = {"M1": 8, "M2": 10, "M3": 10, "M4": 10}
        return _GPU_CORES.get(chip, 0)


def choose_model_config(profile: HardwareProfile) -> ModelConfig:
    """
    Sélectionne la config de modèles selon le profil matériel.

    Seuils :
      < 16 Go  → fast (E2B) seulement, pas de MLX
      16–31 Go → primary (E4B) + fast (E2B), pas de MLX
      ≥ 32 Go  → primary (E4B) + fast (E2B) + MLX (Apple Silicon)
    """
    if profile.ram_gb < _LOW_RAM_GB:
        return ModelConfig(primary="gemma4:e2b", fast="gemma4:e2b", use_mlx=False)

    if profile.ram_gb < _MID_RAM_GB:
        return ModelConfig(primary="gemma4:e4b", fast="gemma4:e2b", use_mlx=False)

    # ≥ 32 Go
    use_mlx = profile.is_apple_silicon
    return ModelConfig(primary="gemma4:e4b", fast="gemma4:e2b", use_mlx=use_mlx)
