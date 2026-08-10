#!/usr/bin/env bash

set -Eeuo pipefail

PUBLIC_IP="${1:?Public IPv4 address is required}"
CERTIFICATE_PATH="${2:?Certificate path is required}"
PRIVATE_KEY_PATH="${3:?Private key path is required}"
OWNER="${4:-10001}"
GROUP="${5:-10001}"
VALIDITY_DAYS="${WEBHOOK_CERTIFICATE_VALIDITY_DAYS:-365}"
RENEW_BEFORE_SECONDS="${WEBHOOK_CERTIFICATE_RENEW_BEFORE_SECONDS:-2592000}"

fail() {
    printf '[certificate] ERROR: %s\n' "$*" >&2
    exit 1
}

validate_ipv4() {
    local address="$1"
    local octets
    local octet

    IFS='.' read -r -a octets <<<"$address"
    [[ "${#octets[@]}" -eq 4 ]] || return 1
    for octet in "${octets[@]}"; do
        [[ "$octet" =~ ^(0|[1-9][0-9]{0,2})$ ]] || return 1
        ((10#$octet <= 255)) || return 1
    done
}

certificate_is_current() {
    local certificate_public_key
    local private_public_key
    local san_addresses

    [[ -s "$CERTIFICATE_PATH" && -s "$PRIVATE_KEY_PATH" ]] || return 1
    openssl x509 \
        -checkend "$RENEW_BEFORE_SECONDS" \
        -noout \
        -in "$CERTIFICATE_PATH" >/dev/null 2>&1 || return 1

    san_addresses="$(
        openssl x509 \
            -in "$CERTIFICATE_PATH" \
            -noout \
            -ext subjectAltName 2>/dev/null |
            grep -oE 'IP Address:[0-9.]+' |
            cut -d: -f2
    )" || return 1
    grep -Fxq "$PUBLIC_IP" <<<"$san_addresses" || return 1

    certificate_public_key="$(
        openssl x509 -in "$CERTIFICATE_PATH" -pubkey -noout 2>/dev/null
    )" || return 1
    private_public_key="$(
        openssl pkey -in "$PRIVATE_KEY_PATH" -pubout 2>/dev/null
    )" || return 1
    [[ "$certificate_public_key" == "$private_public_key" ]]
}

validate_ipv4 "$PUBLIC_IP" || fail "Invalid public IPv4 address: $PUBLIC_IP"
command -v openssl >/dev/null 2>&1 || fail "OpenSSL is required."
[[ "$VALIDITY_DAYS" =~ ^[1-9][0-9]*$ ]] || fail "Invalid validity period."
[[ "$RENEW_BEFORE_SECONDS" =~ ^[0-9]+$ ]] || fail "Invalid renewal window."
[[ "$(dirname "$CERTIFICATE_PATH")" == "$(dirname "$PRIVATE_KEY_PATH")" ]] ||
    fail "The certificate and private key must use the same directory."

CERTIFICATE_DIR="$(dirname "$CERTIFICATE_PATH")"
install -d -o "$OWNER" -g "$GROUP" -m 0750 "$CERTIFICATE_DIR"

if certificate_is_current; then
    chown "$OWNER:$GROUP" "$CERTIFICATE_PATH" "$PRIVATE_KEY_PATH"
    chmod 0444 "$CERTIFICATE_PATH"
    chmod 0400 "$PRIVATE_KEY_PATH"
    printf 'current\n'
    exit 0
fi

TEMP_DIR="$(mktemp -d "$CERTIFICATE_DIR/.webhook-certificate.XXXXXX")"
TEMP_CERTIFICATE="$TEMP_DIR/webhook.pem"
TEMP_PRIVATE_KEY="$TEMP_DIR/webhook.key"

cleanup() {
    rm -f -- "$TEMP_CERTIFICATE" "$TEMP_PRIVATE_KEY"
    rmdir -- "$TEMP_DIR" 2>/dev/null || true
}
trap cleanup EXIT

openssl req \
    -x509 \
    -newkey rsa:2048 \
    -sha256 \
    -nodes \
    -days "$VALIDITY_DAYS" \
    -keyout "$TEMP_PRIVATE_KEY" \
    -out "$TEMP_CERTIFICATE" \
    -subj "/CN=$PUBLIC_IP" \
    -addext "subjectAltName=IP:$PUBLIC_IP" \
    >/dev/null 2>&1

openssl x509 -in "$TEMP_CERTIFICATE" -noout >/dev/null 2>&1 ||
    fail "Generated certificate could not be read."
openssl pkey -in "$TEMP_PRIVATE_KEY" -noout >/dev/null 2>&1 ||
    fail "Generated private key could not be read."

chown "$OWNER:$GROUP" "$TEMP_CERTIFICATE" "$TEMP_PRIVATE_KEY"
chmod 0444 "$TEMP_CERTIFICATE"
chmod 0400 "$TEMP_PRIVATE_KEY"
mv -f -- "$TEMP_PRIVATE_KEY" "$PRIVATE_KEY_PATH"
mv -f -- "$TEMP_CERTIFICATE" "$CERTIFICATE_PATH"

printf 'generated\n'
