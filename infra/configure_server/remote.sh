#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="/opt/sal-resource-manager"
APP_UID="10001"
APP_GID="10001"
CONTAINER_NAME="sal-resource-manager"
SOURCE_DIR="${1:?Source directory is required}"
APP_RESTART_REQUIRED=false

log() {
    printf '[configure] %s\n' "$*"
}

fail() {
    printf '[configure] ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 ||
        fail "Required command not found: $1"
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

ensure_directories() {
    install -d -m 0750 "$APP_DIR"
    install -d -m 0750 "$APP_DIR/config"
    install -o "$APP_UID" -g "$APP_GID" -d -m 0750 "$APP_DIR/data"
}

install_managed_file() {
    local source="$1"
    local destination="$2"
    local owner="$3"
    local group="$4"
    local mode="$5"
    local restart_on_change="$6"

    if [[ ! -f "$destination" ]] || ! cmp -s "$source" "$destination"; then
        install -o "$owner" -g "$group" -m "$mode" "$source" "$destination"
        log "Updated $destination."
        if [[ "$restart_on_change" == "true" ]]; then
            APP_RESTART_REQUIRED=true
        fi
        return
    fi

    chown "$owner:$group" "$destination"
    chmod "$mode" "$destination"
    log "$destination is current."
}

install_configuration() {
    ensure_directories
    install_managed_file \
        "$SOURCE_DIR/compose.yaml" "$APP_DIR/compose.yaml" \
        root root 0644 false
    install_managed_file \
        "$SOURCE_DIR/config.ini" "$APP_DIR/config/config.ini" \
        "$APP_UID" "$APP_GID" 0400 true
    install_managed_file \
        "$SOURCE_DIR/gapi_service_file.json" "$APP_DIR/gapi_service_file.json" \
        "$APP_UID" "$APP_GID" 0400 true
}

login_to_ghcr() {
    local credentials_file="$SOURCE_DIR/ghcr-credentials"
    local username
    local token

    [[ -f "$credentials_file" ]] || return 0

    username="$(sed -n '1p' "$credentials_file")"
    token="$(sed -n '2p' "$credentials_file")"
    rm -f "$credentials_file"
    [[ -n "$username" && -n "$token" ]] ||
        fail "Incomplete GHCR credentials."

    log "Logging in to GHCR..."
    printf '%s' "$token" | docker login ghcr.io \
        --username "$username" \
        --password-stdin
}

apply_compose() {
    local compose_args=(up -d --remove-orphans)

    if [[ "$APP_RESTART_REQUIRED" == "true" ]]; then
        compose_args+=(--force-recreate)
    fi
    compose_args+=(bot)

    log "Pulling the configured application image..."
    (
        cd "$APP_DIR"
        docker compose pull bot
        docker compose "${compose_args[@]}"
    )
}

verify_application() {
    local status
    local logs

    for _ in {1..45}; do
        status="$(
            docker inspect --format '{{.State.Status}}' \
                "$CONTAINER_NAME" 2>/dev/null || true
        )"
        logs="$(docker logs "$CONTAINER_NAME" --tail 250 2>&1 || true)"

        if [[ "$status" == "running" ]] &&
            grep -Fq "Sal Resources Manager started" <<<"$logs"; then
            log "Application startup completed."
            return
        fi

        sleep 2
    done

    log "Application failed to complete startup. Recent logs:"
    docker logs "$CONTAINER_NAME" --tail 100 2>&1 || true
    exit 1
}

verify_storage() {
    local expected_mount="$APP_DIR/data|true"
    local actual_mount
    local mount_format

    mount_format='{{range .Mounts}}{{if eq .Destination "/app/data"}}'
    mount_format+='{{.Source}}|{{.RW}}{{end}}{{end}}'

    actual_mount="$(
        docker inspect \
            --format "$mount_format" \
            "$CONTAINER_NAME"
    )"
    [[ "$actual_mount" == "$expected_mount" ]] ||
        fail "Unexpected /app/data mount: '$actual_mount'; expected '$expected_mount'."

    docker exec "$CONTAINER_NAME" sh -c '
        probe=/app/data/.storage-write-test
        trap "rm -f \"$probe\"" EXIT
        : > "$probe"
    '
    log "Persistent /app/data mount is writable by the application user."
}

main() {
    [[ "${EUID}" -eq 0 ]] || fail "Remote configuration must run as root."
    [[ -f "$SOURCE_DIR/compose.yaml" ]] || fail "compose.yaml was not uploaded."
    [[ -f "$SOURCE_DIR/config.ini" ]] || fail "config.ini was not uploaded."
    [[ -f "$SOURCE_DIR/gapi_service_file.json" ]] ||
        fail "gapi_service_file.json was not uploaded."
    require_command cmp
    require_command install
    check_docker
    ensure_compose
    install_configuration
    login_to_ghcr
    apply_compose
    verify_application
    verify_storage
    log "Server configuration is current."
}

main "$@"
