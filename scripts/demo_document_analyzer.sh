#!/usr/bin/env bash
# Démo Sprint 7 — document_analyzer
#
# Génère 5 dossiers fictifs (lic_eco, lic_perso, sociétés, pharma, mixte),
# les passe dans `analyze_document()`, et imprime le DocumentAnalysisResult
# en JSON pour chaque dossier. 100% local, aucun appel réseau.
#
# Usage : bash scripts/demo_document_analyzer.sh

set -euo pipefail

# Worktree root (le script vit dans scripts/, root est le parent)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Le venv du repo a déjà reportlab + pdfplumber + python-docx
PYTHON_BIN="${PYTHON_BIN:-${HOME}/Desktop/mon-agence-ia/venv/bin/python}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "❌ Python introuvable : ${PYTHON_BIN}" >&2
    echo "   Configurer la variable PYTHON_BIN ou activer le venv." >&2
    exit 1
fi

"${PYTHON_BIN}" - <<'PYEOF'
import asyncio
import json
import sys
import tempfile
from pathlib import Path

# Le repo doit être dans le PYTHONPATH (cwd suffit normalement)
sys.path.insert(0, str(Path.cwd()))

from lucie_v1_standalone.document_analyzer import analyze_document
from lucie_v1_standalone.tests.test_document_analyzer.conftest import (
    FIXTURE_LIC_ECO_CADRE_PAGES,
    FIXTURE_LIC_PERSO_FAUTE,
    FIXTURE_SOCIETE_SARL_PAGES,
    FIXTURE_PHARMA_PUB_PAGES,
    FIXTURE_MIXTE_LIC_FISCAL_PARAGRAPHS,
    _write_pdf,
    _write_docx,
)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="beaume_demo_"))

    dossiers = []

    pdf1 = tmp / "1_dossier_licenciement_eco_cadre.pdf"
    _write_pdf(pdf1, FIXTURE_LIC_ECO_CADRE_PAGES)
    dossiers.append(("1. Licenciement économique (in-scope)", pdf1))

    docx2 = tmp / "2_dossier_licenciement_perso_faute.docx"
    _write_docx(docx2, FIXTURE_LIC_PERSO_FAUTE)
    dossiers.append(("2. Licenciement personnel / faute (in-scope)", docx2))

    pdf3 = tmp / "3_dossier_societe_SARL.pdf"
    _write_pdf(pdf3, FIXTURE_SOCIETE_SARL_PAGES)
    dossiers.append(("3. Cession parts SARL (out-of-scope)", pdf3))

    pdf4 = tmp / "4_dossier_pharma_pub.pdf"
    _write_pdf(pdf4, FIXTURE_PHARMA_PUB_PAGES)
    dossiers.append(("4. Publicité médicament (out-of-scope, pharma)", pdf4))

    docx5 = tmp / "5_dossier_mixte_lic_eco_fiscal.docx"
    _write_docx(docx5, FIXTURE_MIXTE_LIC_FISCAL_PARAGRAPHS)
    dossiers.append(("5. Mixte lic_eco + fiscal (refus partiel)", docx5))

    print("=" * 72)
    print("Beaume Sprint 7 — document_analyzer demo")
    print(f"Dossiers fictifs générés dans : {tmp}")
    print("=" * 72)
    print()

    for title, path in dossiers:
        print(f"── {title} " + "─" * (70 - len(title) - 4))
        print(f"   Fichier : {path.name}")
        result = asyncio.run(analyze_document(str(path)))
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        print()

    return 0


sys.exit(main())
PYEOF
