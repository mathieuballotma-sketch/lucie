"""
Tests du HybridProviderManager et du MLXProvider.

Couvre :
- Détection Apple Silicon (mock platform)
- Fallback Ollama quand MLX indisponible
- Sélection du provider par task_type
- CircuitBreaker sur échec MLX → fallback Ollama
- Détection hardware (HardwareConfig)
"""

import sys
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_ollama_mock() -> MagicMock:
    """Crée un mock ProviderManager (Ollama) prêt à l'emploi."""
    mock = MagicMock()
    mock.generate.return_value = "réponse ollama"
    mock.is_available.return_value = True
    mock.list_models.return_value = ["qwen2.5:7b"]
    mock.router = MagicMock()
    return mock


def _make_mlx_mock(available: bool = True) -> MagicMock:
    """Crée un mock MLXProvider prêt à l'emploi."""
    mock = MagicMock()
    mock.generate.return_value = "réponse mlx"
    mock.is_available.return_value = available
    mock.list_models.return_value = ["mlx-community/Qwen2.5-7B-Instruct-4bit"]
    mock.default_model = "mlx-community/Qwen2.5-7B-Instruct-4bit"
    return mock


# ═══════════════════════════════════════════════════════════════════════════════
# Tests MLXProvider
# ═══════════════════════════════════════════════════════════════════════════════


class TestMLXProvider:
    """Tests de la classe MLXProvider."""

    def test_unavailable_when_flag_false(self) -> None:
        """is_available() retourne False si _available=False."""
        from app.providers.mlx_provider import MLXProvider

        provider = MLXProvider()
        provider._available = False
        assert not provider.is_available()

    def test_available_when_flag_true(self) -> None:
        """is_available() retourne True si _available=True."""
        from app.providers.mlx_provider import MLXProvider

        provider = MLXProvider()
        provider._available = True
        assert provider.is_available()

    def test_generate_raises_when_unavailable(self) -> None:
        """generate() lève RuntimeError si MLX non disponible."""
        from app.providers.mlx_provider import MLXProvider

        provider = MLXProvider()
        provider._available = False

        with pytest.raises(RuntimeError, match="non disponible"):
            provider.generate("bonjour")

    def test_list_models_empty_when_unavailable(self) -> None:
        """list_models() retourne [] si MLX non disponible."""
        from app.providers.mlx_provider import MLXProvider

        provider = MLXProvider()
        provider._available = False
        assert provider.list_models() == []

    def test_generate_calls_mlx_lm(self) -> None:
        """generate() appelle mlx_lm.load et mlx_lm.generate."""
        from app.providers.mlx_provider import MLXProvider, _model_cache

        # Vider le cache pour forcer un "chargement"
        _model_cache.clear()

        mock_mlx_module = MagicMock()
        mock_mlx_module.load.return_value = (MagicMock(), MagicMock())
        mock_mlx_module.generate.return_value = "réponse mlx test"

        with patch.dict(sys.modules, {"mlx_lm": mock_mlx_module}):
            provider = MLXProvider({"mlx_model": "mlx-community/Test-4bit"})
            provider._available = True

            result = provider.generate("test prompt", max_tokens=128)

        assert result == "réponse mlx test"
        mock_mlx_module.load.assert_called_once_with("mlx-community/Test-4bit")
        mock_mlx_module.generate.assert_called_once()

    def test_generate_uses_model_cache(self) -> None:
        """Un modèle déjà chargé n'est pas rechargé au second appel."""
        from app.providers.mlx_provider import MLXProvider, _model_cache

        _model_cache.clear()

        mock_mlx_module = MagicMock()
        mock_mlx_module.load.return_value = (MagicMock(), MagicMock())
        mock_mlx_module.generate.return_value = "ok"

        with patch.dict(sys.modules, {"mlx_lm": mock_mlx_module}):
            provider = MLXProvider({"mlx_model": "mlx-community/Test-4bit"})
            provider._available = True

            provider.generate("prompt 1")
            provider.generate("prompt 2")

        # load() ne doit être appelé qu'une seule fois
        assert mock_mlx_module.load.call_count == 1

    def test_generate_with_system_prompt(self) -> None:
        """generate() formate correctement le prompt quand system est fourni."""
        from app.providers.mlx_provider import MLXProvider, _model_cache

        _model_cache.clear()

        captured: Dict[str, Any] = {}

        def fake_generate(model, tokenizer, prompt, **kwargs):  # type: ignore[no-untyped-def]
            captured["prompt"] = prompt
            return "réponse"

        mock_mlx_module = MagicMock()
        mock_mlx_module.load.return_value = (MagicMock(), MagicMock())
        mock_mlx_module.generate.side_effect = fake_generate

        with patch.dict(sys.modules, {"mlx_lm": mock_mlx_module}):
            provider = MLXProvider()
            provider._available = True
            provider.generate("question", system="Tu es un assistant")

        assert "<|system|>" in captured["prompt"]
        assert "Tu es un assistant" in captured["prompt"]
        assert "question" in captured["prompt"]

    def test_not_available_on_x86(self) -> None:
        """MLXProvider._available doit être False sur x86_64."""
        with patch("platform.machine", return_value="x86_64"):
            with patch("app.providers.mlx_provider._MLX_IMPORT_OK", False):
                from app.providers.mlx_provider import MLXProvider

                provider = MLXProvider()
                assert not provider._available


# ═══════════════════════════════════════════════════════════════════════════════
# Tests HybridProviderManager — sélection du provider
# ═══════════════════════════════════════════════════════════════════════════════


class TestHybridProviderManagerSelection:
    """Tests de la sélection du provider par task_type."""

    @pytest.fixture
    def manager_with_mlx(self) -> Any:
        """HybridProviderManager avec MLX et Ollama mockés."""
        from app.providers.provider_manager import HybridProviderManager

        with patch("app.providers.provider_manager.ProviderManager") as mock_pm_cls:
            mock_pm_cls.return_value = _make_ollama_mock()
            with patch("app.providers.provider_manager.MLXProvider") as mock_mlx_cls:
                mock_mlx_cls.return_value = _make_mlx_mock(available=True)
                mgr = HybridProviderManager({})

        return mgr

    @pytest.fixture
    def manager_no_mlx(self) -> Any:
        """HybridProviderManager sans MLX (Ollama seul)."""
        from app.providers.provider_manager import HybridProviderManager

        with patch("app.providers.provider_manager.ProviderManager") as mock_pm_cls:
            mock_pm_cls.return_value = _make_ollama_mock()
            with patch("app.providers.provider_manager.MLXProvider") as mock_mlx_cls:
                mock_mlx_cls.return_value = _make_mlx_mock(available=False)
                mgr = HybridProviderManager({})

        return mgr

    def test_get_provider_routing_returns_mlx(self, manager_with_mlx: Any) -> None:
        """get_provider('routing') retourne MLX si disponible."""
        provider = manager_with_mlx.get_provider("routing")
        assert provider is manager_with_mlx._mlx

    def test_get_provider_fast_returns_mlx(self, manager_with_mlx: Any) -> None:
        """get_provider('fast') retourne MLX si disponible."""
        provider = manager_with_mlx.get_provider("fast")
        assert provider is manager_with_mlx._mlx

    def test_get_provider_default_returns_mlx(self, manager_with_mlx: Any) -> None:
        """get_provider('default') retourne MLX si disponible."""
        provider = manager_with_mlx.get_provider("default")
        assert provider is manager_with_mlx._mlx

    def test_get_provider_fallback_returns_ollama(self, manager_with_mlx: Any) -> None:
        """get_provider('fallback') retourne toujours Ollama."""
        provider = manager_with_mlx.get_provider("fallback")
        assert provider is manager_with_mlx._ollama

    def test_get_provider_quality_returns_ollama(self, manager_with_mlx: Any) -> None:
        """get_provider('quality') retourne toujours Ollama."""
        provider = manager_with_mlx.get_provider("quality")
        assert provider is manager_with_mlx._ollama

    def test_get_provider_returns_ollama_when_mlx_none(
        self, manager_no_mlx: Any
    ) -> None:
        """get_provider retourne Ollama quand MLX n'est pas initialisé."""
        provider = manager_no_mlx.get_provider("routing")
        assert provider is manager_no_mlx._ollama


# ═══════════════════════════════════════════════════════════════════════════════
# Tests HybridProviderManager — generate()
# ═══════════════════════════════════════════════════════════════════════════════


class TestHybridProviderManagerGenerate:
    """Tests de la méthode generate() avec différents scénarios."""

    def _build_manager(
        self, ollama_mock: MagicMock, mlx_mock: MagicMock
    ) -> Any:
        """Construit un HybridProviderManager avec des backends mockés."""
        from app.providers.provider_manager import HybridProviderManager

        with patch("app.providers.provider_manager.ProviderManager") as pm_cls:
            pm_cls.return_value = ollama_mock
            with patch("app.providers.provider_manager.MLXProvider") as mlx_cls:
                mlx_cls.return_value = mlx_mock
                mgr = HybridProviderManager({})
        return mgr

    def test_generate_uses_mlx_when_available(self) -> None:
        """generate() utilise MLX si disponible et priority != forcé."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=True)
        mgr = self._build_manager(ollama, mlx)

        result = mgr.generate("bonjour", priority="auto")

        mlx.generate.assert_called_once()
        ollama.generate.assert_not_called()
        assert result == "réponse mlx"

    def test_generate_falls_back_to_ollama_when_mlx_none(self) -> None:
        """generate() utilise Ollama si MLX non initialisé."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=False)
        mgr = self._build_manager(ollama, mlx)

        result = mgr.generate("bonjour", priority="auto")

        ollama.generate.assert_called_once()
        assert result == "réponse ollama"

    def test_generate_forces_ollama_for_quality(self) -> None:
        """generate() force Ollama pour priority='quality'."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=True)
        mgr = self._build_manager(ollama, mlx)

        result = mgr.generate("bonjour", priority="quality")

        ollama.generate.assert_called_once()
        mlx.generate.assert_not_called()
        assert result == "réponse ollama"

    def test_generate_forces_ollama_for_fallback(self) -> None:
        """generate() force Ollama pour priority='fallback'."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=True)
        mgr = self._build_manager(ollama, mlx)

        result = mgr.generate("bonjour", priority="fallback")

        ollama.generate.assert_called_once()
        mlx.generate.assert_not_called()
        assert result == "réponse ollama"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests CircuitBreaker sur MLX
# ═══════════════════════════════════════════════════════════════════════════════


class TestCircuitBreakerMLX:
    """Tests du CircuitBreaker qui protège les appels MLX."""

    def _build_manager(
        self, ollama_mock: MagicMock, mlx_mock: MagicMock
    ) -> Any:
        from app.providers.provider_manager import HybridProviderManager

        with patch("app.providers.provider_manager.ProviderManager") as pm_cls:
            pm_cls.return_value = ollama_mock
            with patch("app.providers.provider_manager.MLXProvider") as mlx_cls:
                mlx_cls.return_value = mlx_mock
                mgr = HybridProviderManager({})
        return mgr

    def test_circuit_breaker_present_when_mlx_available(self) -> None:
        """_mlx_cb est initialisé quand MLX est disponible."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=True)
        mgr = self._build_manager(ollama, mlx)

        assert mgr._mlx_cb is not None

    def test_circuit_breaker_absent_when_mlx_unavailable(self) -> None:
        """_mlx_cb est None quand MLX n'est pas disponible."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=False)
        mgr = self._build_manager(ollama, mlx)

        assert mgr._mlx_cb is None

    def test_fallback_to_ollama_on_mlx_failure(self) -> None:
        """generate() bascule vers Ollama quand MLX lève une exception."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=True)
        mlx.generate.side_effect = RuntimeError("MLX crash simulé")

        mgr = self._build_manager(ollama, mlx)

        # Un seul échec → le CircuitBreaker appelle le fallback (Ollama)
        result = mgr.generate("test", priority="fast")

        ollama.generate.assert_called_once()
        assert result == "réponse ollama"

    def test_circuit_opens_after_repeated_failures(self) -> None:
        """Le circuit s'ouvre après failure_threshold échecs et redirige vers Ollama."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=True)
        mlx.generate.side_effect = RuntimeError("MLX crash")

        mgr = self._build_manager(ollama, mlx)
        assert mgr._mlx_cb is not None

        # Déclencher failure_threshold (=3) échecs pour ouvrir le circuit
        for _ in range(3):
            mgr.generate("test", priority="auto")

        # Le circuit doit être OPEN
        from app.utils.circuit_breaker import CircuitState as CS

        assert mgr._mlx_cb.state == CS.OPEN

        # Après ouverture, les appels suivants utilisent directement Ollama
        ollama.generate.reset_mock()
        result = mgr.generate("encore", priority="auto")
        ollama.generate.assert_called_once()
        assert result == "réponse ollama"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests détection hardware (HardwareConfig)
# ═══════════════════════════════════════════════════════════════════════════════


class TestHardwareDetection:
    """Tests de la détection automatique du hardware."""

    def test_detect_hardware_returns_hardware_config(self) -> None:
        """detect_hardware() retourne un HardwareConfig valide."""
        from app.core.config import HardwareConfig, detect_hardware

        hw = detect_hardware()
        assert isinstance(hw, HardwareConfig)
        assert hw.ram_gb > 0
        assert hw.tier in ("Light", "Standard", "Full", "Pro")
        assert isinstance(hw.is_apple_silicon, bool)

    def test_tier_light_for_8gb(self) -> None:
        """Tier 'Light' pour ≤8 Go."""
        from app.core.config import detect_hardware

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=str(8 * 1024**3)
            )
            hw = detect_hardware()

        assert hw.tier == "Light"
        assert hw.ram_gb == pytest.approx(8.0, abs=0.5)

    def test_tier_standard_for_16gb(self) -> None:
        """Tier 'Standard' pour ≤16 Go."""
        from app.core.config import detect_hardware

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=str(16 * 1024**3)
            )
            hw = detect_hardware()

        assert hw.tier == "Standard"

    def test_tier_full_for_24gb(self) -> None:
        """Tier 'Full' pour ≤24 Go."""
        from app.core.config import detect_hardware

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=str(24 * 1024**3)
            )
            hw = detect_hardware()

        assert hw.tier == "Full"

    def test_tier_pro_for_32gb(self) -> None:
        """Tier 'Pro' pour >24 Go."""
        from app.core.config import detect_hardware

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=str(32 * 1024**3)
            )
            hw = detect_hardware()

        assert hw.tier == "Pro"

    def test_apple_silicon_flag_on_arm64(self) -> None:
        """is_apple_silicon=True sur arm64."""
        from app.core.config import detect_hardware

        with patch("platform.machine", return_value="arm64"):
            hw = detect_hardware()

        assert hw.is_apple_silicon is True

    def test_apple_silicon_flag_false_on_x86(self) -> None:
        """is_apple_silicon=False sur x86_64."""
        from app.core.config import detect_hardware

        with patch("platform.machine", return_value="x86_64"):
            hw = detect_hardware()

        assert hw.is_apple_silicon is False

    def test_detect_hardware_graceful_on_failure(self) -> None:
        """detect_hardware() ne crashe pas si sysctl ET psutil échouent."""
        from app.core.config import HardwareConfig, detect_hardware

        with patch("app.core.config.subprocess.run", side_effect=Exception("sysctl indisponible")):
            # Masquer aussi psutil pour forcer le chemin de code du fallback pur
            with patch.dict(sys.modules, {"psutil": None}):
                hw = detect_hardware()

        assert isinstance(hw, HardwareConfig)
        assert hw.ram_gb == 8.0  # valeur par défaut quand tout échoue
        assert hw.tier == "Light"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests intégration — HybridProviderManager.list_models et is_available
# ═══════════════════════════════════════════════════════════════════════════════


class TestHybridProviderManagerMisc:
    """Tests complémentaires de HybridProviderManager."""

    def _build_manager(
        self, ollama_mock: MagicMock, mlx_mock: MagicMock
    ) -> Any:
        from app.providers.provider_manager import HybridProviderManager

        with patch("app.providers.provider_manager.ProviderManager") as pm_cls:
            pm_cls.return_value = ollama_mock
            with patch("app.providers.provider_manager.MLXProvider") as mlx_cls:
                mlx_cls.return_value = mlx_mock
                mgr = HybridProviderManager({})
        return mgr

    def test_list_models_combines_both_backends(self) -> None:
        """list_models() concatène les modèles Ollama et MLX."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=True)
        mgr = self._build_manager(ollama, mlx)

        models = mgr.list_models()
        assert "qwen2.5:7b" in models
        assert "mlx-community/Qwen2.5-7B-Instruct-4bit" in models

    def test_list_models_only_ollama_when_mlx_none(self) -> None:
        """list_models() ne retourne que les modèles Ollama si MLX indisponible."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=False)
        mgr = self._build_manager(ollama, mlx)

        models = mgr.list_models()
        assert "qwen2.5:7b" in models
        assert "mlx-community/Qwen2.5-7B-Instruct-4bit" not in models

    def test_is_available_true_when_mlx_active(self) -> None:
        """is_available() retourne True si MLX est disponible."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=True)
        mgr = self._build_manager(ollama, mlx)

        assert mgr.is_available() is True

    def test_is_available_true_when_ollama_only(self) -> None:
        """is_available() retourne True si seul Ollama est disponible."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=False)
        mgr = self._build_manager(ollama, mlx)

        assert mgr.is_available() is True

    def test_get_health_structure(self) -> None:
        """get_health() retourne la structure attendue."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=True)
        mgr = self._build_manager(ollama, mlx)

        health = mgr.get_health()
        assert "ollama" in health
        assert "mlx" in health
        assert "apple_silicon" in health
        assert "available" in health["ollama"]
        assert "available" in health["mlx"]

    def test_router_exposed_from_ollama(self) -> None:
        """Le router du HybridProviderManager est celui d'Ollama."""
        ollama = _make_ollama_mock()
        mlx = _make_mlx_mock(available=True)
        mgr = self._build_manager(ollama, mlx)

        assert mgr.router is ollama.router
