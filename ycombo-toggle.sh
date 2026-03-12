#!/usr/bin/env bash
# YCOMBO — toggle show/hide

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${XDG_RUNTIME_DIR:-/tmp}/ycombo/daemon.pid"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill -USR2 "$(cat "$PID_FILE")"
else
    "$SCRIPT_DIR/ycombo-start.sh"
fi
