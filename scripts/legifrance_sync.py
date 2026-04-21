#!/usr/bin/env python3
"""
CLI manuelle pour le sync Légifrance.

Exemples :
    # Premier run (télécharge le dernier full + incrémentaux postérieurs)
    python scripts/legifrance_sync.py --first-run

    # Sync incrémental (défaut)
    python scripts/legifrance_sync.py --incremental

    # Dry-run : liste ce qui serait téléchargé, sans écrire
    python scripts/legifrance_sync.py --dry-run

    # Mode sample offline : applique un tarball local (tests / dev)
    python scripts/legifrance_sync.py --sample tests/test_legifrance/fixtures/LEGI_sample_20260418.tar.gz

    # Vérifier la fraîcheur du dernier sync
    python scripts/legifrance_sync.py --status
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Permet d'exécuter le script sans installer le package.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lucie_v1_standalone.knowledge_legifrance.sync import (  # noqa: E402
    legifrance_freshness,
    run_sync,
)
from lucie_v1_standalone.knowledge_legifrance.downloader import (  # noqa: E402
    CorruptedArchiveError,
    DownloadError,
)
from lucie_v1_standalone.knowledge_legifrance.parser import ParseError  # noqa: E402


def _get_data_dir(override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    try:
        from lucie_v1_standalone.config import get_legifrance_db_path

        return get_legifrance_db_path().parent
    except (ImportError, AttributeError):
        default = Path.home() / "Library/Application Support/Lucie/legifrance"
        return default


def _build_audit_trail(enable: bool) -> object | None:
    if not enable:
        return None
    try:
        from app.services.audit_trail import AuditTrail

        return AuditTrail()
    except Exception as exc:  # noqa: BLE001 — audit optionnel
        logging.warning("AuditTrail indisponible (%s), sync continuera sans audit", exc)
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync Légifrance (dump DILA LEGI) → base locale Lucie."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--first-run", action="store_true",
                      help="Premier sync : full + incrémentaux postérieurs")
    mode.add_argument("--incremental", action="store_true",
                      help="Sync incrémental (défaut)")
    mode.add_argument("--status", action="store_true",
                      help="Affiche la fraîcheur du dernier sync et sort")

    parser.add_argument("--sample", nargs="+", metavar="TARBALL",
                        help="Applique un/des tarball(s) locaux (bypass download)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Ne rien écrire ; liste les archives sélectionnées")
    parser.add_argument("--force", action="store_true",
                        help="Re-télécharge les tarballs déjà présents")
    parser.add_argument("--data-dir", default=None,
                        help="Répertoire de travail (défaut : ~/Library/Application Support/Lucie/legifrance)")
    parser.add_argument("--no-audit", action="store_true",
                        help="Désactive l'écriture de l'entrée AuditTrail")
    parser.add_argument("--user", default="system",
                        help="Valeur du champ `user` de l'AuditTrail (défaut: system)")
    parser.add_argument("--verbose", "-v", action="count", default=0,
                        help="Niveau de log (-v info, -vv debug)")
    args = parser.parse_args(argv)

    level = logging.WARNING if args.verbose == 0 else (
        logging.INFO if args.verbose == 1 else logging.DEBUG
    )
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    data_dir = _get_data_dir(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    if args.status:
        info = legifrance_freshness(data_dir)
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0

    sample = [Path(p).expanduser().resolve() for p in (args.sample or [])]
    audit_trail = _build_audit_trail(enable=not args.no_audit)

    try:
        result = run_sync(
            data_dir=data_dir,
            first_run=args.first_run,
            dry_run=args.dry_run,
            force=args.force,
            sample_archives=sample or None,
            user=args.user,
            audit_trail=audit_trail,
        )
    except KeyboardInterrupt:
        print("[abandon utilisateur]", file=sys.stderr)
        return 130
    except DownloadError as exc:
        print(f"ERREUR réseau Légifrance : {exc}", file=sys.stderr)
        print(
            "Si le problème vient d'un certificat SSL : sur macOS Python.org, "
            "lancer `/Applications/Python\\ 3.13/Install\\ Certificates.command`. "
            "Sinon utiliser `--sample <tarball.tar.gz>` pour bypass le réseau.",
            file=sys.stderr,
        )
        return 2
    except CorruptedArchiveError as exc:
        print(f"ERREUR archive corrompue : {exc}", file=sys.stderr)
        print("Relancer avec --force pour re-télécharger.", file=sys.stderr)
        return 3
    except ParseError as exc:
        print(f"ERREUR parsing XML Légifrance : {exc}", file=sys.stderr)
        return 4

    summary = result.to_dict()
    # N'affiche pas le gros audit_summary en stdout pour garder le log lisible
    summary.pop("audit_summary", None)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
