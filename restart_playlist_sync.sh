#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${LOG_DIR:-"$PROJECT_ROOT/logs"}"
PID_FILE="${PID_FILE:-"$LOG_DIR/playlist-sync.pid"}"

mkdir -p "$LOG_DIR"

LOG_DIR="$LOG_DIR" PID_FILE="$PID_FILE" "$PROJECT_ROOT/stop_playlist_sync.sh"

echo "Starting playlist-sync..."
"$PROJECT_ROOT/run_playlist_sync.sh"
