"""
Downloader des archives DILA LEGI.

Source : https://echanges.dila.gouv.fr/OPENDATA/LEGI/

Deux types d'archives :
- `Freemium_legi_global_YYYYMMDD-HHMMSS.tar.gz` : dump full (~1.1 GB).
- `LEGI_YYYYMMDD-HHMMSS.tar.gz`                 : incrémentaux quotidiens
  (300 KB – 42 MB, publiés 20h-23h).

Stdlib uniquement — pas de deps externes. Parse HTML via `html.parser`.

Contrat public :
- `list_remote_archives()`  → liste des archives disponibles côté DILA.
- `download(archive, dest)` → télécharge, calcule SHA256, renvoie Path.
- `CorruptedArchiveError`   → levée si checksum attendu ≠ checksum calculé.
"""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Literal

logger = logging.getLogger(__name__)


DILA_BASE_URL = "https://echanges.dila.gouv.fr/OPENDATA/LEGI/"
USER_AGENT = "Lucie-Legifrance-Sync/1.0 (+local-lawyer-assistant)"
DEFAULT_TIMEOUT_SEC = 60
CHUNK_SIZE = 1 << 20  # 1 MiB

_ARCHIVE_RE = re.compile(
    r"^(?P<kind>Freemium_legi_global|LEGI)_"
    r"(?P<date>\d{8})-(?P<time>\d{6})\.tar\.gz$"
)


class CorruptedArchiveError(RuntimeError):
    """Checksum SHA256 calculé ≠ checksum attendu."""


class DownloadError(RuntimeError):
    """Échec réseau ou HTTP non-200."""


@dataclass(frozen=True)
class RemoteArchive:
    """Un .tar.gz publié sur l'index DILA."""

    name: str
    kind: Literal["full", "incremental"]
    timestamp: datetime  # parsé depuis le nom du fichier (UTC approximé)
    url: str

    @property
    def is_full(self) -> bool:
        return self.kind == "full"


class _IndexParser(HTMLParser):
    """Extrait les liens `.tar.gz` d'un index HTML Apache (DILA)."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value and value.endswith(".tar.gz"):
                self.hrefs.append(value)


def _parse_archive_name(name: str, base_url: str = DILA_BASE_URL) -> RemoteArchive | None:
    """Parse `LEGI_20260420-211500.tar.gz` → `RemoteArchive` ou None."""
    match = _ARCHIVE_RE.match(name)
    if match is None:
        return None
    date_str = match.group("date")
    time_str = match.group("time")
    try:
        ts = datetime.strptime(date_str + time_str, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    kind: Literal["full", "incremental"] = (
        "full" if match.group("kind") == "Freemium_legi_global" else "incremental"
    )
    return RemoteArchive(
        name=name,
        kind=kind,
        timestamp=ts,
        url=base_url.rstrip("/") + "/" + name,
    )


def list_remote_archives(
    base_url: str = DILA_BASE_URL,
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> list[RemoteArchive]:
    """
    Liste les archives `.tar.gz` publiées sur l'index DILA.

    Retourne une liste triée par timestamp croissant (plus ancien d'abord).
    Les archives au nom non conforme sont ignorées silencieusement.
    """
    req = urllib.request.Request(base_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise DownloadError(
                    f"HTTP {resp.status} sur l'index DILA {base_url}"
                )
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DownloadError(f"Impossible de lire l'index DILA {base_url}: {exc}") from exc

    return parse_index_html(html, base_url=base_url)


def parse_index_html(html: str, base_url: str = DILA_BASE_URL) -> list[RemoteArchive]:
    """Parse la page HTML de l'index DILA → liste d'archives.

    Exposée pour les tests (on injecte du HTML captif sans réseau).
    """
    parser = _IndexParser()
    parser.feed(html)
    archives: list[RemoteArchive] = []
    for href in parser.hrefs:
        name = href.rsplit("/", 1)[-1]
        archive = _parse_archive_name(name, base_url=base_url)
        if archive is not None:
            archives.append(archive)
    archives.sort(key=lambda a: a.timestamp)
    return archives


def compute_sha256(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    """Hash SHA256 hex du fichier, lu par blocs."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def download(
    archive: RemoteArchive,
    dest_dir: Path,
    expected_sha256: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SEC,
    force: bool = False,
) -> Path:
    """
    Télécharge `archive` dans `dest_dir`. Idempotent : si le fichier existe
    déjà avec le bon checksum, ne re-télécharge pas.

    - `expected_sha256` : si fourni, vérifie le hash et lève `CorruptedArchiveError`
      en cas de mismatch.
    - `force`           : re-télécharge même si le fichier existe.

    Retourne le chemin local du fichier téléchargé.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / archive.name

    if dest.exists() and not force:
        if expected_sha256:
            actual = compute_sha256(dest)
            if actual == expected_sha256:
                logger.info("archive déjà présente (checksum OK): %s", archive.name)
                return dest
            logger.warning(
                "archive présente mais checksum mismatch, re-téléchargement: %s",
                archive.name,
            )
        else:
            logger.info("archive déjà présente: %s (skip, pas de checksum attendu)", archive.name)
            return dest

    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(archive.url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as out:
            if resp.status != 200:
                raise DownloadError(f"HTTP {resp.status} sur {archive.url}")
            while True:
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)
    except (urllib.error.URLError, TimeoutError) as exc:
        if tmp.exists():
            tmp.unlink()
        raise DownloadError(f"Échec téléchargement {archive.url}: {exc}") from exc

    if expected_sha256:
        actual = compute_sha256(tmp)
        if actual != expected_sha256:
            tmp.unlink()
            raise CorruptedArchiveError(
                f"SHA256 mismatch pour {archive.name}: "
                f"attendu={expected_sha256}, calculé={actual}"
            )

    tmp.replace(dest)
    logger.info("téléchargé %s (%d octets)", archive.name, dest.stat().st_size)
    return dest


def filter_since(
    archives: Iterable[RemoteArchive],
    since: datetime | None,
) -> list[RemoteArchive]:
    """Ne garde que les archives strictement plus récentes que `since`.

    Si `since` est None, renvoie toutes les archives (first-run).
    """
    if since is None:
        return list(archives)
    return [a for a in archives if a.timestamp > since]


def select_sync_plan(
    archives: Iterable[RemoteArchive],
    last_sync: datetime | None,
) -> list[RemoteArchive]:
    """
    Construit le plan de sync chronologique.

    - Premier run (`last_sync=None`)  : on prend le dernier full + tous les
      incrémentaux postérieurs à ce full.
    - Run incrémental                 : tous les fichiers > `last_sync`.

    Ordre chronologique croissant (on applique dans l'ordre d'émission DILA).
    """
    ordered = sorted(archives, key=lambda a: a.timestamp)

    if last_sync is None:
        fulls = [a for a in ordered if a.is_full]
        if not fulls:
            # Pas de full dispo ? Pas de sync initial possible.
            return []
        latest_full = fulls[-1]
        return [latest_full] + [
            a for a in ordered if a.timestamp > latest_full.timestamp
        ]

    return [a for a in ordered if a.timestamp > last_sync]
