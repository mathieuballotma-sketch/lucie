"""Tests unitaires — VersionChecker + SemanticVersion (SEC-QW-03)."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.security.version_checker import (
    SemanticVersion,
    VersionChecker,
    VersionCheckResult,
)


# ---------------------------------------------------------------------------
# SemanticVersion — parsing
# ---------------------------------------------------------------------------

class TestSemanticVersionParse:
    def test_simple_three_part(self):
        v = SemanticVersion("1.2.3")
        assert (v.major, v.minor, v.patch) == (1, 2, 3)
        assert v.pre is None

    def test_with_v_prefix(self):
        v = SemanticVersion("v2.0.0")
        assert v.major == 2

    def test_prerelease(self):
        v = SemanticVersion("0.2.0-beta")
        assert v.pre == "beta"

    def test_two_part_version(self):
        v = SemanticVersion("4.0")
        assert (v.major, v.minor, v.patch) == (4, 0, 0)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            SemanticVersion("not-a-version")

    def test_str_roundtrip(self):
        assert str(SemanticVersion("1.2.3")) == "1.2.3"


# ---------------------------------------------------------------------------
# SemanticVersion — comparaisons
# ---------------------------------------------------------------------------

class TestSemanticVersionComparison:
    def test_major_wins(self):
        assert SemanticVersion("2.0.0") > SemanticVersion("1.9.9")

    def test_minor_wins(self):
        assert SemanticVersion("1.2.0") > SemanticVersion("1.1.9")

    def test_patch_wins(self):
        assert SemanticVersion("1.0.1") > SemanticVersion("1.0.0")

    def test_equal(self):
        assert SemanticVersion("1.2.3") == SemanticVersion("1.2.3")

    def test_prerelease_less_than_stable(self):
        assert SemanticVersion("1.0.0-beta") < SemanticVersion("1.0.0")

    def test_stable_greater_than_prerelease(self):
        assert SemanticVersion("1.0.0") > SemanticVersion("1.0.0-alpha")

    def test_prerelease_lexical(self):
        assert SemanticVersion("1.0.0-alpha") < SemanticVersion("1.0.0-beta")

    def test_le(self):
        assert SemanticVersion("1.0.0") <= SemanticVersion("1.0.0")
        assert SemanticVersion("0.9.0") <= SemanticVersion("1.0.0")

    def test_gt(self):
        assert SemanticVersion("1.1.0") > SemanticVersion("1.0.9")


# ---------------------------------------------------------------------------
# VersionChecker._compare
# ---------------------------------------------------------------------------

class TestVersionCheckerCompare:
    def _checker(self, current: str, tmp_path: Path) -> VersionChecker:
        return VersionChecker(
            current_version=current,
            cache_file=tmp_path / ".vc_cache.json",
        )

    def test_update_available(self, tmp_path):
        checker = self._checker("0.2.0", tmp_path)
        result = checker._compare("1.0.0", from_cache=False)
        assert result.update_available is True
        assert result.latest == "1.0.0"

    def test_no_update_same_version(self, tmp_path):
        checker = self._checker("1.0.0", tmp_path)
        result = checker._compare("1.0.0", from_cache=False)
        assert result.update_available is False

    def test_no_update_older_remote(self, tmp_path):
        checker = self._checker("2.0.0", tmp_path)
        result = checker._compare("1.9.9", from_cache=False)
        assert result.update_available is False

    def test_current_prerelease_update_to_stable(self, tmp_path):
        checker = self._checker("0.2.0-beta", tmp_path)
        result = checker._compare("0.2.0", from_cache=False)
        assert result.update_available is True

    def test_invalid_version_returns_error(self, tmp_path):
        checker = self._checker("notvalid", tmp_path)
        result = checker._compare("1.0.0", from_cache=False)
        assert result.error is not None
        assert result.update_available is False

    def test_from_cache_flag(self, tmp_path):
        checker = self._checker("1.0.0", tmp_path)
        result = checker._compare("2.0.0", from_cache=True)
        assert result.from_cache is True


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class TestVersionCheckerCache:
    def test_save_and_load_cache(self, tmp_path):
        checker = VersionChecker("1.0.0", cache_file=tmp_path / "cache.json")
        checker._save_cache("2.0.0")
        assert checker._load_cache() == "2.0.0"

    def test_expired_cache_returns_none(self, tmp_path):
        checker = VersionChecker("1.0.0", cache_file=tmp_path / "cache.json", cache_ttl=1)
        checker._save_cache("2.0.0")
        # Forcer l'expiration en écrivant un timestamp passé
        cache_data = {"latest_version": "2.0.0", "timestamp": time.time() - 10}
        (tmp_path / "cache.json").write_text(json.dumps(cache_data))
        assert checker._load_cache() is None

    def test_missing_cache_returns_none(self, tmp_path):
        checker = VersionChecker("1.0.0", cache_file=tmp_path / "nope.json")
        assert checker._load_cache() is None

    def test_corrupt_cache_returns_none(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        checker = VersionChecker("1.0.0", cache_file=f)
        assert checker._load_cache() is None

    def test_clear_cache(self, tmp_path):
        checker = VersionChecker("1.0.0", cache_file=tmp_path / "cache.json")
        checker._save_cache("2.0.0")
        checker.clear_cache()
        assert not (tmp_path / "cache.json").exists()


# ---------------------------------------------------------------------------
# VersionChecker.check — intégration avec mock réseau
# ---------------------------------------------------------------------------

class TestVersionCheckerCheck:
    def test_check_uses_cache_when_fresh(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        checker = VersionChecker("1.0.0", cache_file=cache_file)
        checker._save_cache("2.0.0")

        # _fetch_latest_version ne doit pas être appelé
        with patch.object(checker, "_fetch_latest_version") as mock_fetch:
            result = checker.check()
            mock_fetch.assert_not_called()

        assert result.from_cache is True
        assert result.update_available is True
        assert result.latest == "2.0.0"

    def test_check_fetches_when_no_cache(self, tmp_path):
        checker = VersionChecker("1.0.0", cache_file=tmp_path / "cache.json")

        with patch.object(checker, "_fetch_latest_version", return_value="1.5.0"):
            result = checker.check()

        assert result.from_cache is False
        assert result.update_available is True
        assert result.latest == "1.5.0"

    def test_check_saves_cache_after_fetch(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        checker = VersionChecker("1.0.0", cache_file=cache_file)

        with patch.object(checker, "_fetch_latest_version", return_value="2.0.0"):
            checker.check()

        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert data["latest_version"] == "2.0.0"

    def test_check_returns_gracefully_on_network_error(self, tmp_path):
        checker = VersionChecker("1.0.0", cache_file=tmp_path / "cache.json")

        with patch.object(checker, "_fetch_latest_version", side_effect=ConnectionError("timeout")):
            result = checker.check()

        assert result.update_available is False
        assert result.error is not None
        assert result.latest is None

    def test_check_no_update_when_up_to_date(self, tmp_path):
        checker = VersionChecker("3.0.0", cache_file=tmp_path / "cache.json")

        with patch.object(checker, "_fetch_latest_version", return_value="2.9.9"):
            result = checker.check()

        assert result.update_available is False
