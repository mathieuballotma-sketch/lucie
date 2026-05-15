#!/usr/bin/env python3
"""Mini-CLI manuelle pour tester le consent flow Beaume (Sprint K-8 step 0).

Pas d'interface utilisateur finale ici — juste un outil pour Mathieu (et les
contributeurs futurs) de vérifier les transitions à la main depuis le terminal.

Usage :
  python scripts/test_consent_flow.py --status
  python scripts/test_consent_flow.py --set standard
  python scripts/test_consent_flow.py --set pro_souverainete
  python scripts/test_consent_flow.py --clear
  python scripts/test_consent_flow.py --status --storage /tmp/consent.json

Exit 0 si OK, 1 si exception attrapée. Avec --debug, traceback complet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Permet d'exécuter le script sans installer le package (cohérent avec
# `scripts/legifrance_sync.py` et `scripts/build_kb_artifacts.py`).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lucie_v1_standalone.privacy.consent import (  # noqa: E402
    ConsentMode,
    ConsentStatus,
    clear_consent,
    get_consent_status,
    set_consent,
)
from lucie_v1_standalone.privacy.consent import (  # noqa: E402
    _resolve_storage_path,  # usage CLI dev pour afficher le path résolu
)

_MODE_LABELS = {
    ConsentMode.STANDARD: "Standard (sync activée)",
    ConsentMode.PRO_SOUVERAINETE: "Pro souveraineté (sync désactivée)",
}

_DT_FMT = "%Y-%m-%d %H:%M:%S %Z"


def _fmt_dt(dt) -> str:
    return dt.strftime(_DT_FMT) if dt is not None else "Jamais"


def _print_status(status: ConsentStatus, path: Path) -> None:
    consenti = "Consenti" if status.has_consented else "Pas encore consenti"
    sync = "OUI" if status.sync_enabled else "NON"
    mode_label = _MODE_LABELS[status.mode]

    lines = [
        "Consent Beaume",
        "──────────────",
        f"  Statut    : {consenti}",
        f"  Mode      : {mode_label}",
        f"  Sync KB   : {sync}",
        f"  Décidé le : {_fmt_dt(status.consent_date)}",
        f"  Modifié le: {_fmt_dt(status.last_modified)}",
        f"  Stockage  : {path}",
    ]
    print("\n".join(lines))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test manuel du consent flow Beaume (Sprint K-8 step 0).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--status", action="store_true", help="Affiche l'état actuel."
    )
    action.add_argument(
        "--set",
        dest="set_mode",
        choices=[m.value for m in ConsentMode],
        help="Applique un mode et affiche l'état résultant.",
    )
    action.add_argument(
        "--clear",
        action="store_true",
        help="Efface le consentement (re-prompt au prochain lancement).",
    )
    parser.add_argument(
        "--storage",
        type=Path,
        default=None,
        help="Chemin alternatif du fichier consent.json (utile en dev/tests).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Affiche le traceback complet en cas d'erreur.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    storage = args.storage
    resolved = _resolve_storage_path(storage)

    try:
        if args.status:
            _print_status(get_consent_status(storage), resolved)
        elif args.set_mode is not None:
            mode = ConsentMode(args.set_mode)
            status = set_consent(mode, storage)
            _print_status(status, resolved)
        elif args.clear:
            clear_consent(storage)
            print(f"Consent effacé ({resolved}).")
            _print_status(get_consent_status(storage), resolved)
    except Exception as err:
        if args.debug:
            raise
        print(f"Erreur: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
