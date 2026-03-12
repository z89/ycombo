#!/usr/bin/env bash
# YCOMBO — toggle: kill running daemon or start a new one

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PID="$(pgrep -f 'ycombo\.py --daemon')"

if [[ -n "$PID" ]]; then
    kill -9 "$PID" 2>/dev/null
else
    "$SCRIPT_DIR/ycombo-start.sh"
fi
