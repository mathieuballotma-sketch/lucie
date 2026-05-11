#!/usr/bin/env bash
# Migre l'agent launchd Légifrance de com.lucie.* → com.beaume.*
# (Sprint 1ter — rebrand 2026-05-02, cleanup post-merge).
#
# À lancer UNE FOIS par Mathieu, post-merge de la branche
# `chore/sprint-1ter-rebrand-cleanup-2026-05-08` sur main.
#
# Idempotent : safe à relancer (les étapes ignorent silencieusement les
# états déjà atteints).

set -euo pipefail

OLD_LABEL="com.lucie.legifrance.sync"
NEW_LABEL="com.beaume.legifrance.sync"
OLD_PLIST="${HOME}/Library/LaunchAgents/${OLD_LABEL}.plist"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[1/3] Unload ancien job ${OLD_LABEL}..."
if [[ -f "${OLD_PLIST}" ]]; then
  launchctl unload "${OLD_PLIST}" 2>/dev/null || echo "  (ancien job non chargé, skip unload)"
else
  echo "  (ancien plist absent, skip)"
fi

echo "[2/3] Suppression ancien plist ${OLD_PLIST}..."
if [[ -f "${OLD_PLIST}" ]]; then
  rm -f "${OLD_PLIST}"
  echo "  → supprimé"
else
  echo "  (déjà absent)"
fi

echo "[3/3] Installation nouveau job ${NEW_LABEL}..."
bash "${SCRIPT_DIR}/install_launchd.sh"

echo ""
echo "✓ Migration launchd terminée"
if launchctl list 2>/dev/null | grep -q beaume; then
  echo "  ${NEW_LABEL} chargé (vérifié via launchctl list | grep beaume)"
else
  echo "  ⚠ vérification manuelle recommandée : launchctl list | grep beaume"
fi
