#!/usr/bin/env bash
#
# packaging/release.sh — orchestrateur build → sign → notarize → DMG.
#
# Usage :
#   # Build local uniquement (pas de creds Apple) :
#   bash packaging/release.sh
#
#   # Release complète (DMG signé + notarizé) :
#   export DEVELOPER_ID="Developer ID Application: NOM (TEAMID)"
#   export APPLE_ID="mathieu.ballotma@gmail.com"
#   export APPLE_TEAM_ID="XXXXXXXXXX"
#   export APPLE_APP_PWD="xxxx-xxxx-xxxx-xxxx"
#   bash packaging/release.sh
#
# Chaque étape saute automatiquement si ses prérequis ne sont pas réunis,
# avec un message explicite — pas d'échec obscur.
#
# Idempotent : relançable sans casser un build précédent.
#

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "════════════════════════════════════════════════"
echo "  Lucie — release pipeline"
echo "  repo : $REPO_ROOT"
echo "════════════════════════════════════════════════"

# --- Étape 1 : BUILD ---

echo ""
echo "──── [1/4] BUILD ────"
bash packaging/build.sh

# --- Étape 2 : SIGN ---

echo ""
echo "──── [2/4] SIGN ────"
if [[ -n "${DEVELOPER_ID:-}" ]]; then
    bash packaging/sign.sh
else
    echo "⚠️  DEVELOPER_ID non défini → sign skippée."
    echo "   Pour signer : export DEVELOPER_ID=\"Developer ID Application: …\""
    echo "   Prérequis : Apple Developer Program actif + certif dans Keychain."
fi

# --- Étape 3 : NOTARIZE ---

echo ""
echo "──── [3/4] NOTARIZE ────"
if [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_PWD:-}" ]]; then
    # On ne peut notariser que si l'app est signée.
    if codesign --verify --verbose=1 dist/Lucie.app 2>/dev/null; then
        bash packaging/notarize.sh
    else
        echo "⚠️  Lucie.app non signée → notarize impossible."
    fi
else
    echo "⚠️  APPLE_ID / APPLE_TEAM_ID / APPLE_APP_PWD non définis → notarize skippée."
    echo "   Prérequis : app-specific password sur https://appleid.apple.com"
fi

# --- Étape 4 : DMG ---

echo ""
echo "──── [4/4] DMG ────"
if codesign --verify --verbose=1 dist/Lucie.app 2>/dev/null; then
    bash packaging/make_dmg.sh
else
    echo "⚠️  Lucie.app non signée → DMG skippé (FORCE_UNSIGNED=1 pour override)."
fi

# --- Bilan ---

echo ""
echo "════════════════════════════════════════════════"
echo "  Bilan release"
echo "════════════════════════════════════════════════"
[[ -d dist/Lucie.app ]] && echo "✅ dist/Lucie.app : $(du -sh dist/Lucie.app | cut -f1)"
[[ -f dist/Lucie.dmg ]] && echo "✅ dist/Lucie.dmg : $(du -sh dist/Lucie.dmg | cut -f1)"
echo ""
echo "Prochaine étape :"
if [[ -f dist/Lucie.dmg ]]; then
    echo "  Distribuer dist/Lucie.dmg aux avocats pilotes."
else
    echo "  Configurer les creds Apple (cf. packaging/README.md) puis relancer."
fi
