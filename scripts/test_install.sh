#!/usr/bin/env bash
#
# scripts/test_install.sh — vérifie l'installabilité du DMG Beaume.
#
# Simule autant que possible sur la machine de build (un vrai test Mac vierge
# nécessite une VM Sequoia ou un Mac vide, non scriptable raisonnablement dans
# CI — cf. tests/manual/INSTALLATION_CHECKLIST.md pour la suite à la main).
#
# Vérifie :
#   1. dist/Beaume.dmg existe
#   2. SHA-256 calculable + log
#   3. Montage hdiutil → mount point récupéré
#   4. Présence de Beaume.app dans le volume monté
#   5. Présence du lien symbolique /Applications (layout DMG drag-to-install)
#   6. spctl -a -vv -t install (Gatekeeper) → log résultat
#   7. codesign --verify --deep --strict (bundle integrity) → log
#   8. Taille du bundle (warn si > 500 MB, cible Beaume v1)
#   9. Démontage propre hdiutil detach
#  10. Rapport markdown → tests/manual/install_test_report.md (gitignored)
#
# Options :
#   --require-signed   Échec si Gatekeeper rejette (mode CI signed)
#
# Exit codes :
#   0 = OK
#   1 = DMG absent / corrompu
#   2 = layout DMG invalide
#   3 = Gatekeeper rejette en mode --require-signed
#

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

DMG="dist/Beaume.dmg"
VOL_NAME="Beaume"
REPORT="tests/manual/install_test_report.md"
REQUIRE_SIGNED=0
MAX_BUNDLE_MB=500

for arg in "$@"; do
    case "$arg" in
        --require-signed) REQUIRE_SIGNED=1 ;;
        *) echo "❌ Argument inconnu : $arg"; exit 1 ;;
    esac
done

mkdir -p "$(dirname "$REPORT")"

log() {
    echo "$@"
    echo "$@" >> "$REPORT"
}

# --- Étape 1 : pré-flight ---

echo "# Beaume — Install test report" > "$REPORT"
echo "" >> "$REPORT"
echo "_Generated $(date -u '+%Y-%m-%d %H:%M:%S UTC')_" >> "$REPORT"
echo "" >> "$REPORT"

log "## [1/9] Pré-flight"
if [[ ! -f "$DMG" ]]; then
    log "❌ \`$DMG\` introuvable — lance d'abord : \`make dmg-unsigned\` ou \`make dmg-signed\`"
    exit 1
fi
log "    ✅ DMG trouvé : \`$DMG\` ($(du -sh "$DMG" | cut -f1))"

# --- Étape 2 : SHA-256 ---

log ""
log "## [2/9] SHA-256"
SHA=$(shasum -a 256 "$DMG" | cut -d' ' -f1)
log "    \`$SHA\`"

# --- Étape 3 : Montage ---

log ""
log "## [3/9] Montage hdiutil"
# hdiutil attach renvoie une ligne par device avec mount point.
MOUNT_INFO=$(hdiutil attach "$DMG" -nobrowse -readonly | grep -E "/Volumes/" | tail -1 || true)
if [[ -z "$MOUNT_INFO" ]]; then
    log "❌ Échec du montage"
    exit 1
fi
MOUNT_POINT=$(echo "$MOUNT_INFO" | awk '{for (i=3; i<=NF; i++) printf "%s ", $i; print ""}' | sed 's/ *$//')
log "    ✅ Monté sur : \`$MOUNT_POINT\`"

# Cleanup propre même en cas d'erreur après ce point.
trap "hdiutil detach \"$MOUNT_POINT\" -quiet 2>/dev/null || true" EXIT

# --- Étape 4 : Beaume.app présent ---

log ""
log "## [4/9] Beaume.app dans le DMG"
APP_IN_DMG="$MOUNT_POINT/Beaume.app"
if [[ ! -d "$APP_IN_DMG" ]]; then
    log "❌ \`$APP_IN_DMG\` introuvable"
    exit 2
fi
log "    ✅ \`$APP_IN_DMG\` trouvé"

# --- Étape 5 : Lien /Applications (drag-to-install) ---

log ""
log "## [5/9] Lien /Applications (layout drag-to-install)"
if [[ -L "$MOUNT_POINT/Applications" ]]; then
    target=$(readlink "$MOUNT_POINT/Applications")
    log "    ✅ Lien symbolique présent → \`$target\`"
else
    log "    ⚠️  Pas de lien \`Applications\` dans le DMG — l'avocat devra copier manuellement"
fi

# --- Étape 6 : Gatekeeper (spctl) ---

log ""
log "## [6/9] Gatekeeper (\`spctl --assess\`)"
# spctl -a échoue avec exit non-zéro si rejeté — on intercepte pour logger.
set +e
SPCTL_OUTPUT=$(spctl -a -vv -t install "$APP_IN_DMG" 2>&1)
SPCTL_EXIT=$?
set -e
log "    Output : \`$SPCTL_OUTPUT\`"
if (( SPCTL_EXIT == 0 )); then
    log "    ✅ Gatekeeper accepte (app signée + notarized)"
else
    if (( REQUIRE_SIGNED == 1 )); then
        log "    ❌ Gatekeeper rejette en mode --require-signed → fail"
        exit 3
    else
        log "    ⚠️  Gatekeeper rejette (attendu si DMG non signé)"
    fi
fi

# --- Étape 7 : codesign --verify ---

log ""
log "## [7/9] codesign --verify (intégrité bundle)"
set +e
CS_OUTPUT=$(codesign --verify --deep --strict --verbose=2 "$APP_IN_DMG" 2>&1)
CS_EXIT=$?
set -e
log "\`\`\`"
log "$CS_OUTPUT"
log "\`\`\`"
if (( CS_EXIT == 0 )); then
    log "    ✅ codesign verify PASS"
else
    if (( REQUIRE_SIGNED == 1 )); then
        log "    ❌ codesign verify FAIL en mode --require-signed"
        exit 3
    else
        log "    ⚠️  codesign verify FAIL (attendu si DMG non signé)"
    fi
fi

# --- Étape 8 : Taille du bundle ---

log ""
log "## [8/9] Taille du bundle"
BUNDLE_MB=$(du -sm "$APP_IN_DMG" | cut -f1)
log "    Beaume.app = ${BUNDLE_MB} MB (cible v1 : < ${MAX_BUNDLE_MB} MB)"
if (( BUNDLE_MB > MAX_BUNDLE_MB )); then
    log "    ⚠️  Bundle dépasse la cible — vérifier \`excludes\` dans \`setup_py2app.py\`"
else
    log "    ✅ Bundle sous la cible"
fi

# --- Étape 9 : Démontage ---

log ""
log "## [9/9] Démontage"
hdiutil detach "$MOUNT_POINT" -quiet
trap - EXIT
log "    ✅ Démonté"

log ""
log "---"
log ""
log "**Verdict** : DMG monte, contient Beaume.app, $(if (( SPCTL_EXIT == 0 )); then echo "signé+notarized OK"; else echo "non signé (test local)"; fi)."

echo ""
echo "📄 Rapport complet : $REPORT"
