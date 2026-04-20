#!/usr/bin/env bash
# Installe ~/Library/LaunchAgents/com.lucie.legifrance.sync.plist
# Sync Légifrance automatique toutes les 48h (172800s) via launchd.
#
# Usage :
#   bash scripts/install_launchd.sh            # installe + charge
#   bash scripts/install_launchd.sh --dry-run  # affiche le plist, ne l'écrit pas

set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

LABEL="com.lucie.legifrance.sync"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$(command -v python3 || echo /usr/bin/python3)"
SCRIPT="${REPO_ROOT}/scripts/legifrance_sync.py"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${LAUNCH_AGENTS_DIR}/${LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/Lucie"
INTERVAL_SECONDS=172800

if [[ ! -f "${SCRIPT}" ]]; then
  echo "ERREUR : script introuvable : ${SCRIPT}" >&2
  exit 1
fi

mkdir -p "${LAUNCH_AGENTS_DIR}" "${LOG_DIR}"

PLIST_CONTENT=$(cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>

  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${SCRIPT}</string>
    <string>--incremental</string>
  </array>

  <key>WorkingDirectory</key>
  <string>${REPO_ROOT}</string>

  <key>StartInterval</key>
  <integer>${INTERVAL_SECONDS}</integer>

  <key>RunAtLoad</key>
  <false/>

  <key>StandardOutPath</key>
  <string>${LOG_DIR}/legifrance_sync.out.log</string>

  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/legifrance_sync.err.log</string>

  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
EOF
)

if [[ ${DRY_RUN} -eq 1 ]]; then
  echo "[dry-run] plist qui serait écrit en ${PLIST_PATH} :"
  echo "${PLIST_CONTENT}"
  exit 0
fi

echo "${PLIST_CONTENT}" > "${PLIST_PATH}"
echo "plist écrit : ${PLIST_PATH}"

# Recharge (unload d'abord si existe, sinon ignore l'erreur)
launchctl unload "${PLIST_PATH}" 2>/dev/null || true
launchctl load "${PLIST_PATH}"

echo "agent launchd chargé (${LABEL})"
echo "prochain sync dans ≤ ${INTERVAL_SECONDS} secondes (48h)"
echo "logs : ${LOG_DIR}/legifrance_sync.{out,err}.log"
