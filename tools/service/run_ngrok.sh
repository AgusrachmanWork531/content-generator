#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8088}"
NGROK_TARGET_PORT="${NGROK_TARGET_PORT:-$PORT}"
NGROK_DOMAIN="${NGROK_DOMAIN:-}"
NGROK_CONFIG_DIR="${NGROK_CONFIG_DIR:-$REPO_ROOT/.local-secrets/ngrok}"
NGROK_CONFIG_FILE="${NGROK_CONFIG_FILE:-$NGROK_CONFIG_DIR/ngrok.yml}"

log() {
  printf '[ngrok] %s\n' "$*" >&2
}

if [ -f "$REPO_ROOT/.env" ]; then
  log "Loading .env"
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/.env"
  set +a
fi

NGROK_AUTHTOKEN="${NGROK_TOKEN:-${NGORK_TOKEN:-${NGROK_AUTHTOKEN:-}}}"

if [ -z "$NGROK_AUTHTOKEN" ]; then
  log "ERROR: Set NGROK_TOKEN in .env before running this script."
  log "Compatibility fallback NGORK_TOKEN is supported, but NGROK_TOKEN is preferred."
  exit 1
fi

NGROK_BIN="${NGROK_BIN:-$(command -v ngrok || true)}"
if [ -z "$NGROK_BIN" ] && [ -x /opt/homebrew/bin/ngrok ]; then
  NGROK_BIN="/opt/homebrew/bin/ngrok"
fi

if [ -z "$NGROK_BIN" ]; then
  log "ERROR: ngrok binary not found. Set NGROK_BIN=/path/to/ngrok or install ngrok."
  exit 1
fi

umask 077
mkdir -p "$NGROK_CONFIG_DIR"
chmod 700 "$REPO_ROOT/.local-secrets" "$NGROK_CONFIG_DIR" 2>/dev/null || true

cat >"$NGROK_CONFIG_FILE" <<EOF
version: "3"
agent:
  authtoken: $NGROK_AUTHTOKEN
EOF
chmod 600 "$NGROK_CONFIG_FILE"

log "Using isolated config: $NGROK_CONFIG_FILE"

if [ "${1:-}" = "--init-only" ]; then
  log "Initialized isolated ngrok config only."
  exit 0
fi

log "Forwarding: http://$HOST:$NGROK_TARGET_PORT"

if [ -n "$NGROK_DOMAIN" ]; then
  log "Requested domain: https://$NGROK_DOMAIN"
  exec "$NGROK_BIN" http "$NGROK_TARGET_PORT" \
    --config "$NGROK_CONFIG_FILE" \
    --url="https://$NGROK_DOMAIN"
fi

log "No NGROK_DOMAIN set; ngrok will allocate a temporary URL."
exec "$NGROK_BIN" http "$NGROK_TARGET_PORT" \
  --config "$NGROK_CONFIG_FILE"
