#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

VENV_API_DIR="${VENV_API_DIR:-$REPO_ROOT/.venv-api}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8088}"

# Runtime paths
RUNTIME_DIR="$REPO_ROOT/storage/runtime"
LOG_DIR="$REPO_ROOT/storage/logs"
PID_FILE="$RUNTIME_DIR/content-short-api.pid"
LOG_FILE="$LOG_DIR/content-short-api.log"

log() {
  printf '[service] %s\n' "$*" >&2
}

port_pids() {
  lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true
}

wait_for_port_free() {
  local attempt
  for attempt in $(seq 1 20); do
    if [ -z "$(port_pids)" ]; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

restart_existing_listener() {
  local pids
  pids="$(port_pids)"
  [ -n "$pids" ] || return 0

  log "Port $PORT is already in use by PID(s): $(printf '%s' "$pids" | tr '\n' ' ')"
  log "Stopping existing listener before starting API"
  printf '%s\n' "$pids" | xargs kill 2>/dev/null || true

  if ! wait_for_port_free; then
    pids="$(port_pids)"
    if [ -n "$pids" ]; then
      log "Existing listener did not stop cleanly; forcing PID(s): $(printf '%s' "$pids" | tr '\n' ' ')"
      printf '%s\n' "$pids" | xargs kill -9 2>/dev/null || true
      wait_for_port_free || {
        log "ERROR: Port $PORT is still in use after restart attempt."
        exit 1
      }
    fi
  fi
}

# Usage function
usage() {
  cat <<EOF
Usage:
  ./run_service.sh [--background|--status|--stop|--help]

Options:
  --background   Start API in background and wait for /health
  --status       Show PID, port, and health status
  --stop         Stop API process
  --help         Show this help
EOF
}

# Helper functions
pid_alive() {
  local pid="${1:-}"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  [ -f "$PID_FILE" ] && cat "$PID_FILE" || true
}

health_ok() {
  curl -fsS "http://$HOST:$PORT/health" >/dev/null 2>&1
}

wait_for_health() {
  local attempt
  for attempt in $(seq 1 30); do
    if health_ok; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# Parse mode before setup
MODE="foreground"
case "${1:-}" in
  --background) MODE="background"; shift ;;
  --status) MODE="status"; shift ;;
  --stop) MODE="stop"; shift ;;
  --help|-h) usage; exit 0 ;;
  "") ;;
  *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
esac

# Check for extra arguments
if [ $# -gt 0 ]; then
  log "ERROR: Extra arguments: $@"
  usage
  exit 1
fi

# Load .env if exists
if [ -f "$REPO_ROOT/.env" ]; then
  log "Loading .env"
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/.env"
  set +a
fi

# Ensure venv exists
if [ ! -x "$VENV_API_DIR/bin/python" ]; then
  log "Creating API virtualenv: $VENV_API_DIR"
  python3 -m venv "$VENV_API_DIR"
fi

# Install requirements (only in foreground mode, or skip for status/stop)
if [ "$MODE" = "foreground" ]; then
  log "Installing API requirements"
  "$VENV_API_DIR/bin/python" -m pip install -r "$REPO_ROOT/requirements.txt"
fi

export CONTENT_SHORT_APP_DIR="${CONTENT_SHORT_APP_DIR:-$REPO_ROOT}"
export CONTENT_SHORT_STORAGE_DIR="${CONTENT_SHORT_STORAGE_DIR:-$REPO_ROOT/storage}"
export CONTENT_SHORT_API_TOKEN="${CONTENT_SHORT_API_TOKEN:-change-me}"
export WEBHOOK_URL="${WEBHOOK_URL:-http://$HOST:$PORT}"
export CONTENT_SHORT_BASE_URL="${CONTENT_SHORT_BASE_URL:-$WEBHOOK_URL}"
export CV_PYTHON_BIN="${CV_PYTHON_BIN:-$VENV_API_DIR/bin/python}"
export VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv-transcript-api}"
export SUBTITLE_AUTOCAPTIONS_PYTHON="${SUBTITLE_AUTOCAPTIONS_PYTHON:-$VENV_DIR/bin/python}"

# Add Homebrew paths to PATH for ffmpeg lookup
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:/opt/homebrew/bin:$PATH"

# Set FFMPEG_BIN with Homebrew fallback
if [ -z "${FFMPEG_BIN:-}" ]; then
  if [ -x "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg" ]; then
    export FFMPEG_BIN="/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
  elif [ -x "/opt/homebrew/bin/ffmpeg" ]; then
    export FFMPEG_BIN="/opt/homebrew/bin/ffmpeg"
  else
    export FFMPEG_BIN="$(command -v ffmpeg || true)"
  fi
fi

if [ -z "$FFMPEG_BIN" ] || [ ! -x "$FFMPEG_BIN" ]; then
  log "WARNING: ffmpeg not found in PATH. /health may report ffmpeg=false and rendering may fail."
fi

log "App dir: $CONTENT_SHORT_APP_DIR"
log "Storage dir: $CONTENT_SHORT_STORAGE_DIR"
log "Output dir: $CONTENT_SHORT_STORAGE_DIR/free-viral-shorts"
if [ -n "${CONTENT_SHORT_API_TOKEN:-}" ]; then
  log "API token: set"
else
  log "API token: not-set"
fi
log "yt-dlp: $(command -v yt-dlp || true)"
log "ffmpeg: $FFMPEG_BIN"

log "Starting Content Short API"
log "Local URL: http://$HOST:$PORT"
log "Public base URL: $CONTENT_SHORT_BASE_URL"

# Enable subtitle API by default since n8n now calls /subtitle/burn
export SUBTITLE_ENABLE_SUBTITLE_API="${SUBTITLE_ENABLE_SUBTITLE_API:-true}"

# Handle mode
case "$MODE" in
  status)
    # Print status
    log "PID file: $PID_FILE"
    pid=$(read_pid)
    if [ -n "$pid" ]; then
      log "PID: $pid"
      if pid_alive "$pid"; then
        log "PID alive: yes"
      else
        log "PID alive: no (stale PID file)"
      fi
    else
      log "PID: none"
    fi
    
    # Check port
    pids=$(port_pids)
    if [ -n "$pids" ]; then
      log "Port $PORT listening: yes (PIDs: $pids)"
    else
      log "Port $PORT listening: no"
    fi
    
    # Check health
    if health_ok; then
      log "Health OK: yes"
      exit 0
    else
      log "Health OK: no"
      exit 1
    fi
    ;;
  
  stop)
    pid=$(read_pid)
    if [ -n "$pid" ] && pid_alive "$pid"; then
      log "Stopping PID $pid"
      kill "$pid" || true
      
      # Wait briefly
      local attempt
      for attempt in $(seq 1 10); do
        if ! pid_alive "$pid"; then
          break
        fi
        sleep 0.5
      done
      
      # Force kill if still alive
      if pid_alive "$pid"; then
        log "Force killing PID $pid"
        kill -9 "$pid" || true
      fi
    else
      log "No running PID found"
    fi
    
    # Remove PID file
    if [ -f "$PID_FILE" ]; then
      rm -f "$PID_FILE"
      log "Removed PID file"
    fi
    
    # Also restart existing listener on port if any
    restart_existing_listener || true
    
    log "Service stopped"
    exit 0
    ;;
  
  background)
    # Create directories
    mkdir -p "$RUNTIME_DIR" "$LOG_DIR"
    
    # Check if already running
    pid=$(read_pid)
    if [ -n "$pid" ] && pid_alive "$pid" && health_ok; then
      log "Service already running with PID $pid"
      log "Health OK"
      exit 0
    fi
    
    # Stop any existing
    restart_existing_listener
    
    # Start in background
    log "Starting API in background..."
    nohup "$VENV_API_DIR/bin/uvicorn" api_server:app --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    
    # Wait for health
    if ! wait_for_health; then
      log "ERROR: API did not become healthy."
      log "Last log lines:"
      tail -n 80 "$LOG_FILE" >&2 || true
      exit 1
    fi
    
    log "Service started successfully"
    log "Health URL: http://$HOST:$PORT/health"
    log "Log file: $LOG_FILE"
    exit 0
    ;;
  
  foreground)
    # Default: run in foreground
    restart_existing_listener
    exec "$VENV_API_DIR/bin/uvicorn" api_server:app --host "$HOST" --port "$PORT"
    ;;
esac
