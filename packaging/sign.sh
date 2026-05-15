#!/usr/bin/env bash
#
# packaging/sign.sh — signe Beaume.app avec un Developer ID Application.
#
# Usage :
#   bash packaging/sign.sh "Developer ID Application: Mathieu Ballot (TEAMID)"
#
# Ou via variable d'env :
#   export DEVELOPER_ID="Developer ID Application: Mathieu Ballot (TEAMID)"
#   bash packaging/sign.sh
#
# Prérequis :
#   - dist/Beaume.app existe (lancer build.sh d'abord)
#   - certificat Developer ID Application installé dans le trousseau
#     (Keychain Access → Mes certificats)
#
# Idempotent : resignature propre si déjà signé.
#

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# --- Récupération du Developer ID ---

DEV_ID="${1:-${DEVELOPER_ID:-}}"
if [[ -z "$DEV_ID" ]]; then
    cat <<'EOF'
❌ DEVELOPER_ID non défini.

Fournir le certificat en argument ou via variable d'env :

    bash packaging/sign.sh "Developer ID Application: NOM (TEAMID)"

    # ou
    export DEVELOPER_ID="Developer ID Application: NOM (TEAMID)"
    bash packaging/sign.sh

Prérequis : souscrire Apple Developer Program (99 €/an) sur
https://developer.apple.com puis installer le certificat dans le trousseau.
EOF
    exit 1
fi

# Filet de sécurité : refus si DEVELOPER_ID ressemble à un chemin de fichier
# (on veut le nom du certificat dans le trousseau, pas un .p12 sur disque).
if [[ "$DEV_ID" == /* || "$DEV_ID" == *.p12 || "$DEV_ID" == *.cer ]]; then
    echo "❌ DEVELOPER_ID semble être un chemin de fichier : $DEV_ID"
    echo "   Attendu : 'Developer ID Application: NOM (TEAMID)' — nom trousseau."
    exit 1
fi

APP="dist/Beaume.app"
ENTITLEMENTS="packaging/Beaume.entitlements"

# --- Vérifications préalables ---

if [[ ! -d "$APP" ]]; then
    echo "❌ $APP introuvable — lance d'abord : bash packaging/build.sh"
    exit 1
fi

if [[ ! -f "$ENTITLEMENTS" ]]; then
    echo "❌ $ENTITLEMENTS introuvable."
    exit 1
fi

echo "🔍 [sign] plutil -lint $ENTITLEMENTS"
plutil -lint "$ENTITLEMENTS"

# --- Vérifier que le certificat existe dans le trousseau ---

if ! security find-identity -v -p codesigning | grep -q "$DEV_ID"; then
    echo "❌ Certificat '$DEV_ID' introuvable dans le trousseau."
    echo "   Liste disponible :"
    security find-identity -v -p codesigning || true
    exit 1
fi

# --- Signature ---

echo "🔐 [sign] codesign --deep --options runtime $APP"
codesign --force --deep \
    --sign "$DEV_ID" \
    --options runtime \
    --entitlements "$ENTITLEMENTS" \
    --timestamp \
    "$APP"

# --- Vérification ---

echo "🔍 [sign] codesign --verify --verbose=2"
codesign --verify --verbose=2 "$APP"

echo "🔍 [sign] spctl --assess (Gatekeeper pre-check)"
if spctl --assess --type execute --verbose "$APP" 2>&1; then
    echo "✅ [sign] $APP signée et acceptée par spctl"
else
    echo "⚠️  [sign] spctl refuse — normal tant que non notarizée."
    echo "   Prochaine étape : bash packaging/notarize.sh"
fi

echo "✅ [sign] signature OK"
