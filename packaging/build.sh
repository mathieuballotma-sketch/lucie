#!/usr/bin/env bash
#
# packaging/build.sh — build Beaume.app via py2app.
#
# Usage :
#   bash packaging/build.sh
#
# Idempotent : nettoie build/ et dist/ avant de builder.
# Produit : dist/Beaume.app (non signée — utiliser sign.sh ensuite).
#

set -euo pipefail

# Se placer à la racine du repo, quel que soit le répertoire d'appel.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "🔧 [build] racine repo : $REPO_ROOT"

# --- Prérequis outils ---

command -v python3 >/dev/null 2>&1 || {
    echo "❌ python3 introuvable. Installer Python 3.13 (brew install python@3.13)."
    exit 1
}

PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$PY_VERSION" != "3.13" ]]; then
    echo "⚠️  [build] python3 = $PY_VERSION (attendu 3.13)."
    echo "    py2app embarque l'interpréteur courant → le bundle ciblera $PY_VERSION."
    echo "    Pour un build production, relance avec : /opt/homebrew/bin/python3.13 …"
fi

# --- Lint du plist (fail early si XML cassé) ---

echo "🔍 [build] plutil -lint Info.plist"
plutil -lint packaging/Info.plist

# --- Nettoyage ---

echo "🧹 [build] clean build/ et dist/"
rm -rf build/ dist/

# --- py2app disponible ? ---

if ! python3 -c 'import py2app' 2>/dev/null; then
    echo "❌ py2app n'est pas installé dans ce Python."
    echo "   Installe : python3 -m pip install py2app"
    exit 1
fi

# --- Build ---

echo "📦 [build] py2app py2app (mode alias si DEV=1, sinon standalone)"
if [[ "${DEV:-0}" == "1" ]]; then
    # Mode alias : le .app pointe vers les sources Python du repo (itération rapide).
    python3 packaging/setup_py2app.py py2app -A
else
    python3 packaging/setup_py2app.py py2app
fi

# --- Vérification artefact ---

APP_PATH="dist/Beaume.app"
if [[ ! -d "$APP_PATH" ]]; then
    echo "❌ [build] $APP_PATH n'existe pas — le build a échoué silencieusement."
    exit 1
fi

BUNDLE_SIZE="$(du -sh "$APP_PATH" | cut -f1)"
echo "✅ [build] $APP_PATH produit ($BUNDLE_SIZE)"
echo "   Pour signer : bash packaging/sign.sh \"Developer ID Application: …\""
echo "   Pour tester : open $APP_PATH"
