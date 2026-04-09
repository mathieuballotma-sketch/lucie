"""
SystemProfiler — Détecte les specs du Mac et adapte la configuration de Lucie.
Fournit des profils "light", "standard", "performance" basés sur la RAM disponible.
"""

import platform
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

import psutil

from ..utils.logger import logger


@dataclass
class SystemProfile:
    """Snapshot des specs matérielles et du profil sélectionné."""
    ram_total_gb: float
    ram_available_gb: float
    disk_free_gb: float
    chip: str              # "M1", "M2", "M3", "M4" ou "arm64" / "x86_64"
    gpu_cores: int
    profile: str           # "light", "standard", "performance"


class SystemProfiler:
    """
    Détecte les specs du Mac et recommande un profil de configuration.
    """

    PROFILES = {
        "light": {
            "max_ram": 16,
            "models": ["gemma4:e4b"],
            "vision": True,
            "vision_model": "gemma4:e4b",
        },
        "standard": {
            "max_ram": 24,
            "models": ["gemma4:e4b", "gemma4:26b"],
            "vision": True,
            "vision_model": "gemma4:26b",
        },
        "performance": {
            "max_ram": 999,
            "models": ["gemma4:e4b", "gemma4:26b"],
            "vision": True,
            "vision_model": "gemma4:26b",
            "parallel": True,
        },
    }

    # Seuils RAM pour sélection du profil (en Go)
    _LIGHT_MAX = 16.0
    _STANDARD_MAX = 24.0

    def detect(self) -> SystemProfile:
        """
        Détecte RAM, disque, chip, GPU cores. Retourne un SystemProfile.
        """
        mem = psutil.virtual_memory()
        ram_total_gb = mem.total / (1024 ** 3)
        ram_available_gb = mem.available / (1024 ** 3)

        disk = psutil.disk_usage("/")
        disk_free_gb = disk.free / (1024 ** 3)

        chip = self._detect_chip()
        gpu_cores = self._detect_gpu_cores(chip)
        profile = self._select_profile(ram_total_gb)

        logger.info(
            f"SystemProfiler: chip={chip}, RAM={ram_total_gb:.1f}Go, "
            f"dispo={ram_available_gb:.1f}Go, profil={profile}"
        )

        return SystemProfile(
            ram_total_gb=round(ram_total_gb, 1),
            ram_available_gb=round(ram_available_gb, 1),
            disk_free_gb=round(disk_free_gb, 1),
            chip=chip,
            gpu_cores=gpu_cores,
            profile=profile,
        )

    def get_available_ram(self) -> float:
        """Retourne la RAM disponible en temps réel (Go)."""
        return psutil.virtual_memory().available / (1024 ** 3)

    def should_swap_model(self) -> bool:
        """
        True si la RAM disponible est critique (< 2 Go).
        Indique qu'il faut passer au modèle plus léger.
        """
        return self.get_available_ram() < 2.0

    def recommend_actions(self) -> List[str]:
        """
        Recommandations proactives basées sur l'état du système.
        """
        recommendations: List[str] = []

        disk = psutil.disk_usage("/")
        disk_free_gb = disk.free / (1024 ** 3)
        if disk_free_gb < 5.0:
            recommendations.append(
                f"Stockage faible ({disk_free_gb:.1f} Go libre). "
                "Voulez-vous que j'identifie les gros fichiers ?"
            )

        ram_available = self.get_available_ram()
        if ram_available < 4.0:
            recommendations.append(
                f"RAM disponible faible ({ram_available:.1f} Go). "
                "Je passe en mode économique (gemma4:e4b)."
            )

        mem = psutil.virtual_memory()
        if mem.percent > 90:
            recommendations.append(
                f"Utilisation mémoire critique ({mem.percent:.0f}%). "
                "Certains agents peuvent être ralentis."
            )

        return recommendations

    # ── Méthodes internes ────────────────────────────────────────────────────

    def _detect_chip(self) -> str:
        """Détecte le type de puce Apple Silicon ou x86_64."""
        machine = platform.machine()
        if machine != "arm64":
            return machine  # "x86_64" ou autre

        # Apple Silicon — cherche M1/M2/M3/M4 via sysctl
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            brand = result.stdout.strip().lower()
            for model in ("m4", "m3", "m2", "m1"):
                if model in brand:
                    return model.upper()
        except Exception:
            pass

        return "arm64"

    def _detect_gpu_cores(self, chip: str) -> int:
        """
        Estime le nombre de cœurs GPU selon la puce.
        Valeurs approximatives pour les puces Apple Silicon standard.
        """
        _GPU_CORES = {
            "M1": 8,
            "M2": 10,
            "M3": 10,
            "M4": 10,
        }
        return _GPU_CORES.get(chip, 0)

    def _select_profile(self, ram_total_gb: float) -> str:
        """Sélectionne le profil selon la RAM totale."""
        if ram_total_gb <= self._LIGHT_MAX:
            return "light"
        elif ram_total_gb <= self._STANDARD_MAX:
            return "standard"
        else:
            return "performance"
