#!/usr/bin/env bash
# YCOMBO — start the GTK widget daemon

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${XDG_RUNTIME_DIR:-/tmp}/ycombo/daemon.pid"

# Kill stale daemon
if [[ -f "$PID_FILE" ]]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
fi

# Start daemon
python3 "$SCRIPT_DIR/ycombo.py" --daemon &
disown
