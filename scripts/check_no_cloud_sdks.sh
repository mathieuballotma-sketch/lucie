#!/usr/bin/env bash
#
# scripts/check_no_cloud_sdks.sh — garde-fou Beaume 100% local.
#
# Scanne dist/Beaume.app/Contents/Resources/lib/ pour détecter :
#   1. Présence de SDKs cloud bannis (openai, anthropic, sentry_sdk, posthog,
#      mixpanel, datadog) — détection structurelle par __init__.py, pas par
#      regex sur les sources (zéro false positive depuis un commentaire).
#   2. Chaînes secrètes hardcodées : clés API (sk-…), tokens (xoxb-…),
#      patterns d'env vars qui auraient fuité.
#
# Exit 0 si bundle propre, exit 1 + liste des fichiers offenseurs sinon.
#
# Usage :
#   bash scripts/check_no_cloud_sdks.sh
#
# Prérequis : `make dmg-build` ou `make dmg-unsigned` exécuté d'abord
# (le script échoue immédiatement si dist/Beaume.app n'existe pas).
#

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

BUNDLE="dist/Beaume.app"
LIB_DIR="$BUNDLE/Contents/Resources/lib"

# Packages cloud à bannir : présence du __init__.py = SDK installé dans le bundle.
FORBIDDEN_PACKAGES=(
    openai
    anthropic
    sentry_sdk
    posthog
    mixpanel
    datadog
    rollbar
    bugsnag
    segment
    amplitude
)

# Patterns secrets potentiels (regex étendues).
SECRET_PATTERNS=(
    'sk-[A-Za-z0-9]{40,}'              # OpenAI / Anthropic style
    'xoxb-[A-Za-z0-9-]{40,}'           # Slack bot token
    'ghp_[A-Za-z0-9]{36,}'             # GitHub personal access token
    'AKIA[0-9A-Z]{16}'                 # AWS access key
    'ANTHROPIC_API_KEY[ ]*=[ ]*["a-zA-Z0-9]'
    'OPENAI_API_KEY[ ]*=[ ]*["a-zA-Z0-9]'
)

echo "[1/3] Vérification de l'existence du bundle"
if [[ ! -d "$BUNDLE" ]]; then
    echo "❌ $BUNDLE introuvable — lance d'abord : make dmg-build"
    exit 1
fi

if [[ ! -d "$LIB_DIR" ]]; then
    echo "❌ $LIB_DIR introuvable — bundle py2app malformé ?"
    exit 1
fi

echo "    ✅ Bundle trouvé : $BUNDLE ($(du -sh "$BUNDLE" | cut -f1))"

# --- Check 1 : packages cloud ---

echo "[2/3] Recherche de packages cloud interdits"
offenders_pkg=()
for pkg in "${FORBIDDEN_PACKAGES[@]}"; do
    # py2app installe les packages soit dans lib/python3.X/site-packages/<pkg>/
    # soit dans lib/python3.X/<pkg>/ (semi_standalone=False) — on cherche large.
    matches=$(find "$LIB_DIR" -type d -name "$pkg" 2>/dev/null | head -5 || true)
    if [[ -n "$matches" ]]; then
        # Confirme la présence d'un __init__.py pour distinguer un vrai package
        # d'un répertoire qui s'appellerait comme un SDK par coïncidence.
        for match in $matches; do
            if [[ -f "$match/__init__.py" ]]; then
                offenders_pkg+=("$match")
            fi
        done
    fi
done

if (( ${#offenders_pkg[@]} > 0 )); then
    echo "    ❌ Packages cloud détectés dans le bundle :"
    for o in "${offenders_pkg[@]}"; do
        echo "       - $o"
    done
else
    echo "    ✅ Aucun SDK cloud présent (${#FORBIDDEN_PACKAGES[@]} packages vérifiés)"
fi

# --- Check 2 : secrets hardcodés ---

echo "[3/3] Recherche de secrets hardcodés"
offenders_sec=()
for pattern in "${SECRET_PATTERNS[@]}"; do
    matches=$(grep -rEl --include="*.py" --include="*.pyc" --include="*.json" --include="*.yaml" \
        "$pattern" "$LIB_DIR" 2>/dev/null | head -10 || true)
    if [[ -n "$matches" ]]; then
        while IFS= read -r line; do
            offenders_sec+=("$line  (pattern: $pattern)")
        done <<< "$matches"
    fi
done

if (( ${#offenders_sec[@]} > 0 )); then
    echo "    ❌ Secrets potentiels détectés :"
    for o in "${offenders_sec[@]}"; do
        echo "       - $o"
    done
else
    echo "    ✅ Aucun secret hardcodé détecté (${#SECRET_PATTERNS[@]} patterns testés)"
fi

# --- Verdict ---

total=$(( ${#offenders_pkg[@]} + ${#offenders_sec[@]} ))
if (( total > 0 )); then
    echo ""
    echo "❌ $total problème(s) détecté(s) — bundle non distribuable."
    echo "   Beaume DOIT rester 100% local : zéro cloud, zéro telemetry, zéro fuite."
    exit 1
fi

echo ""
echo "✅ Bundle propre : 0 SDK cloud, 0 secret hardcodé."
echo "   Beaume reste 100% local conformément à l'invariant non-négociable."
