#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${LOG_DIR:-"$PROJECT_ROOT/logs"}"
PID_FILE="${PID_FILE:-"$LOG_DIR/playlist-sync.pid"}"
LOG_FILE="${LOG_FILE:-"$LOG_DIR/playlist-sync.log"}"
PYTHON_BIN="${PYTHON_BIN:-python}"
APP_ENTRY="${APP_ENTRY:-"$PROJECT_ROOT/app.py"}"

mkdir -p "$LOG_DIR"

if [[ -s "$PID_FILE" ]] && ps -p "$(cat "$PID_FILE")" >/dev/null 2>&1; then
    echo "playlist-sync already running with PID $(cat "$PID_FILE")"
    exit 0
fi

cd "$PROJECT_ROOT"

if [[ -d "$PROJECT_ROOT/.venv" ]]; then
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.venv/bin/activate"
fi

nohup "$PYTHON_BIN" "$APP_ENTRY" >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
echo "playlist-sync started in background (PID $!). Logs: $LOG_FILE"
