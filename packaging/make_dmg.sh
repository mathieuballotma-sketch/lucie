#!/usr/bin/env bash
#
# packaging/make_dmg.sh — crée un DMG signé + notarizé contenant Beaume.app.
#
# Usage :
#   bash packaging/make_dmg.sh
#
# Lit DEVELOPER_ID, APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PWD depuis l'env.
#
# Produit : dist/Beaume.dmg (glissable dans /Applications par l'utilisateur).
#
# Idempotent : écrase le DMG précédent.
#

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

APP="dist/Beaume.app"
DMG="dist/Beaume.dmg"
VOL_NAME="Beaume"
STAGING_DIR="dist/dmg_staging"

# --- Vérifications préalables ---

if [[ ! -d "$APP" ]]; then
    echo "❌ $APP introuvable — lance d'abord : bash packaging/build.sh"
    exit 1
fi

if ! codesign --verify --verbose=1 "$APP" 2>/dev/null; then
    echo "⚠️  [dmg] $APP n'est pas signée — le DMG sera inutilisable en prod."
    echo "    Lance sign.sh puis notarize.sh avant si tu veux un livrable."
    if [[ "${FORCE_UNSIGNED:-0}" != "1" ]]; then
        echo "    Pour continuer quand même : FORCE_UNSIGNED=1 bash packaging/make_dmg.sh"
        exit 1
    fi
fi

# --- Préparation staging ---

echo "🧹 [dmg] nettoyage staging"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

echo "📂 [dmg] copie $APP → staging"
cp -R "$APP" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

# --- Création DMG ---

echo "💿 [dmg] création $DMG"
rm -f "$DMG"
hdiutil create \
    -volname "$VOL_NAME" \
    -srcfolder "$STAGING_DIR" \
    -ov \
    -format UDZO \
    -fs HFS+ \
    "$DMG"

rm -rf "$STAGING_DIR"

# --- Signature du DMG ---

DEV_ID="${DEVELOPER_ID:-}"
if [[ -n "$DEV_ID" ]]; then
    echo "🔐 [dmg] codesign du DMG"
    codesign --force --sign "$DEV_ID" --timestamp "$DMG"
    codesign --verify --verbose=2 "$DMG"
else
    echo "⚠️  [dmg] DEVELOPER_ID non défini → DMG non signé"
    echo "    Acceptable pour test local, refusé en distribution."
fi

# --- Notarization du DMG (optionnel si creds dispo) ---

if [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_PWD:-}" ]]; then
    echo "☁️  [dmg] notarization du DMG"
    xcrun notarytool submit "$DMG" \
        --apple-id "$APPLE_ID" \
        --team-id "$APPLE_TEAM_ID" \
        --password "$APPLE_APP_PWD" \
        --wait
    echo "📎 [dmg] stapler staple $DMG"
    xcrun stapler staple "$DMG"
    xcrun stapler validate "$DMG"
    echo "✅ [dmg] $DMG notarizé et staplé"
else
    echo "⚠️  [dmg] creds Apple non fournis → DMG non notarizé"
    echo "    Définir APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PWD pour notarizer."
fi

SIZE="$(du -sh "$DMG" | cut -f1)"
echo "✅ [dmg] $DMG produit ($SIZE)"
