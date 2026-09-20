#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="/opt/sal-resource-manager"
APP_UID="10001"
APP_GID="10001"
GRAFANA_UID="472"
GRAFANA_GID="0"
CONTAINER_NAME="sal-resource-manager"
SOURCE_DIR="${1:?Source directory is required}"
APP_RESTART_REQUIRED=false
PREPARE_ONLY="${PREPARE_ONLY:-false}"
SWAP_FILE="/swapfile"
SWAP_SIZE_MIB="1024"

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

ensure_swap() {
    require_command swapon
    if swapon --show=NAME --noheadings | grep -q '[^[:space:]]'; then
        log "Swap is already active."
        return
    fi

    require_command mkswap
    if [[ ! -e "$SWAP_FILE" ]]; then
        if command -v fallocate >/dev/null 2>&1; then
            fallocate -l "${SWAP_SIZE_MIB}M" "$SWAP_FILE"
        else
            dd if=/dev/zero of="$SWAP_FILE" bs=1M count="$SWAP_SIZE_MIB" \
                status=none
        fi
    fi
    [[ -f "$SWAP_FILE" ]] || fail "$SWAP_FILE is not a regular file."
    chown root:root "$SWAP_FILE"
    chmod 0600 "$SWAP_FILE"
    mkswap "$SWAP_FILE" >/dev/null
    swapon "$SWAP_FILE"
    if ! awk '$1 == "/swapfile" && $3 == "swap" { found = 1 } END { exit !found }' \
        /etc/fstab; then
        printf '%s\n' '/swapfile none swap sw 0 0' >> /etc/fstab
    fi
    log "Enabled ${SWAP_SIZE_MIB} MiB of persistent swap at $SWAP_FILE."
}

ensure_directories() {
    install -d -m 0750 "$APP_DIR"
    install -d -m 0750 "$APP_DIR/config"
    install -d -m 0750 "$APP_DIR/config/grafana"
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

generate_grafana_config() {
    local destination="$SOURCE_DIR/grafana.ini"

    if ! awk '
        BEGIN { in_security = 0 }
        /^[[:space:]]*\[[^]]+\][[:space:]]*$/ {
            section = $0
            sub(/^[[:space:]]*\[/, "", section)
            sub(/\][[:space:]]*$/, "", section)
            in_security = (tolower(section) == "security")
            if (in_security) print "[security]"
            next
        }
        in_security {
            print
            separator = index($0, "=")
            if (separator == 0) next
            key = substr($0, 1, separator - 1)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
            if (tolower(key) == "admin_user") found_user = 1
            if (tolower(key) == "admin_password") found_password = 1
        }
        END { if (!found_user || !found_password) exit 1 }
    ' "$SOURCE_DIR/config.ini" > "$destination"; then
        rm -f "$destination"
        fail "config.ini must define admin_user and admin_password in [security]."
    fi
    chmod 0600 "$destination"
}

install_configuration() {
    ensure_directories
    generate_grafana_config
    install_managed_file \
        "$SOURCE_DIR/compose.yaml" "$APP_DIR/compose.yaml" \
        root root 0644 false
    install_managed_file \
        "$SOURCE_DIR/Caddyfile" "$APP_DIR/config/Caddyfile" \
        root root 0644 true
    install_managed_file \
        "$SOURCE_DIR/prometheus.yml" "$APP_DIR/config/prometheus.yml" \
        root root 0644 true
    install_managed_file \
        "$SOURCE_DIR/vector.yaml" "$APP_DIR/config/vector.yaml" \
        root root 0644 true
    install_managed_file \
        "$SOURCE_DIR/grafana-datasources.yml" \
        "$APP_DIR/config/grafana/datasources.yml" \
        root root 0644 true
    install_managed_file \
        "$SOURCE_DIR/grafana-dashboards.yml" \
        "$APP_DIR/config/grafana/dashboards.yml" \
        root root 0644 true
    install_managed_file \
        "$SOURCE_DIR/grafana-dashboard.json" \
        "$APP_DIR/config/grafana/sal-resource-manager.json" \
        root root 0644 true
    install_managed_file \
        "$SOURCE_DIR/grafana-system-dashboard.json" \
        "$APP_DIR/config/grafana/sal-resource-manager-system.json" \
        root root 0644 true
    install_managed_file \
        "$SOURCE_DIR/grafana.ini" "$APP_DIR/config/grafana/grafana.ini" \
        "$GRAFANA_UID" "$GRAFANA_GID" 0400 true
    install_managed_file \
        "$SOURCE_DIR/config.ini" "$APP_DIR/config/config.ini" \
        "$APP_UID" "$APP_GID" 0400 true
    install_managed_file \
        "$SOURCE_DIR/google_oauth_token.json" \
        "$APP_DIR/config/google_oauth_token.json" \
        "$APP_UID" "$APP_GID" 0400 true
}

read_config_option() {
    local option="$1"
    local mode="${MODE:-Release}"

    awk -v wanted="$option" -v wanted_section="$mode" '
        BEGIN { section = "default" }
        /^[[:space:]]*[;#]/ { next }
        /^[[:space:]]*\[[^]]+\][[:space:]]*$/ {
            section = $0
            sub(/^[[:space:]]*\[/, "", section)
            sub(/\][[:space:]]*$/, "", section)
            section = tolower(section)
            next
        }
        {
            separator = index($0, "=")
            if (separator == 0) next
            key = substr($0, 1, separator - 1)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
            if (tolower(key) != tolower(wanted)) next
            value = substr($0, separator + 1)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            if (section == "default") {
                default_value = value
                has_default = 1
            }
            if (section == tolower(wanted_section)) {
                selected_value = value
                has_selected = 1
            }
        }
        END {
            if (has_selected) print selected_value
            else if (has_default) print default_value
        }
    ' "$APP_DIR/config/config.ini"
}

validate_public_hostname() {
    local hostname="$1"
    local label
    local labels

    [[ ${#hostname} -le 253 ]] || return 1
    [[ "$hostname" == *.* ]] || return 1
    [[ ! "$hostname" =~ ^[0-9.]+$ ]] || return 1
    IFS='.' read -r -a labels <<<"$hostname"
    for label in "${labels[@]}"; do
        [[ "$label" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$ ]] ||
            return 1
    done
}

configure_caddy_environment() {
    local environment_file="$SOURCE_DIR/caddy.env"
    local public_host
    local webhook_path
    local webhook_url

    webhook_url="$(read_config_option WEBHOOK_URL)"
    [[ "$webhook_url" =~ ^https://([^/:]+):8443(/[^?#]*)$ ]] ||
        fail "WEBHOOK_URL must use a public DNS name and HTTPS port 8443."
    public_host="${BASH_REMATCH[1]}"
    webhook_path="${BASH_REMATCH[2]}"
    validate_public_hostname "$public_host" ||
        fail "WEBHOOK_URL host must be a valid public DNS name, not an IP address."
    [[ "$webhook_path" =~ ^/[A-Za-z0-9._~/-]+/$ ]] ||
        fail "WEBHOOK_URL path must end with '/' and contain only safe URL path characters."

    printf 'CADDY_PUBLIC_HOST=%s\nCADDY_WEBHOOK_PATH=%s\n' \
        "$public_host" "$webhook_path" > "$environment_file"
    chmod 0600 "$environment_file"
    install_managed_file \
        "$environment_file" "$APP_DIR/.env" root root 0600 true
}

configure_firewall() {
    if ! command -v ufw >/dev/null 2>&1; then
        log "UFW is not installed; skipping the host firewall rule."
        return
    fi
    if ! ufw status | grep -Fq "Status: active"; then
        log "UFW is inactive; skipping the host firewall rule."
        return
    fi

    ufw allow 80/tcp >/dev/null
    ufw allow 8443/tcp >/dev/null
    ufw allow 8443/udp >/dev/null
    ufw --force delete allow 3000/tcp >/dev/null 2>&1 || true
    log "UFW allows ACME HTTP and Caddy HTTPS on port 8443."
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

pull_images() {
    log "Pulling the configured service images..."
    (
        cd "$APP_DIR"
        docker compose pull \
            bot node-exporter prometheus grafana victorialogs vector caddy
    )
}

apply_compose() {
    local compose_args=(up -d --remove-orphans)

    if [[ "$APP_RESTART_REQUIRED" == "true" ]]; then
        compose_args+=(--force-recreate)
    fi
    compose_args+=(bot node-exporter prometheus grafana victorialogs vector caddy)

    (
        cd "$APP_DIR"
        docker compose "${compose_args[@]}"
    )
}

verify_application() {
    local restart_count
    local status
    local logs

    for _ in {1..45}; do
        status="$(
            docker inspect --format '{{.State.Status}}' \
                "$CONTAINER_NAME" 2>/dev/null || true
        )"
        logs="$(docker logs "$CONTAINER_NAME" --tail 250 2>&1 || true)"

        if [[ "$status" == "running" ]] &&
            grep -Fq "Sal Resources Manager started" <<<"$logs" &&
            grep -Fq "Uvicorn running on http://0.0.0.0:8443" <<<"$logs"; then
            log "Application startup completed."
            return
        fi

        restart_count="$(
            docker inspect --format '{{.RestartCount}}' \
                "$CONTAINER_NAME" 2>/dev/null || true
        )"
        if [[ "$status" == "restarting" || "$status" == "exited" ||
            "$status" == "dead" ||
            "$restart_count" =~ ^[1-9][0-9]*$ ]]; then
            stop_failed_application
        fi

        sleep 2
    done

    stop_failed_application
}

stop_failed_application() {
    log "Application failed to complete startup. Recent logs:"
    docker logs "$CONTAINER_NAME" --tail 100 2>&1 || true
    if docker stop "$CONTAINER_NAME" >/dev/null 2>&1; then
        log "Stopped the failed application to prevent a restart loop."
    fi
    fail "Application startup verification failed."
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

verify_auxiliary_services() {
    local container
    local status

    for container in \
        sal-resource-manager-prometheus \
        sal-resource-manager-grafana \
        sal-resource-manager-victorialogs \
        sal-resource-manager-vector \
        sal-resource-manager-caddy; do
        status="$(docker inspect --format '{{.State.Status}}' "$container")"
        [[ "$status" == "running" ]] ||
            fail "Container $container is not running: $status"
    done

    local victorialogs_mount
    victorialogs_mount="$(
        docker inspect --format \
            '{{range .Mounts}}{{if eq .Destination "/victoria-logs-data"}}{{.Name}}|{{.RW}}{{end}}{{end}}' \
            sal-resource-manager-victorialogs
    )"
    [[ "$victorialogs_mount" == \
        "sal-resource-manager_victorialogs-data|true" ]] ||
        fail "Unexpected VictoriaLogs data mount: '$victorialogs_mount'."
    docker exec sal-resource-manager-caddy \
        caddy validate --config /etc/caddy/Caddyfile >/dev/null
    log "Caddy, Prometheus, Grafana, VictoriaLogs, and Vector are running."
}

main() {
    [[ "${EUID}" -eq 0 ]] || fail "Remote configuration must run as root."
    [[ -f "$SOURCE_DIR/compose.yaml" ]] || fail "compose.yaml was not uploaded."
    [[ -f "$SOURCE_DIR/prometheus.yml" ]] ||
        fail "prometheus.yml was not uploaded."
    [[ -f "$SOURCE_DIR/vector.yaml" ]] ||
        fail "vector.yaml was not uploaded."
    [[ -f "$SOURCE_DIR/grafana-datasources.yml" ]] ||
        fail "grafana-datasources.yml was not uploaded."
    [[ -f "$SOURCE_DIR/grafana-dashboards.yml" ]] ||
        fail "grafana-dashboards.yml was not uploaded."
    [[ -f "$SOURCE_DIR/grafana-dashboard.json" ]] ||
        fail "grafana-dashboard.json was not uploaded."
    [[ -f "$SOURCE_DIR/grafana-system-dashboard.json" ]] ||
        fail "grafana-system-dashboard.json was not uploaded."
    [[ -f "$SOURCE_DIR/Caddyfile" ]] || fail "Caddyfile was not uploaded."
    [[ -f "$SOURCE_DIR/config.ini" ]] || fail "config.ini was not uploaded."
    [[ -f "$SOURCE_DIR/google_oauth_token.json" ]] ||
        fail "google_oauth_token.json was not uploaded."
    require_command cmp
    require_command install
    check_docker
    ensure_compose
    ensure_swap
    install_configuration
    configure_caddy_environment
    configure_firewall
    login_to_ghcr
    pull_images
    if [[ "$PREPARE_ONLY" == "true" ]]; then
        log "Server preparation completed without starting services."
        return
    fi
    apply_compose
    verify_application
    verify_storage
    verify_auxiliary_services
    log "Server configuration is current."
}

main "$@"
