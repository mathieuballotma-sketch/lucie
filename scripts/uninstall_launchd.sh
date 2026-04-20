#!/usr/bin/env bash
# Désinstalle l'agent launchd `com.lucie.legifrance.sync`.
# Utilisé par legifrance_rollback.sh mais peut être lancé seul.

set -euo pipefail

LABEL="com.lucie.legifrance.sync"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [[ -f "${PLIST_PATH}" ]]; then
  launchctl unload "${PLIST_PATH}" 2>/dev/null || true
  rm "${PLIST_PATH}"
  echo "agent launchd désinstallé (${LABEL})"
else
  echo "aucun agent launchd trouvé (${PLIST_PATH})"
fi
