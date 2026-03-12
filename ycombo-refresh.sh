#!/usr/bin/env bash
# YCOMBO — trigger refresh via daemon signal

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${XDG_RUNTIME_DIR:-/tmp}/ycombo/daemon.pid"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill -USR1 "$(cat "$PID_FILE")"
else
    python3 "$SCRIPT_DIR/ycombo.py" --refresh
fi
