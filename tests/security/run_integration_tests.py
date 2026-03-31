#!/usr/bin/env python3
"""
Script de lancement des tests d'intégration sécurité — Phase 6.

Lance les tests E2E du pipeline de sécurité Lucie avec un rapport détaillé.
Peut être exécuté directement ou via pytest.

Usage:
    python tests/security/run_integration_tests.py [options]
    python -m pytest tests/security/ -v [options]

Options transmises à pytest:
    --fast      : désactive les tests de performance mémoire (plus rapide en CI)
    --report    : génère un rapport HTML (nécessite pytest-html)
    -k EXPR     : filtre les tests par nom (ex: -k "xxe or macro")
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """
    Point d'entrée principal — délègue à pytest avec des options sensées.

    Returns:
        Exit code de pytest (0 = succès, 1+ = échecs).
    """
    args = argv or sys.argv[1:]

    # Racine du projet (deux niveaux au-dessus de ce script)
    project_root = Path(__file__).parent.parent.parent
    test_dir     = Path(__file__).parent

    pytest_args = [
        sys.executable,
        "-m", "pytest",
        str(test_dir),
        "--tb=short",          # tracebacks concis
        "-v",                  # verbose : affiche chaque test
        "--no-header",
        "-rN",                 # résumé : N = pas de warnings parasites
    ]

    # Prise en charge de --fast : skip les tests de mémoire lents
    if "--fast" in args:
        args.remove("--fast")
        pytest_args.extend(["-k", "not memory"])
        print("⚡ Mode rapide activé : tests mémoire exclus\n")

    # Rapport HTML optionnel
    if "--report" in args:
        args.remove("--report")
        report_path = project_root / "reports" / "security_tests.html"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        pytest_args.extend([
            "--html", str(report_path),
            "--self-contained-html",
        ])
        print(f"📄 Rapport HTML : {report_path}\n")

    # Passer tous les arguments restants directement à pytest
    pytest_args.extend(args)

    # Affichage du contexte
    print("=" * 60)
    print("  Tests sécurité Lucie — Phase 6")
    print(f"  Répertoire : {test_dir}")
    print(f"  Python     : {sys.version.split()[0]}")
    print("=" * 60)
    print()

    result = subprocess.run(pytest_args, cwd=str(project_root))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
