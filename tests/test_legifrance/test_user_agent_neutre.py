"""
Tests truth-rule : user-agent neutre côté DILA.

Beaume ne doit JAMAIS s'identifier en clair via un user-agent custom.
Ces tests sont un garde-fou : tout PR qui réintroduit une signature
identifiante doit échouer ici.

Voir mémoire project_privacy_sync_kb (2026-05-13).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from lucie_v1_standalone.knowledge_legifrance import downloader


REPO_ROOT = Path(__file__).resolve().parents[2]

# Variantes identifiantes interdites — liste exhaustive des signatures
# qui trahiraient Beaume côté DILA. Toute nouvelle variante doit être
# ajoutée ici si jamais elle apparaît dans une review.
IDENTIFYING_PATTERNS = (
    "Lucie-Legifrance-Sync",
    "Beaume-Legifrance-Sync",
    "Lucie-Sync",
    "Beaume-Sync",
    "local-lawyer-assistant",
)


def test_beaume_user_agent_existe_et_est_neutre():
    """La constante existe et ressemble à un Safari macOS standard."""
    ua = downloader.BEAUME_USER_AGENT
    assert ua.startswith("Mozilla/5.0")
    assert "Safari" in ua
    assert "Macintosh" in ua


def test_beaume_user_agent_ne_contient_aucune_signature_identifiante():
    """La constante elle-même ne doit pas mentionner Beaume/Lucie."""
    ua = downloader.BEAUME_USER_AGENT.lower()
    for pattern in IDENTIFYING_PATTERNS:
        assert pattern.lower() not in ua, (
            f"Signature identifiante '{pattern}' présente dans BEAUME_USER_AGENT"
        )
    # Garde supplémentaire : ni "beaume" ni "lucie" en clair dans le UA HTTP.
    assert "beaume" not in ua
    assert "lucie" not in ua


def test_aucun_fichier_repo_ne_contient_signature_identifiante():
    """
    Grep négatif sur tout le repo (hors .git, venv, ce fichier de tests
    qui DOIT lister les patterns interdits).

    Si ce test échoue, quelqu'un a réintroduit un user-agent identifiant
    quelque part dans le code suivi par git.
    """
    exclude_dirs = (".git", ".venv", "venv", "__pycache__", "node_modules")
    self_filename = Path(__file__).name

    for pattern in IDENTIFYING_PATTERNS:
        result = subprocess.run(
            ["git", "grep", "-l", pattern],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        # `git grep -l` exit code 1 = aucun match (cas nominal attendu),
        # exit code 0 = au moins un match (échec truth-rule).
        hits = [
            line
            for line in result.stdout.splitlines()
            if line
            and not any(part in exclude_dirs for part in Path(line).parts)
            and Path(line).name != self_filename
        ]
        assert hits == [], (
            f"Signature identifiante '{pattern}' encore présente dans : {hits}"
        )


def test_regression_user_agent_neutre_2026_05_13():
    """
    Régression : l'ancienne constante `USER_AGENT` ne doit plus exister
    et `BEAUME_USER_AGENT` doit être référencée dans les 2 callsites
    réseau (`list_remote_archives` et `download`).
    """
    # L'ancienne constante doit avoir disparu du module.
    assert not hasattr(downloader, "USER_AGENT"), (
        "Ancienne constante USER_AGENT toujours présente — renommage incomplet"
    )
    # La nouvelle doit être présente.
    assert hasattr(downloader, "BEAUME_USER_AGENT")

    # Vérifie que le code source des 2 fonctions réseau référence bien la
    # constante (≥ 3 occurrences = 1 définition + 2 callsites).
    src = Path(downloader.__file__).read_text(encoding="utf-8")
    assert src.count("BEAUME_USER_AGENT") >= 3, (
        "BEAUME_USER_AGENT doit être défini + référencé ≥ 2× "
        "(list_remote_archives, download)"
    )
