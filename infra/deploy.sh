#!/bin/sh

set -eu

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
docker compose pull bot

install -d -m 0750 config/grafana
for filename in $GRAFANA_FILES; do
    if ! cmp -s "$RELEASE_DIR/config/grafana/$filename" "config/grafana/$filename"; then
        # Keep this marker on failure so the next deploy retries recreation.
        touch config/grafana/.recreate-required
        install -m 0644 "$RELEASE_DIR/config/grafana/$filename" "config/grafana/$filename"
    fi
done

docker compose up -d --force-recreate bot
if [ -f config/grafana/.recreate-required ]; then
    docker compose up -d --no-deps --force-recreate --wait --wait-timeout 120 grafana
    rm config/grafana/.recreate-required
fi
docker image prune -f
