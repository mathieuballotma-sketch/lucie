"""
Orchestrateur de sync Légifrance.

Pipeline :
  1. (optionnel) list_remote_archives() → sélectionne les tarballs à appliquer
  2. download() chacun avec SHA256 (si fourni)
  3. apply_archive() + apply_suppression_list() sur la DB
  4. reindex_themes() pour matérialiser articles_by_theme
  5. compute_diff() vs snapshot précédent
  6. record_sync() dans l'AuditTrail (HMAC chaîné)
  7. met à jour last_sync.json

Sans dépendance au reste du pipeline Lucie — se suffit à lui-même pour
être lançable via `scripts/legifrance_sync.py` ou via launchd.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .diff import SyncDiff, compute_diff
from .downloader import (
    RemoteArchive,
    compute_sha256,
    download,
    list_remote_archives,
    select_sync_plan,
)
from .indexer import load_theme_mapping, reindex_themes
from .parser import apply_archive, apply_suppression_list, init_db

logger = logging.getLogger(__name__)

LAST_SYNC_FILENAME = "last_sync.json"
TARBALLS_SUBDIR = "tarballs"
DEFAULT_TARBALL_RETENTION_DAYS = 7


@dataclass
class SyncResult:
    started_at: str
    finished_at: str
    duration_sec: float
    archives_applied: list[str]
    articles_added: int = 0
    articles_updated: int = 0
    articles_deleted: int = 0
    abrogated: int = 0
    db_sha256: str = ""
    theme_counts: dict[str, int] = field(default_factory=dict)
    parse_errors: int = 0
    audit_summary: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_last_sync(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("last_sync.json illisible (%s), on ignore", exc)
        return None


def _write_last_sync(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _snapshot_db(db_path: Path) -> Path | None:
    """Copie temporaire de la DB pour comparaison diff (before vs after)."""
    if not db_path.exists():
        return None
    tmp = Path(tempfile.mkdtemp(prefix="legi_snapshot_")) / "before.sqlite"
    shutil.copy2(db_path, tmp)
    return tmp


def _parse_since_timestamp(last: dict[str, Any] | None) -> datetime | None:
    if not last:
        return None
    archives = last.get("archives") or []
    if not archives:
        return None
    # `archives` est la liste des noms appliqués ; on prend le plus récent par
    # nom — les noms DILA embarquent le timestamp.
    from .downloader import _parse_archive_name

    parsed = [
        _parse_archive_name(name)
        for name in archives
    ]
    timestamps = [p.timestamp for p in parsed if p is not None]
    if not timestamps:
        return None
    return max(timestamps)


def run_sync(
    data_dir: Path,
    *,
    first_run: bool = False,
    dry_run: bool = False,
    force: bool = False,
    sample_archives: list[Path] | None = None,
    user: str = "system",
    audit_trail: Any | None = None,
    list_archives_fn: Callable[[], list[RemoteArchive]] = list_remote_archives,
) -> SyncResult:
    """
    Exécute un sync complet.

    - `data_dir`         : répertoire racine (contient `legi.sqlite` + `tarballs/`).
    - `first_run`        : si True, on prend le dernier full + incrémentaux postérieurs.
    - `dry_run`          : simule (pas d'écriture DB, pas d'audit).
    - `force`            : re-télécharge les tarballs déjà présents.
    - `sample_archives`  : liste de chemins locaux de tarballs (court-circuite
                           la partie download — utile pour fixtures / offline).
    - `audit_trail`      : instance `AuditTrail` ou None (pas d'audit).
    - `list_archives_fn` : injecté pour tests (stubber list_remote_archives).
    """
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()

    db_path = data_dir / "legi.sqlite"
    last_sync_path = data_dir / LAST_SYNC_FILENAME
    tarballs_dir = data_dir / TARBALLS_SUBDIR

    # 1. Déterminer le plan
    applied_names: list[str] = []
    to_apply: list[Path] = []

    if sample_archives:
        to_apply = [Path(p) for p in sample_archives]
        applied_names = [p.name for p in to_apply]
        logger.info("mode sample : %d archive(s) locale(s) utilisée(s)", len(to_apply))
    else:
        last = _load_last_sync(last_sync_path)
        since = None if first_run else _parse_since_timestamp(last)
        remote = list_archives_fn()
        plan = select_sync_plan(remote, since if not first_run else None)
        if first_run:
            # Redondance : select_sync_plan(None) prend déjà le dernier full
            pass
        logger.info("sync plan : %d archive(s) à appliquer", len(plan))
        for archive in plan:
            local = download(archive, tarballs_dir, force=force)
            to_apply.append(local)
            applied_names.append(archive.name)

    if dry_run:
        logger.info("dry-run : %d archives sélectionnées, abandon avant écriture", len(to_apply))
        finished_at = datetime.now(timezone.utc).isoformat()
        return SyncResult(
            started_at=started_at,
            finished_at=finished_at,
            duration_sec=time.monotonic() - t0,
            archives_applied=applied_names,
        )

    # 2. Snapshot pré-sync pour diff
    before_snapshot = _snapshot_db(db_path)
    conn_before = (
        sqlite3.connect(before_snapshot) if before_snapshot else None
    )

    # 3. Apply archives
    conn = init_db(db_path)
    try:
        articles_added = 0
        articles_updated = 0
        articles_deleted = 0
        parse_errors = 0
        for tarball in to_apply:
            stats = apply_archive(tarball, conn)
            articles_added += stats.articles_added
            articles_updated += stats.articles_updated
            parse_errors += stats.parse_errors
            articles_deleted += apply_suppression_list(tarball, conn)

        # 4. Reindex themes
        mapping = load_theme_mapping()
        theme_counts = reindex_themes(conn, mapping=mapping)

        # 5. Diff
        diff = compute_diff(conn_before, conn)
        abrogated = len(diff.abrogated)
        audit_summary = diff.summary_lines()
    finally:
        conn.close()
        if conn_before is not None:
            conn_before.close()
            if before_snapshot and before_snapshot.parent.exists():
                shutil.rmtree(before_snapshot.parent, ignore_errors=True)

    # 6. Checksum final
    db_sha = compute_sha256(db_path)

    # 7. Enregistrer last_sync + audit
    finished_at = datetime.now(timezone.utc).isoformat()
    duration = time.monotonic() - t0
    result = SyncResult(
        started_at=started_at,
        finished_at=finished_at,
        duration_sec=round(duration, 3),
        archives_applied=applied_names,
        articles_added=articles_added,
        articles_updated=articles_updated,
        articles_deleted=articles_deleted,
        abrogated=abrogated,
        db_sha256=db_sha,
        theme_counts=theme_counts,
        parse_errors=parse_errors,
        audit_summary=audit_summary,
    )

    _write_last_sync(last_sync_path, {
        "timestamp": finished_at,
        "archives": applied_names,
        "db_sha256": db_sha,
        "articles_added": articles_added,
        "articles_updated": articles_updated,
        "articles_deleted": articles_deleted,
        "abrogated": abrogated,
        "theme_counts": theme_counts,
        "theme_mapping_version": mapping.get("version"),
    })

    if audit_trail is not None:
        try:
            audit_trail.record_sync(
                action="legifrance_sync",
                user=user,
                justification=(
                    f"Sync Légifrance : {len(applied_names)} archive(s), "
                    f"+{articles_added} -{articles_deleted} ~{articles_updated}"
                ),
                data={
                    "archives": applied_names,
                    "articles_added": articles_added,
                    "articles_updated": articles_updated,
                    "articles_deleted": articles_deleted,
                    "abrogated": abrogated,
                    "theme_counts": theme_counts,
                    "db_sha256": db_sha,
                    "duration_sec": result.duration_sec,
                    "diff_preview": audit_summary[: 50],
                },
            )
        except Exception as exc:  # noqa: BLE001 — audit ne doit pas casser le sync
            logger.warning("audit trail indisponible : %s", exc)

    return result


def legifrance_freshness(data_dir: Path, warn_after_days: int = 7) -> dict[str, Any]:
    """
    Helper HUD : renvoie un niveau et la date du dernier sync.

    Retour :
        {"level": "ok"|"warning"|"missing", "last_sync": iso|None, "age_days": int|None}
    """
    last_path = data_dir / LAST_SYNC_FILENAME
    last = _load_last_sync(last_path)
    if not last:
        return {"level": "missing", "last_sync": None, "age_days": None}
    ts_raw = last.get("timestamp")
    if not ts_raw:
        return {"level": "missing", "last_sync": None, "age_days": None}
    try:
        ts = datetime.fromisoformat(ts_raw)
    except ValueError:
        return {"level": "missing", "last_sync": ts_raw, "age_days": None}
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - ts
    age_days = age.days
    level = "warning" if age_days > warn_after_days else "ok"
    return {"level": level, "last_sync": ts_raw, "age_days": age_days}
