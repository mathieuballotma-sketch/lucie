#!/usr/bin/env bash
#
# packaging/notarize.sh — soumet Lucie.app à Apple pour notarization.
#
# Usage (via args) :
#   bash packaging/notarize.sh <apple-id> <team-id> <app-specific-password>
#
# Usage (via env) :
#   export APPLE_ID="mathieu.ballotma@gmail.com"
#   export APPLE_TEAM_ID="XXXXXXXXXX"
#   export APPLE_APP_PWD="xxxx-xxxx-xxxx-xxxx"   # app-specific password
#   bash packaging/notarize.sh
#
# Prérequis :
#   - dist/Lucie.app existe ET est signée (lancer sign.sh d'abord)
#   - Apple Developer Program actif (99 €/an)
#   - App-specific password généré sur https://appleid.apple.com
#     (Sign-In and Security → App-Specific Passwords)
#
# Staple le ticket de notarization dans le bundle → installation hors ligne
# possible chez l'avocat pilote.
#

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# --- Récupération des creds ---

APPLE_ID_VAL="${1:-${APPLE_ID:-}}"
TEAM_ID_VAL="${2:-${APPLE_TEAM_ID:-}}"
APP_PWD_VAL="${3:-${APPLE_APP_PWD:-}}"

missing=()
[[ -z "$APPLE_ID_VAL" ]] && missing+=("APPLE_ID")
[[ -z "$TEAM_ID_VAL" ]] && missing+=("APPLE_TEAM_ID")
[[ -z "$APP_PWD_VAL" ]] && missing+=("APPLE_APP_PWD")

if ((${#missing[@]} > 0)); then
    cat <<EOF
❌ Variable(s) manquante(s) : ${missing[*]}

Fournir les creds Apple via arguments :

    bash packaging/notarize.sh <apple-id> <team-id> <app-specific-password>

Ou via variables d'env :

    export APPLE_ID="mathieu.ballotma@gmail.com"
    export APPLE_TEAM_ID="XXXXXXXXXX"
    export APPLE_APP_PWD="xxxx-xxxx-xxxx-xxxx"
    bash packaging/notarize.sh

Prérequis : souscrire Apple Developer Program (99 €/an) + générer un
app-specific password sur https://appleid.apple.com.
EOF
    exit 1
fi

APP="dist/Lucie.app"
ZIP="dist/Lucie.zip"

# --- Vérifications préalables ---

if [[ ! -d "$APP" ]]; then
    echo "❌ $APP introuvable — lance d'abord : bash packaging/build.sh"
    exit 1
fi

# Vérifie que l'app est signée (codesign --verify passe).
if ! codesign --verify --verbose=1 "$APP" 2>/dev/null; then
    echo "❌ $APP n'est pas signée — lance d'abord : bash packaging/sign.sh"
    exit 1
fi

# --- Création du zip pour soumission ---

echo "📦 [notarize] création $ZIP"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"

# --- Soumission ---

echo "☁️  [notarize] xcrun notarytool submit (bloquant — peut prendre 5-15 min)"
xcrun notarytool submit "$ZIP" \
    --apple-id "$APPLE_ID_VAL" \
    --team-id "$TEAM_ID_VAL" \
    --password "$APP_PWD_VAL" \
    --wait

# --- Staple du ticket dans le bundle ---

echo "📎 [notarize] xcrun stapler staple $APP"
xcrun stapler staple "$APP"

echo "🔍 [notarize] xcrun stapler validate"
xcrun stapler validate "$APP"

# --- Cleanup zip intermédiaire ---

rm -f "$ZIP"

echo "✅ [notarize] $APP notarizée et staplée — prête pour distribution"
echo "   Prochaine étape : bash packaging/make_dmg.sh"
