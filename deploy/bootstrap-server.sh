#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="/opt/sal-resource-manager"
APP_UID="10001"
IMAGE="ghcr.io/antonpleshakov/salresourcemanager:latest"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
BOOTSTRAP_TARGET=""
BOOTSTRAP_REMOTE_DIR=""
BOOTSTRAP_SSH_OPTIONS=()

log() {
    printf '[bootstrap] %s\n' "$*"
}

fail() {
    printf '[bootstrap] ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 ||
        fail "Required command not found: $1"
}

require_file() {
    [[ -f "$1" ]] || fail "Required file not found: $1"
}

cleanup_remote_files() {
    [[ -n "$BOOTSTRAP_TARGET" && -n "$BOOTSTRAP_REMOTE_DIR" ]] || return

    ssh "${BOOTSTRAP_SSH_OPTIONS[@]}" "$BOOTSTRAP_TARGET" \
        "rm -f '$BOOTSTRAP_REMOTE_DIR/bootstrap-server.sh' '$BOOTSTRAP_REMOTE_DIR/compose.yaml' '$BOOTSTRAP_REMOTE_DIR/config.ini' '$BOOTSTRAP_REMOTE_DIR/gapi_service_file.json' '$BOOTSTRAP_REMOTE_DIR/ghcr-credentials'; rmdir '$BOOTSTRAP_REMOTE_DIR' 2>/dev/null || true" \
        >/dev/null 2>&1 || true
}

check_docker() {
    require_command docker
    docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable."
    log "Docker is available."
}

ensure_compose() {
    if docker compose version >/dev/null 2>&1; then
        log "Docker Compose is available."
        return
    fi

    log "Docker Compose is missing. Installing docker-compose-v2..."
    require_command apt-get
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y docker-compose-v2
    docker compose version >/dev/null 2>&1 ||
        fail "Docker Compose installation failed."
}

install_files() {
    log "Installing application files in ${APP_DIR}..."
    install -d -m 0750 "$APP_DIR"
    install -d -m 0750 "$APP_DIR/config"
    install -m 0644 "$SCRIPT_DIR/compose.yaml" "$APP_DIR/compose.yaml"
    install -o "$APP_UID" -g "$APP_UID" -m 0400 \
        "$SCRIPT_DIR/config.ini" "$APP_DIR/config/config.ini"
    install -o "$APP_UID" -g "$APP_UID" -m 0400 \
        "$SCRIPT_DIR/gapi_service_file.json" "$APP_DIR/gapi_service_file.json"
}

login_to_ghcr() {
    local credentials_file="$SCRIPT_DIR/ghcr-credentials"
    local username
    local token

    if [[ ! -f "$credentials_file" ]]; then
        log "GHCR credentials were not provided; using anonymous access."
        return
    fi

    username="$(sed -n '1p' "$credentials_file")"
    token="$(sed -n '2p' "$credentials_file")"
    rm -f "$credentials_file"

    [[ -n "$username" ]] || fail "GHCR username is empty."
    [[ -n "$token" ]] || fail "GHCR token is empty."

    log "Logging in to GHCR..."
    printf '%s' "$token" | docker login ghcr.io \
        --username "$username" \
        --password-stdin
}

deploy() {
    log "Pulling ${IMAGE}..."
    (
        cd "$APP_DIR"
        BOT_IMAGE="$IMAGE" docker compose pull
        BOT_IMAGE="$IMAGE" docker compose up -d --force-recreate --remove-orphans
    )
}

verify() {
    local status
    local logs

    for _ in {1..45}; do
        status="$(
            docker inspect \
                --format '{{.State.Status}}' \
                sal-resource-manager \
                2>/dev/null || true
        )"
        logs="$(docker logs sal-resource-manager --tail 200 2>&1 || true)"

        if [[ "$status" == "running" ]] && \
            grep -Fq "Sal Resources Manager started" <<<"$logs"; then
            log "Application startup completed."
            return
        fi

        sleep 2
    done

    log "Application failed to complete startup. Recent logs:"
    docker logs sal-resource-manager --tail 100 2>&1 || true
    exit 1
}

remote_main() {
    [[ "${EUID}" -eq 0 ]] || fail "Remote bootstrap must run as root."
    require_file "$SCRIPT_DIR/compose.yaml"
    require_file "$SCRIPT_DIR/config.ini"
    require_file "$SCRIPT_DIR/gapi_service_file.json"
    check_docker
    ensure_compose
    install_files
    login_to_ghcr
    deploy
    verify
    log "Server environment is ready."
}

local_main() {
    local port="${SSH_PORT:-22}"
    local identity_file="${SSH_IDENTITY_FILE:-}"
    local option
    local target
    local config_source="${CONFIG_FILE:-${PROJECT_DIR}/config/config.ini}"
    local credentials_source="${GOOGLE_CREDENTIALS_FILE:-${PROJECT_DIR}/gapi_service_file.json}"
    local remote_dir="/tmp/sal-resource-manager-bootstrap-$$"
    local ssh_options
    local scp_options

    OPTIND=1
    while getopts ":i:p:" option; do
        case "$option" in
            i) identity_file="$OPTARG" ;;
            p) port="$OPTARG" ;;
            :) fail "Option -$OPTARG requires a value." ;;
            \?) fail "Unknown option: -$OPTARG" ;;
        esac
    done
    shift "$((OPTIND - 1))"

    target="${1:-${SSH_TARGET:-}}"
    [[ "$#" -le 1 ]] || fail "Usage: $0 [-i identity_file] [-p port] <user@server>"
    ssh_options=(-p "$port" -o BatchMode=yes)
    scp_options=(-P "$port" -o BatchMode=yes)

    [[ -n "$target" ]] ||
        fail "Usage: $0 [-i identity_file] [-p port] <user@server>"
    require_command ssh
    require_command scp
    require_file "$PROJECT_DIR/compose.yaml"
    require_file "$config_source"
    require_file "$credentials_source"

    if [[ -n "$identity_file" ]]; then
        require_file "$identity_file"
        ssh_options+=(-i "$identity_file")
        scp_options+=(-i "$identity_file")
    fi

    if [[ -z "${GHCR_USERNAME:-}" && -z "${GHCR_TOKEN:-}" ]]; then
        [[ -t 0 ]] ||
            fail "Set GHCR_USERNAME and GHCR_TOKEN for non-interactive use."
        read -r -p "GHCR username [AntonPleshakov]: " GHCR_USERNAME
        GHCR_USERNAME="${GHCR_USERNAME:-AntonPleshakov}"
        read -r -s -p "GHCR token (classic PAT with read:packages): " GHCR_TOKEN
        printf '\n'
    fi

    [[ -n "${GHCR_USERNAME:-}" && -n "${GHCR_TOKEN:-}" ]] ||
        fail "GHCR_USERNAME and GHCR_TOKEN must be set together."

    BOOTSTRAP_TARGET="$target"
    BOOTSTRAP_REMOTE_DIR="$remote_dir"
    BOOTSTRAP_SSH_OPTIONS=("${ssh_options[@]}")
    trap cleanup_remote_files EXIT

    log "Connecting to ${target}..."
    ssh "${ssh_options[@]}" "$target" "install -d -m 0700 '$remote_dir'"

    log "Copying configuration and credentials..."
    scp "${scp_options[@]}" "$SCRIPT_DIR/bootstrap-server.sh" \
        "$target:$remote_dir/bootstrap-server.sh"
    scp "${scp_options[@]}" "$PROJECT_DIR/compose.yaml" \
        "$target:$remote_dir/compose.yaml"
    scp "${scp_options[@]}" "$config_source" \
        "$target:$remote_dir/config.ini"
    scp "${scp_options[@]}" "$credentials_source" \
        "$target:$remote_dir/gapi_service_file.json"

    {
        printf '%s\n' "$GHCR_USERNAME"
        printf '%s\n' "$GHCR_TOKEN"
    } | ssh "${ssh_options[@]}" "$target" \
        "umask 077; cat > '$remote_dir/ghcr-credentials'"

    log "Running initial setup on the server..."
    ssh "${ssh_options[@]}" "$target" \
        "if [ \"\$(id -u)\" -eq 0 ]; then bash '$remote_dir/bootstrap-server.sh' --remote; else sudo -n bash '$remote_dir/bootstrap-server.sh' --remote; fi"
}

if [[ "${1:-}" == "--remote" ]]; then
    remote_main
else
    local_main "$@"
fi
