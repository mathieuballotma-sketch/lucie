#!/usr/bin/env bash
# Rollback de l'intégration Légifrance.
#
# Actions (par défaut — confirmation demandée) :
#   1. Désinstalle l'agent launchd com.lucie.legifrance.sync
#   2. Supprime la base SQLite Légifrance
#   3. Supprime le répertoire tarballs/
#   4. Supprime last_sync.json
#
# Le code et le feature flag restent en place — passer LUCIE_LEGIFRANCE=0
# pour désactiver proprement l'appel au retriever Légifrance.
#
# Usage :
#   bash scripts/legifrance_rollback.sh            # interactif (demande confirmation)
#   bash scripts/legifrance_rollback.sh --dry-run  # liste sans exécuter
#   bash scripts/legifrance_rollback.sh --yes      # non-interactif (CI)

set -euo pipefail

DRY_RUN=0
ASSUME_YES=0
for arg in "$@"; do
  case "${arg}" in
    --dry-run)  DRY_RUN=1 ;;
    --yes|-y)   ASSUME_YES=1 ;;
    -h|--help)
      sed -n '1,20p' "$0"
      exit 0
      ;;
    *)
      echo "option inconnue : ${arg}" >&2
      exit 2
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${LUCIE_LEGIFRANCE_DIR:-${HOME}/Library/Application Support/Beaume/legifrance}"

echo "Rollback Légifrance"
echo "  data_dir  = ${DATA_DIR}"
echo "  dry-run   = ${DRY_RUN}"
echo ""

if [[ ${DRY_RUN} -eq 0 && ${ASSUME_YES} -eq 0 ]]; then
  read -r -p "Confirmer la suppression (y/N) ? " reply
  if [[ ! "${reply}" =~ ^[Yy]$ ]]; then
    echo "abandonné"
    exit 0
  fi
fi

run() {
  if [[ ${DRY_RUN} -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    eval "$@"
  fi
}

# 1. Agent launchd
if [[ -x "${REPO_ROOT}/scripts/uninstall_launchd.sh" ]]; then
  if [[ ${DRY_RUN} -eq 1 ]]; then
    echo "[dry-run] bash ${REPO_ROOT}/scripts/uninstall_launchd.sh"
  else
    bash "${REPO_ROOT}/scripts/uninstall_launchd.sh"
  fi
else
  echo "uninstall_launchd.sh absent ou non exécutable — skip"
fi

# 2-4. Contenu data dir
for path in "${DATA_DIR}/legi.sqlite" \
            "${DATA_DIR}/legi.sqlite-wal" \
            "${DATA_DIR}/legi.sqlite-shm" \
            "${DATA_DIR}/last_sync.json" \
            "${DATA_DIR}/tarballs"; do
  if [[ -e "${path}" ]]; then
    run "rm -rf \"${path}\""
  fi
done

echo ""
echo "rollback terminé. Pour désactiver le feature flag, exportez :"
echo "  unset LUCIE_LEGIFRANCE   # ou export LUCIE_LEGIFRANCE=0"
