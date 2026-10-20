#!/bin/sh

set -eu

cleanup_old_images() {
    repository=${BOT_IMAGE%:*}
    rollback_image="$repository:rollback"
    current_image=$(docker image inspect --format '{{.Id}}' "$BOT_IMAGE") || return 1
    old_rollback_id=$(docker image inspect --format '{{.Id}}' "$rollback_image" 2>/dev/null) || old_rollback_id=
    if [ -n "$previous_image" ] && [ "$previous_image" != "$current_image" ]; then
        docker image tag "$previous_image" "$rollback_image" || return 1
    fi
    rollback_id=$(docker image inspect --format '{{.Id}}' "$rollback_image" 2>/dev/null) || rollback_id=
    images=$(docker image ls --no-trunc --format '{{.Repository}}:{{.Tag}} {{.ID}}' "$repository") || return 1
    printf '%s\n' "$images" | while read -r reference image_id; do
        [ -n "$image_id" ] || continue
        [ "$image_id" != "$current_image" ] || continue
        [ "$image_id" != "$rollback_id" ] || continue
        containers=$(docker ps -aq --filter "ancestor=$image_id") || return 1
        [ -z "$containers" ] || continue
        docker image rm "$reference" || return 1
    done || return 1
    if [ -n "$old_rollback_id" ] && [ "$old_rollback_id" != "$current_image" ] && [ "$old_rollback_id" != "$rollback_id" ]; then
        # Retagging rollback can leave its former image without a repository tag.
        if tags=$(docker image inspect --format '{{json .RepoTags}}' "$old_rollback_id" 2>/dev/null); then
            containers=$(docker ps -aq --filter "ancestor=$old_rollback_id") || return 1
            if [ "$tags" = '[]' ] && [ -z "$containers" ]; then
                docker image rm "$old_rollback_id" || return 1
            fi
        fi
    fi
}

RELEASE_DIR=${1:?Release directory is required}
APP_DIR=${2:-/opt/sal-resource-manager}
GRAFANA_FILES="datasources.yml dashboards.yml sal-resource-manager.json sal-resource-manager-system.json sal-resource-manager-logs.json"

# Validate the complete upload before changing the running installation.
test -s "$RELEASE_DIR/release-image.txt"
for filename in $GRAFANA_FILES; do
    test -s "$RELEASE_DIR/config/grafana/$filename"
done
BOT_IMAGE=$(cat "$RELEASE_DIR/release-image.txt")
export BOT_IMAGE

cd "$APP_DIR"
previous_container=$(docker compose ps -aq bot)
previous_image=
if [ -n "$previous_container" ]; then
    previous_image=$(docker inspect --format '{{.Image}}' "$previous_container")
fi
docker compose pull bot

install -d -m 0750 config/grafana
for filename in $GRAFANA_FILES; do
    if ! cmp -s "$RELEASE_DIR/config/grafana/$filename" "config/grafana/$filename"; then
        # Keep this marker on failure so the next deploy retries recreation.
        touch config/grafana/.recreate-required
        install -m 0644 "$RELEASE_DIR/config/grafana/$filename" "config/grafana/$filename"
    fi
done

docker compose up -d --force-recreate --wait --wait-timeout 120 bot
if [ -f config/grafana/.recreate-required ]; then
    docker compose up -d --no-deps --force-recreate --wait --wait-timeout 120 grafana
    rm config/grafana/.recreate-required
fi
if ! cleanup_old_images; then
    echo 'Deployment succeeded, but old application images could not be fully cleaned up.' >&2
fi
