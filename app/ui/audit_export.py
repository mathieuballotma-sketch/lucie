"""
Helpers UI pour l'export PAF (Piste d'Audit Fiable) depuis le HUD.

L'API ``AuditTrail.export_paf_csv()`` est déjà production-ready (HMAC-SHA256
chain, RGPD/AI Act compliant). Ces helpers encapsulent la partie UI :
- chemin de la base d'audit utilisée par le HUD
- nom de fichier suggéré pour l'export
- wrapper d'export tolérant aux erreurs (renvoie (success, message))

Pure Python — facilite les tests sans NSSavePanel ni NSAlert.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Tuple


def default_audit_db_path() -> Path:
    """
    Chemin canonique de la base d'audit utilisée par le HUD.

    Note : différent de ``app/agents/lucie_v1/pipeline.py`` qui utilise sa
    propre DB. À harmoniser via service registry post-S3 (cf. plan).
    """
    return Path("data/audit/hud.db")


def default_export_filename(today: datetime.date | None = None) -> str:
    """
    Nom de fichier suggéré dans NSSavePanel.

    >>> default_export_filename(datetime.date(2026, 4, 28))
    'lucie_audit_2026-04-28.csv'
    """
    d = today or datetime.date.today()
    return f"lucie_audit_{d.isoformat()}.csv"


def export_to_path(audit_trail: Any, target_path: Path | str) -> Tuple[bool, str]:
    """
    Wrapper d'export : appelle ``audit_trail.export_paf_csv(output=target_path)``
    et renvoie ``(succès, message_utilisateur)``.

    Tolère les erreurs IO (permission, disque plein) en renvoyant un message
    intelligible, jamais une stacktrace nue.

    Returns:
        (True, "✓ Journal d'audit exporté vers <path>") en cas de succès
        (False, "✗ Erreur : <raison>") en cas d'échec
    """
    target = Path(target_path)
    try:
        audit_trail.export_paf_csv(output=target)
    except PermissionError as exc:
        return False, f"✗ Permission refusée pour {target.name} : {exc}"
    except OSError as exc:
        return False, f"✗ Erreur disque pour {target.name} : {exc}"
    except Exception as exc:
        return False, f"✗ Échec de l'export : {exc}"
    return True, f"✓ Journal d'audit exporté vers {target}"
