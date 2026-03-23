"""
Tests pour le gestionnaire d'energie.
Mock NSProcessInfo et subprocess pour eviter les dependances macOS dans la CI.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.services.energy_manager import (
    ENERGY_PROFILES,
    EnergyOrchestrator,
    PowerMode,
    ThermalMonitor,
    get_battery_percentage,
    is_on_battery,
)


# ─────────────────────────────────────────────────────────────────────────────
# PowerMode
# ─────────────────────────────────────────────────────────────────────────────
class TestPowerMode:
    """Teste l'enum PowerMode."""

    def test_values(self) -> None:
        assert PowerMode.PERFORMANCE.value == "performance"
        assert PowerMode.BALANCED.value == "balanced"
        assert PowerMode.ECO.value == "eco"
        assert PowerMode.CRITICAL.value == "critical"

    def test_all_modes_have_profile(self) -> None:
        for mode in PowerMode:
            assert mode in ENERGY_PROFILES, f"Profil manquant pour {mode}"

    def test_profile_keys(self) -> None:
        expected_keys = {
            "ollama_threads",
            "keep_alive",
            "faiss_mode",
            "max_agents",
            "inference_delay",
        }
        for mode in PowerMode:
            assert set(ENERGY_PROFILES[mode].keys()) == expected_keys


# ─────────────────────────────────────────────────────────────────────────────
# is_on_battery / get_battery_percentage
# ─────────────────────────────────────────────────────────────────────────────
class TestPowerSource:
    """Teste la detection de source d'alimentation."""

    @patch("app.services.energy_manager.subprocess.run")
    def test_is_on_battery_true(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            stdout="Now drawing from 'Battery Power'\n-InternalBattery-0\t87%"
        )
        assert is_on_battery() is True

    @patch("app.services.energy_manager.subprocess.run")
    def test_is_on_battery_false(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            stdout="Now drawing from 'AC Power'\n-InternalBattery-0\t100%"
        )
        assert is_on_battery() is False

    @patch("app.services.energy_manager.subprocess.run")
    def test_is_on_battery_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = Exception("pmset not found")
        assert is_on_battery() is False

    @patch("app.services.energy_manager.subprocess.run")
    def test_get_battery_percentage(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            stdout=(
                "Now drawing from 'Battery Power'\n"
                " -InternalBattery-0 (id=123)\t87%; discharging; 3:00 remaining\n"
            )
        )
        pct = get_battery_percentage()
        assert pct == 87

    @patch("app.services.energy_manager.subprocess.run")
    def test_get_battery_percentage_none(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = Exception("fail")
        assert get_battery_percentage() is None


# ─────────────────────────────────────────────────────────────────────────────
# ThermalMonitor
# ─────────────────────────────────────────────────────────────────────────────
class TestThermalMonitor:
    """Teste le moniteur thermique (mock NSProcessInfo)."""

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_thermal_state_range(self, mock_notif: MagicMock) -> None:
        monitor = ThermalMonitor()
        # Sans NSProcessInfo, state par defaut = NOMINAL
        assert monitor.thermal_state in (0, 1, 2, 3)

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_thermal_state_name(self, mock_notif: MagicMock) -> None:
        monitor = ThermalMonitor()
        assert monitor.thermal_state_name in ("nominal", "fair", "serious", "critical")

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_is_throttling_recommended(self, mock_notif: MagicMock) -> None:
        monitor = ThermalMonitor()
        # Desactiver NSProcessInfo pour controler l'etat manuellement
        monitor._nsprocessinfo = None
        monitor._thermal_state = ThermalMonitor.NOMINAL
        assert monitor.is_throttling_recommended() is False
        monitor._thermal_state = ThermalMonitor.SERIOUS
        assert monitor.is_throttling_recommended() is True
        monitor._thermal_state = ThermalMonitor.CRITICAL
        assert monitor.is_throttling_recommended() is True

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_on_thermal_change_callback(self, mock_notif: MagicMock) -> None:
        monitor = ThermalMonitor()
        received: list[int] = []
        monitor.on_thermal_change(lambda state: received.append(state))
        monitor._nsprocessinfo = MagicMock()
        monitor._nsprocessinfo.thermalState.return_value = 2
        monitor._on_thermal_change()
        assert received == [2]


# ─────────────────────────────────────────────────────────────────────────────
# EnergyOrchestrator
# ─────────────────────────────────────────────────────────────────────────────
class TestEnergyOrchestrator:
    """Teste l'orchestrateur d'energie."""

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_default_mode(self, mock_notif: MagicMock) -> None:
        orch = EnergyOrchestrator()
        assert orch.mode == PowerMode.BALANCED

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_forced_mode(self, mock_notif: MagicMock) -> None:
        orch = EnergyOrchestrator(energy_mode="eco")
        assert orch.mode == PowerMode.ECO

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_eco_on_serious_thermal(self, mock_notif: MagicMock) -> None:
        orch = EnergyOrchestrator()
        assert orch.mode == PowerMode.BALANCED
        orch._on_thermal_change(ThermalMonitor.SERIOUS)
        assert orch.mode == PowerMode.ECO

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_critical_on_critical_thermal(self, mock_notif: MagicMock) -> None:
        orch = EnergyOrchestrator()
        orch._on_thermal_change(ThermalMonitor.CRITICAL)
        assert orch.mode == PowerMode.CRITICAL

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    @patch("app.services.energy_manager.is_on_battery", return_value=True)
    @patch("app.services.energy_manager.get_battery_percentage", return_value=15)
    def test_eco_on_low_battery(
        self, mock_pct: MagicMock, mock_batt: MagicMock, mock_notif: MagicMock
    ) -> None:
        orch = EnergyOrchestrator()
        orch._evaluate_power_source()
        assert orch.mode == PowerMode.ECO

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    @patch("app.services.energy_manager.is_on_battery", return_value=True)
    @patch("app.services.energy_manager.get_battery_percentage", return_value=80)
    def test_balanced_on_battery_from_performance(
        self, mock_pct: MagicMock, mock_batt: MagicMock, mock_notif: MagicMock
    ) -> None:
        orch = EnergyOrchestrator()
        orch._set_mode(PowerMode.PERFORMANCE)
        orch._evaluate_power_source()
        assert orch.mode == PowerMode.BALANCED

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_profiles_correct(self, mock_notif: MagicMock) -> None:
        orch = EnergyOrchestrator()
        for mode in PowerMode:
            orch._set_mode(mode)
            profile = orch.profile
            assert "ollama_threads" in profile
            assert "keep_alive" in profile
            assert "faiss_mode" in profile

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_get_status_for_hud(self, mock_notif: MagicMock) -> None:
        orch = EnergyOrchestrator()
        status = orch.get_status_for_hud()
        assert "mode" in status
        assert "thermal_state" in status
        assert "thermal_name" in status
        assert "on_battery" in status
        assert "profile" in status

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_get_energy_config(self, mock_notif: MagicMock) -> None:
        orch = EnergyOrchestrator()
        config = orch.get_energy_config()
        assert "num_thread" in config
        assert "keep_alive" in config

    @pytest.mark.asyncio
    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    async def test_start_stop(self, mock_notif: MagicMock) -> None:
        orch = EnergyOrchestrator()
        await orch.start()
        assert orch._running is True
        await orch.stop()
        assert orch._running is False

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_mode_change_callback(self, mock_notif: MagicMock) -> None:
        orch = EnergyOrchestrator()
        modes_received: list[PowerMode] = []
        orch.on_mode_change(lambda m: modes_received.append(m))
        orch._set_mode(PowerMode.ECO)
        assert modes_received == [PowerMode.ECO]

    @patch("app.services.energy_manager.ThermalMonitor._register_notification")
    def test_no_change_callback_same_mode(self, mock_notif: MagicMock) -> None:
        orch = EnergyOrchestrator()
        modes_received: list[PowerMode] = []
        orch.on_mode_change(lambda m: modes_received.append(m))
        orch._set_mode(PowerMode.BALANCED)  # deja BALANCED
        assert modes_received == []
