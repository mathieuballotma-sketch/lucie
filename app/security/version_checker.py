"""
SEC-QW-03 : Vérification de version au démarrage.

Interroge l'API GitHub pour récupérer le dernier tag du dépôt,
compare sémantiquement avec la version courante et notifie (sans bloquer)
si une mise à jour est disponible. Le résultat est mis en cache 24 h.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

# Cache stocké dans le même répertoire que le module
_DEFAULT_CACHE_FILE = Path(__file__).parent / ".version_check_cache.json"
_CACHE_TTL_SECONDS = 86_400  # 24 h

# Repo GitHub du projet
_GITHUB_REPO = "mathieubellot/lucie-agent"  # à adapter si besoin
_GITHUB_API_URL = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"
_GITHUB_TAGS_URL = f"https://api.github.com/repos/{_GITHUB_REPO}/tags"

# Timeout de la requête HTTP (secondes)
_HTTP_TIMEOUT = 5


@dataclass
class VersionCheckResult:
    """Résultat d'un check de version."""
    current: str
    latest: Optional[str]
    update_available: bool
    from_cache: bool
    error: Optional[str] = None


class SemanticVersion:
    """Parse et compare des versions sémantiques (X.Y.Z[-prerelease])."""

    _RE = re.compile(
        r"^v?(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?(?:-(?P<pre>.+))?$"
    )

    def __init__(self, version_str: str) -> None:
        m = self._RE.match(version_str.strip())
        if not m:
            raise ValueError(f"Version non reconnue : {version_str!r}")
        self.major = int(m.group("major"))
        self.minor = int(m.group("minor"))
        self.patch = int(m.group("patch") or 0)
        self.pre: Optional[str] = m.group("pre")
        self.raw = version_str

    def __lt__(self, other: "SemanticVersion") -> bool:
        if (self.major, self.minor, self.patch) != (other.major, other.minor, other.patch):
            return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)
        # Prérelease < stable
        if self.pre and not other.pre:
            return True
        if not self.pre and other.pre:
            return False
        # Les deux en prérelease : comparaison lexicale
        if self.pre and other.pre:
            return self.pre < other.pre
        return False

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        return (self.major, self.minor, self.patch, self.pre) == (
            other.major, other.minor, other.patch, other.pre
        )

    def __le__(self, other: "SemanticVersion") -> bool:
        return self == other or self < other

    def __gt__(self, other: "SemanticVersion") -> bool:
        return not self <= other

    def __repr__(self) -> str:
        return f"SemanticVersion({self.raw!r})"

    def __str__(self) -> str:
        return self.raw


class VersionChecker:
    """
    Vérifie si une nouvelle version est disponible sur GitHub.

    Utilisation ::

        checker = VersionChecker(current_version="0.2.0-beta")
        result = checker.check()
        if result.update_available:
            print(f"Mise à jour disponible : {result.latest}")
    """

    def __init__(
        self,
        current_version: str,
        github_api_url: str = _GITHUB_API_URL,
        github_tags_url: str = _GITHUB_TAGS_URL,
        cache_file: Optional[Path] = None,
        cache_ttl: int = _CACHE_TTL_SECONDS,
    ) -> None:
        self.current_version = current_version
        self.github_api_url = github_api_url
        self.github_tags_url = github_tags_url
        self.cache_file = Path(cache_file) if cache_file else _DEFAULT_CACHE_FILE
        self.cache_ttl = cache_ttl

    # ------------------------------------------------------------------
    # Point d'entrée principal
    # ------------------------------------------------------------------

    def check(self) -> VersionCheckResult:
        """
        Vérifie si une mise à jour est disponible (non-bloquant).

        Retourne toujours un VersionCheckResult, même en cas d'erreur.
        """
        # 1. Vérifier le cache
        cached = self._load_cache()
        if cached is not None:
            latest_str = cached
            return self._compare(latest_str, from_cache=True)

        # 2. Interroger GitHub
        try:
            latest_str = self._fetch_latest_version()
        except Exception as exc:
            logger.debug("[VersionChecker] Impossible de vérifier la version : %s", exc)
            return VersionCheckResult(
                current=self.current_version,
                latest=None,
                update_available=False,
                from_cache=False,
                error=str(exc),
            )

        # 3. Mettre en cache et comparer
        self._save_cache(latest_str)
        return self._compare(latest_str, from_cache=False)

    # ------------------------------------------------------------------
    # Comparaison
    # ------------------------------------------------------------------

    def _compare(self, latest_str: str, from_cache: bool) -> VersionCheckResult:
        try:
            current = SemanticVersion(self.current_version)
            latest = SemanticVersion(latest_str)
            update_available = latest > current
        except ValueError as exc:
            return VersionCheckResult(
                current=self.current_version,
                latest=latest_str,
                update_available=False,
                from_cache=from_cache,
                error=str(exc),
            )

        if update_available:
            logger.info(
                "[VersionChecker] Mise à jour disponible : %s → %s",
                self.current_version, latest_str,
            )
        else:
            logger.debug("[VersionChecker] Version à jour (%s).", self.current_version)

        return VersionCheckResult(
            current=self.current_version,
            latest=latest_str,
            update_available=update_available,
            from_cache=from_cache,
        )

    # ------------------------------------------------------------------
    # Requête GitHub
    # ------------------------------------------------------------------

    def _fetch_latest_version(self) -> str:
        """
        Tente d'abord /releases/latest, puis /tags si nécessaire.

        Retourne la chaîne de version du dernier release/tag.
        """
        # Essai 1 : endpoint releases/latest
        try:
            version = self._get_release_version(self.github_api_url)
            return version
        except HTTPError as exc:
            if exc.code != 404:
                raise
            logger.debug("[VersionChecker] Pas de releases — repli sur les tags.")

        # Essai 2 : premier tag
        return self._get_tag_version(self.github_tags_url)

    def _get_release_version(self, url: str) -> str:
        data = self._http_get_json(url)
        tag = data.get("tag_name", "")
        if not tag:
            raise ValueError("tag_name absent de la réponse GitHub releases")
        return tag

    def _get_tag_version(self, url: str) -> str:
        data = self._http_get_json(url)
        if not isinstance(data, list) or not data:
            raise ValueError("Aucun tag trouvé sur GitHub")
        return data[0].get("name", "")

    def _http_get_json(self, url: str) -> dict | list:
        req = Request(url, headers={"User-Agent": "lucie-agent/version-checker"})
        with urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _load_cache(self) -> Optional[str]:
        """Retourne la version en cache si elle est encore valide."""
        if not self.cache_file.exists():
            return None
        try:
            with open(self.cache_file, encoding="utf-8") as fh:
                data = json.load(fh)
            ts = data.get("timestamp", 0)
            if time.time() - ts < self.cache_ttl:
                return data.get("latest_version")
        except (json.JSONDecodeError, OSError, KeyError):
            pass
        return None

    def _save_cache(self, latest_version: str) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            data = {"latest_version": latest_version, "timestamp": time.time()}
            with open(self.cache_file, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
        except OSError as exc:
            logger.debug("[VersionChecker] Impossible d'écrire le cache : %s", exc)

    def clear_cache(self) -> None:
        """Supprime le cache (utile pour les tests)."""
        if self.cache_file.exists():
            self.cache_file.unlink()
