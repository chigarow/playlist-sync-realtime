#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${LOG_DIR:-"$PROJECT_ROOT/logs"}"
PID_FILE="${PID_FILE:-"$LOG_DIR/playlist-sync.pid"}"

mkdir -p "$LOG_DIR"

if [[ ! -s "$PID_FILE" ]]; then
    echo "No playlist-sync PID file found; nothing to stop."
    exit 0
fi

pid="$(cat "$PID_FILE")"

if ! ps -p "$pid" >/dev/null 2>&1; then
    echo "PID $pid from $PID_FILE is not running. Cleaning up PID file."
    rm -f "$PID_FILE"
    exit 0
fi

echo "Stopping playlist-sync (PID $pid)..."
kill "$pid" || true

for _ in {1..10}; do
    if ! ps -p "$pid" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ps -p "$pid" >/dev/null 2>&1; then
    echo "Process still running, forcing termination..."
    kill -9 "$pid" || true
    sleep 1
fi

if ps -p "$pid" >/dev/null 2>&1; then
    echo "Failed to stop playlist-sync (PID $pid)." >&2
    exit 1
fi

rm -f "$PID_FILE"
echo "playlist-sync stopped."
