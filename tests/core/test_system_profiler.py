"""
Tests pour SystemProfiler.
psutil est mocké pour simuler différentes configurations matérielles.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.core.system_profiler import SystemProfiler, SystemProfile


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_vmem(total_gb: float, available_gb: float, percent: float = 50.0):
    """Crée un mock psutil.virtual_memory."""
    m = MagicMock()
    m.total = int(total_gb * 1024 ** 3)
    m.available = int(available_gb * 1024 ** 3)
    m.percent = percent
    return m


def _make_disk(free_gb: float, total_gb: float = 500.0):
    """Crée un mock psutil.disk_usage."""
    m = MagicMock()
    m.free = int(free_gb * 1024 ** 3)
    m.total = int(total_gb * 1024 ** 3)
    return m


@pytest.fixture
def profiler():
    return SystemProfiler()


# ─────────────────────────────────────────────────────────────────────────────
# detect()
# ─────────────────────────────────────────────────────────────────────────────

class TestDetect:
    def test_detect_returns_system_profile(self, profiler):
        """detect() retourne un SystemProfile."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 8)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.detect()
        assert isinstance(result, SystemProfile)

    def test_detect_profile_valid(self, profiler):
        """detect() retourne un profil valide parmi les clés PROFILES."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 8)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.detect()
        assert result.profile in SystemProfiler.PROFILES

    def test_detect_ram_positive(self, profiler):
        """detect() retourne des valeurs RAM positives."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 8)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.detect()
        assert result.ram_total_gb > 0
        assert result.ram_available_gb > 0

    def test_detect_disk_positive(self, profiler):
        """detect() retourne un espace disque positif."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 8)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.detect()
        assert result.disk_free_gb > 0

    def test_detect_chip_is_string(self, profiler):
        """detect() retourne un chip non vide."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 8)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.detect()
        assert isinstance(result.chip, str)
        assert len(result.chip) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Seuils de profils
# ─────────────────────────────────────────────────────────────────────────────

class TestProfileThresholds:
    def test_8gb_is_light(self, profiler):
        """8 Go → profil light."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(8, 4)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.detect()
        assert result.profile == "light"

    def test_16gb_is_light(self, profiler):
        """16 Go exactement → profil light (≤ 16)."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 8)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.detect()
        assert result.profile == "light"

    def test_24gb_is_standard(self, profiler):
        """24 Go → profil standard."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(24, 12)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.detect()
        assert result.profile == "standard"

    def test_32gb_is_performance(self, profiler):
        """32 Go → profil performance."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(32, 16)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.detect()
        assert result.profile == "performance"

    def test_48gb_is_performance(self, profiler):
        """48 Go → profil performance."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(48, 24)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.detect()
        assert result.profile == "performance"


# ─────────────────────────────────────────────────────────────────────────────
# get_available_ram()
# ─────────────────────────────────────────────────────────────────────────────

class TestGetAvailableRam:
    def test_returns_float(self, profiler):
        """get_available_ram() retourne un float."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 8)):
            result = profiler.get_available_ram()
        assert isinstance(result, float)

    def test_returns_positive(self, profiler):
        """get_available_ram() retourne une valeur > 0."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 8)):
            result = profiler.get_available_ram()
        assert result > 0

    def test_correct_value(self, profiler):
        """get_available_ram() retourne la bonne valeur en Go."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 6)):
            result = profiler.get_available_ram()
        assert abs(result - 6.0) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# should_swap_model()
# ─────────────────────────────────────────────────────────────────────────────

class TestShouldSwapModel:
    def test_no_swap_when_ram_ok(self, profiler):
        """Pas de swap si RAM disponible ≥ 2 Go."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 8)):
            assert profiler.should_swap_model() is False

    def test_swap_when_ram_critical(self, profiler):
        """Swap si RAM disponible < 2 Go."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 1)):
            assert profiler.should_swap_model() is True

    def test_swap_at_exact_threshold(self, profiler):
        """Pas de swap si RAM exactement à 2 Go."""
        # 2.0 Go n'est PAS < 2.0, donc pas de swap
        available_bytes = int(2.0 * 1024 ** 3)
        m = MagicMock()
        m.total = int(16 * 1024 ** 3)
        m.available = available_bytes
        m.percent = 50.0
        with patch("psutil.virtual_memory", return_value=m):
            assert profiler.should_swap_model() is False


# ─────────────────────────────────────────────────────────────────────────────
# recommend_actions()
# ─────────────────────────────────────────────────────────────────────────────

class TestRecommendActions:
    def test_returns_list(self, profiler):
        """recommend_actions() retourne une liste."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 8)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.recommend_actions()
        assert isinstance(result, list)

    def test_no_recommendations_when_healthy(self, profiler):
        """Aucune recommandation si système en bonne santé."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 8, percent=50)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.recommend_actions()
        assert result == []

    def test_recommends_disk_cleanup_when_low(self, profiler):
        """Recommande nettoyage disque si < 5 Go libre."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 8, percent=50)), \
             patch("psutil.disk_usage", return_value=_make_disk(3.2)):
            result = profiler.recommend_actions()
        assert len(result) >= 1
        assert any("Stockage" in r or "stockage" in r.lower() for r in result)

    def test_recommends_eco_mode_when_ram_low(self, profiler):
        """Recommande mode économique si RAM < 4 Go."""
        with patch("psutil.virtual_memory", return_value=_make_vmem(16, 2, percent=87)), \
             patch("psutil.disk_usage", return_value=_make_disk(100)):
            result = profiler.recommend_actions()
        assert len(result) >= 1
        assert any("RAM" in r or "mémoire" in r.lower() for r in result)


# ─────────────────────────────────────────────────────────────────────────────
# PROFILES constant
# ─────────────────────────────────────────────────────────────────────────────

class TestProfilesConstant:
    def test_all_profiles_present(self):
        assert "light" in SystemProfiler.PROFILES
        assert "standard" in SystemProfiler.PROFILES
        assert "performance" in SystemProfiler.PROFILES

    def test_all_profiles_have_models(self):
        for name, profile in SystemProfiler.PROFILES.items():
            assert "models" in profile, f"Profil {name} manque 'models'"
            assert len(profile["models"]) > 0

    def test_all_profiles_have_vision(self):
        for name, profile in SystemProfiler.PROFILES.items():
            assert "vision" in profile, f"Profil {name} manque 'vision'"
            assert "vision_model" in profile, f"Profil {name} manque 'vision_model'"

    def test_light_profile_uses_e4b(self):
        assert "gemma4:e4b" in SystemProfiler.PROFILES["light"]["models"]

    def test_performance_profile_has_parallel(self):
        assert SystemProfiler.PROFILES["performance"].get("parallel") is True
