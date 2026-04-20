#!/usr/bin/env bash
# reset_lucie_fresh_install.sh
#
# Remet Lucie dans l'état « première installation » :
# - Wipe mémoires adaptatives, audit trail, vector stores, profils, journaux, Healer runtime
# - Préserve ~/.ollama (36 GB de modèles LLM) et ~/Documents/Lucie (doc stratégique)
#
# Mode DRY-RUN par défaut. Utiliser --execute pour le wipe réel.
# Voir: /Users/mathieu/Documents/Lucie/04_Recherche/Reset_Lucie_Inventaire_2026-04-20.md

set -euo pipefail

# =============================================================================
# Constantes
# =============================================================================

REPO_ROOT="/Users/mathieu/Desktop/mon-agence-ia"
HOME_DIR="${HOME}"
DATE_STAMP="$(date +%Y-%m-%d)"
TIME_STAMP="$(date +%H%M%S)"
LOG_FILE="${HOME_DIR}/Desktop/lucie_reset_log_${DATE_STAMP}_${TIME_STAMP}.log"
BACKUP_DIR="${HOME_DIR}/Desktop/lucie_backup_${DATE_STAMP}"

# Chemins sacrés — JAMAIS toucher
SACRED_OLLAMA="${HOME_DIR}/.ollama"
SACRED_DOCS="${HOME_DIR}/Documents/Lucie"
SACRED_MIN_OLLAMA_KB=$((30 * 1024 * 1024))   # ~30 GB
SACRED_MIN_DOCS_KB=$((1 * 1024))             # ~1 MB

# Couleurs ANSI
C_RED=$'\033[0;31m'
C_YLW=$'\033[0;33m'
C_GRN=$'\033[0;32m'
C_BLU=$'\033[0;34m'
C_BLD=$'\033[1m'
C_END=$'\033[0m'

# Options
EXECUTE=0
BACKUP=0
YES=0

# =============================================================================
# Utilitaires
# =============================================================================

usage() {
    cat <<EOF
${C_BLD}reset_lucie_fresh_install.sh${C_END} — Remet Lucie dans l'état « première installation »

${C_BLD}USAGE:${C_END}
  $(basename "$0") [OPTIONS]

${C_BLD}OPTIONS:${C_END}
  --execute    Effectue le wipe réel. Sans ce flag, mode dry-run (aucune suppression).
  --backup     Sauvegarde chaque zone en tar.gz dans ${BACKUP_DIR}/ avant wipe.
  --yes        Skip les confirmations interactives (à combiner avec --execute).
  --help       Affiche cette aide.

${C_BLD}MODES:${C_END}
  ${C_BLU}DRY-RUN${C_END} (défaut)   : liste ce qui serait supprimé, ne touche rien.
  ${C_RED}EXECUTE${C_END}           : supprime réellement (confirmations par bloc sauf --yes).

${C_BLD}PRÉSERVÉ (strict, guards actifs) :${C_END}
  - ${SACRED_OLLAMA} (modèles LLM, ~36 GB)
  - ${SACRED_DOCS} (doc stratégique produit, ~3 MB)
  - Code source du repo ${REPO_ROOT}

${C_BLD}EXEMPLES:${C_END}
  $(basename "$0")                    # dry-run simple
  $(basename "$0") --backup           # dry-run + liste des backups prévus
  $(basename "$0") --execute          # wipe réel, interactif
  $(basename "$0") --execute --backup # wipe réel avec backup
  $(basename "$0") --execute --yes    # wipe réel sans confirmations (⚠ dangereux)

${C_BLD}LOG:${C_END} ${LOG_FILE}
EOF
}

log() {
    # tee stdout + fichier log
    local msg="$*"
    printf '%s\n' "${msg}" | tee -a "${LOG_FILE}"
}

log_info()   { log "${C_BLU}[INFO]${C_END}  $*"; }
log_warn()   { log "${C_YLW}[WARN]${C_END}  $*"; }
log_ok()     { log "${C_GRN}[OK]${C_END}    $*"; }
log_danger() { log "${C_RED}[!!]${C_END}    $*"; }
log_head()   { log ""; log "${C_BLD}${C_BLU}━━━ $* ━━━${C_END}"; }

confirm() {
    # confirm "message" — retourne 0 si oui, 1 sinon
    if [[ "${YES}" -eq 1 ]]; then
        return 0
    fi
    local msg="$1"
    local reply
    printf '%s [y/N] ' "${msg}" >&2
    read -r reply
    [[ "${reply}" =~ ^[yYoO]$ ]]
}

guard_path() {
    # Refuse les chemins dangereux (/, /Users/mathieu, etc.)
    local path="$1"
    case "${path}" in
        "" | "/" | "/Users" | "/Users/mathieu" | "${HOME_DIR}" | "${REPO_ROOT}")
            log_danger "Refus de toucher un chemin sacré : ${path}"
            return 1
            ;;
        "${SACRED_OLLAMA}" | "${SACRED_OLLAMA}/"* | "${SACRED_DOCS}" | "${SACRED_DOCS}/"*)
            log_danger "Refus de toucher un chemin PRÉSERVÉ : ${path}"
            return 1
            ;;
    esac
    return 0
}

safe_remove() {
    # safe_remove <chemin> — wipe si --execute, sinon log "[DRY]"
    local target="$1"
    if ! guard_path "${target}"; then
        return 1
    fi
    if [[ ! -e "${target}" ]]; then
        log_info "[SKIP] ${target} (absent)"
        return 0
    fi
    local size
    size=$(du -sh "${target}" 2>/dev/null | awk '{print $1}')
    if [[ "${EXECUTE}" -eq 1 ]]; then
        rm -rf "${target}"
        log_ok "[WIPED ${size}] ${target}"
    else
        log_warn "[DRY ${size}] ${target}"
    fi
}

safe_remove_contents() {
    # safe_remove_contents <dir> — supprime le contenu mais garde le dossier
    local dir="$1"
    if ! guard_path "${dir}"; then
        return 1
    fi
    if [[ ! -d "${dir}" ]]; then
        log_info "[SKIP] ${dir} (absent)"
        return 0
    fi
    local size
    size=$(du -sh "${dir}" 2>/dev/null | awk '{print $1}')
    if [[ "${EXECUTE}" -eq 1 ]]; then
        find "${dir}" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
        log_ok "[EMPTIED ${size}] ${dir}/*"
    else
        log_warn "[DRY ${size}] ${dir}/* (contenu)"
    fi
}

backup_zone() {
    # backup_zone <nom> <chemins...>
    if [[ "${BACKUP}" -ne 1 ]]; then
        return 0
    fi
    local name="$1"; shift
    local archive="${BACKUP_DIR}/${name}.tar.gz"
    mkdir -p "${BACKUP_DIR}"
    local existing=()
    local p
    for p in "$@"; do
        if [[ -e "${p}" ]]; then
            existing+=("${p}")
        fi
    done
    if [[ ${#existing[@]} -eq 0 ]]; then
        log_info "[BACKUP] ${name}: rien à archiver"
        return 0
    fi
    if [[ "${EXECUTE}" -eq 1 ]]; then
        tar -czf "${archive}" "${existing[@]}" 2>/dev/null || true
        log_ok "[BACKUP] ${archive} (${#existing[@]} chemins)"
    else
        log_warn "[DRY BACKUP] ${archive} → ${existing[*]}"
    fi
}

dir_size_kb() {
    # renvoie la taille en KB d'un chemin, 0 si absent
    [[ -e "$1" ]] || { echo 0; return; }
    du -sk "$1" 2>/dev/null | awk '{print $1}'
}

preserve_check() {
    # Assert que les chemins sacrés sont toujours présents et de taille suffisante
    log_head "PRESERVE CHECK"
    local fail=0

    local ollama_kb
    ollama_kb=$(dir_size_kb "${SACRED_OLLAMA}")
    if [[ "${ollama_kb}" -lt "${SACRED_MIN_OLLAMA_KB}" ]]; then
        log_danger "~/.ollama/ taille anormale : ${ollama_kb} KB (attendu ≥ ${SACRED_MIN_OLLAMA_KB} KB)"
        fail=1
    else
        log_ok "~/.ollama/ intact (${ollama_kb} KB)"
    fi

    local docs_kb
    docs_kb=$(dir_size_kb "${SACRED_DOCS}")
    if [[ "${docs_kb}" -lt "${SACRED_MIN_DOCS_KB}" ]]; then
        log_danger "~/Documents/Lucie/ taille anormale : ${docs_kb} KB (attendu ≥ ${SACRED_MIN_DOCS_KB} KB)"
        fail=1
    else
        log_ok "~/Documents/Lucie/ intact (${docs_kb} KB)"
    fi

    if [[ "${fail}" -eq 1 ]]; then
        log_danger "PRESERVE CHECK ÉCHOUÉ — un chemin sacré a été altéré. Vérifier immédiatement."
        return 1
    fi
    log_ok "PRESERVE CHECK OK"
    return 0
}

# =============================================================================
# Parse args
# =============================================================================

while [[ $# -gt 0 ]]; do
    case "$1" in
        --execute) EXECUTE=1 ;;
        --backup)  BACKUP=1 ;;
        --yes)     YES=1 ;;
        --help|-h) usage; exit 0 ;;
        *) printf 'Option inconnue : %s\n' "$1" >&2; usage; exit 1 ;;
    esac
    shift
done

# =============================================================================
# Preflight
# =============================================================================

touch "${LOG_FILE}"
log_head "RESET LUCIE — ${DATE_STAMP} ${TIME_STAMP}"
log_info "Log : ${LOG_FILE}"

if [[ "${EXECUTE}" -eq 1 ]]; then
    log_danger "MODE : EXECUTE (le wipe sera réel)"
else
    log_info "MODE : DRY-RUN (aucune suppression, utilise --execute pour wiper)"
fi

[[ "${BACKUP}" -eq 1 ]] && log_info "Backup ON → ${BACKUP_DIR}/"
[[ "${YES}" -eq 1 ]]    && log_warn "Mode --yes : confirmations skip"

# macOS check
if [[ "$(uname -s)" != "Darwin" ]]; then
    log_warn "Non-macOS détecté ($(uname -s)). Script conçu pour macOS. Continuer?"
    confirm "Forcer malgré tout?" || { log_info "Abandon."; exit 0; }
fi

# Preserve pre-check
log_head "PRÉ-CHECK"
if [[ ! -d "${SACRED_OLLAMA}" ]]; then
    log_warn "~/.ollama/ absent — Ollama pas installé ? Les modèles devront être téléchargés après reset."
else
    log_ok "~/.ollama/ présent ($(du -sh "${SACRED_OLLAMA}" | awk '{print $1}'))"
fi
if [[ ! -d "${SACRED_DOCS}" ]]; then
    log_warn "~/Documents/Lucie/ absent — pas de doc stratégique à préserver."
else
    log_ok "~/Documents/Lucie/ présent ($(du -sh "${SACRED_DOCS}" | awk '{print $1}'))"
fi

if [[ "${EXECUTE}" -eq 1 && "${YES}" -ne 1 ]]; then
    log_warn ""
    log_warn "⚠  Le wipe va modifier le disque. Lis la liste ci-dessous avant de confirmer."
    log_warn "⚠  Les chemins ~/.ollama et ~/Documents/Lucie sont protégés par guards."
    log_warn ""
    confirm "Continuer vers les blocs de wipe?" || { log_info "Abandon utilisateur."; exit 0; }
fi

# =============================================================================
# Bloc 1 — Repo runtime
# =============================================================================

log_head "BLOC 1 — REPO RUNTIME (${REPO_ROOT})"

REPO_TARGETS=(
    "${REPO_ROOT}/data"
    "${REPO_ROOT}/chroma_data"
    "${REPO_ROOT}/rag_data"
    "${REPO_ROOT}/memory/journals"
    "${REPO_ROOT}/app/memory/journals"
    "${REPO_ROOT}/.audit_salt"
    "${REPO_ROOT}/audit.db"
)

log_info "Ciblé (contenu runtime, code source préservé) :"
for t in "${REPO_TARGETS[@]}"; do
    if [[ -e "${t}" ]]; then
        log_info "  - ${t} ($(du -sh "${t}" 2>/dev/null | awk '{print $1}'))"
    fi
done
log_info "  - ${REPO_ROOT}/logs/* (contenu seulement, dossier préservé)"

if confirm "Bloc 1 : wipe repo runtime?"; then
    backup_zone "01_repo_runtime" "${REPO_TARGETS[@]}"
    for t in "${REPO_TARGETS[@]}"; do
        safe_remove "${t}"
    done
    safe_remove_contents "${REPO_ROOT}/logs"
else
    log_warn "Bloc 1 skip."
fi

# =============================================================================
# Bloc 2 — Home : ~/.lucie et crewAI
# =============================================================================

log_head "BLOC 2 — HOME (~/.lucie + crewAI state)"

HOME_TARGETS=(
    "${HOME_DIR}/.lucie"
    "${HOME_DIR}/Library/Application Support/mon-agence-ia"
)

log_info "Ciblé :"
for t in "${HOME_TARGETS[@]}"; do
    if [[ -e "${t}" ]]; then
        log_info "  - ${t} ($(du -sh "${t}" 2>/dev/null | awk '{print $1}'))"
    fi
done

if confirm "Bloc 2 : wipe ~/.lucie et crewAI state?"; then
    backup_zone "02_home_lucie_crewai" "${HOME_TARGETS[@]}"
    for t in "${HOME_TARGETS[@]}"; do
        safe_remove "${t}"
    done
else
    log_warn "Bloc 2 skip."
fi

# =============================================================================
# Bloc 3 — Healer (Agent Lucide cybersécurité)
# =============================================================================

log_head "BLOC 3 — HEALER (cybersécurité Agent Lucide)"

HEALER_DBS=(
    "${HOME_DIR}/.agent_lucide/attackers.db"
    "${HOME_DIR}/.agent_lucide/lure_tracker.db"
)
HEALER_DIRS_CONTENT=(
    "${HOME_DIR}/AgentLucide/quarantine"
    "${HOME_DIR}/AgentLucide/lures"
    "${HOME_DIR}/AgentLucide/workspace"
)

log_info "Ciblé (DB runtime + contenu dossiers Healer) :"
for t in "${HEALER_DBS[@]}"; do
    [[ -e "${t}" ]] && log_info "  - ${t} ($(du -sh "${t}" 2>/dev/null | awk '{print $1}'))"
done
for t in "${HEALER_DIRS_CONTENT[@]}"; do
    [[ -e "${t}" ]] && log_info "  - ${t}/* (contenu)"
done
log_info "  ${C_GRN}PRÉSERVÉ${C_END} : ${HOME_DIR}/.agent_lucide/malicious_hashes.txt (config)"

if confirm "Bloc 3 : wipe Healer runtime?"; then
    backup_zone "03_healer" "${HEALER_DBS[@]}" "${HEALER_DIRS_CONTENT[@]}"
    for t in "${HEALER_DBS[@]}"; do
        safe_remove "${t}"
    done
    for t in "${HEALER_DIRS_CONTENT[@]}"; do
        safe_remove_contents "${t}"
    done
else
    log_warn "Bloc 3 skip."
fi

# =============================================================================
# Bloc 4 — Temp
# =============================================================================

log_head "BLOC 4 — TEMP"

TEMP_MATCHES=()
for pattern in /tmp/lucie* /private/tmp/lucie*; do
    for f in ${pattern}; do
        [[ -e "${f}" ]] && TEMP_MATCHES+=("${f}")
    done
done

if [[ ${#TEMP_MATCHES[@]} -eq 0 ]]; then
    log_info "Aucun résidu temp trouvé."
else
    log_info "Ciblé :"
    for t in "${TEMP_MATCHES[@]}"; do
        log_info "  - ${t}"
    done
    if confirm "Bloc 4 : wipe temp?"; then
        for t in "${TEMP_MATCHES[@]}"; do
            safe_remove "${t}"
        done
    else
        log_warn "Bloc 4 skip."
    fi
fi

# =============================================================================
# Preserve post-check
# =============================================================================

preserve_check || {
    log_danger "STOP — vérifier l'état du disque avant de continuer."
    exit 2
}

# =============================================================================
# Re-scan final
# =============================================================================

log_head "RE-SCAN FINAL"

check_empty() {
    local p="$1"
    if [[ ! -e "${p}" ]]; then
        log_ok "  ✓ ${p} absent"
    elif [[ -d "${p}" && -z "$(ls -A "${p}" 2>/dev/null)" ]]; then
        log_ok "  ✓ ${p} vide"
    else
        if [[ "${EXECUTE}" -eq 1 ]]; then
            log_warn "  ✗ ${p} ENCORE PRÉSENT ($(du -sh "${p}" 2>/dev/null | awk '{print $1}'))"
        else
            log_info "  · ${p} (dry-run : présence normale)"
        fi
    fi
}

log_info "Repo runtime :"
for t in "${REPO_TARGETS[@]}"; do check_empty "${t}"; done
check_empty "${REPO_ROOT}/logs"

log_info "Home :"
for t in "${HOME_TARGETS[@]}"; do check_empty "${t}"; done

log_info "Healer runtime (DBs) :"
for t in "${HEALER_DBS[@]}"; do check_empty "${t}"; done

log_info "Préservé :"
log_ok "  ✓ ${SACRED_OLLAMA} ($(du -sh "${SACRED_OLLAMA}" 2>/dev/null | awk '{print $1}'))"
log_ok "  ✓ ${SACRED_DOCS} ($(du -sh "${SACRED_DOCS}" 2>/dev/null | awk '{print $1}'))"
log_ok "  ✓ ${HOME_DIR}/.agent_lucide/malicious_hashes.txt (si présent)"

# =============================================================================
# Bilan
# =============================================================================

log_head "BILAN"
if [[ "${EXECUTE}" -eq 1 ]]; then
    log_ok "Reset terminé."
    log_info "Checklist post-reset à valider :"
    log_info "  1. Lancer Lucie → questionnaire onboarding doit s'afficher"
    log_info "  2. Premier message → réponse ne doit pas référencer d'échange passé"
    log_info "  3. Audit trail : .audit_salt régénéré (chmod 600) dès la première action"
    log_info "  4. Vector store : aucune suggestion de jurisprudence cachée"
    log_info "  5. RPVA : identifiants redemandés (si feature active)"
    log_info "  6. Healer stats à 0 (attackers.db, lure_tracker.db régénérés vides)"
else
    log_info "Dry-run terminé. Relancer avec --execute pour effectuer le wipe."
fi
log_info "Log complet : ${LOG_FILE}"
[[ "${BACKUP}" -eq 1 ]] && log_info "Backups : ${BACKUP_DIR}/"
