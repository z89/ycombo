#!/usr/bin/env bash
# YCOMBO daemon — runs ycombo.py immediately, then every 5 minutes.

SCRIPT="$(dirname "$(realpath "$0")")/ycombo.py"

while true; do
    python3 "$SCRIPT" > /dev/null 2>&1
    xdotool search --name "Eww - ycombo" windowlower 2>/dev/null || true
    sleep 300
done
