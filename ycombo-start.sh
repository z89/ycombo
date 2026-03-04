#!/usr/bin/env bash
# YCOMBO — startup: (re)start daemon and eww widget

YCOMBO_DIR="/home/archie/Documents/Github-Projects/ycombo"
EWW_CFG="$YCOMBO_DIR/eww"

# Kill stale data daemon and relaunch
pkill -f ycombo-daemon.sh 2>/dev/null || true
"$YCOMBO_DIR/ycombo-daemon.sh" &

# Kill stale resize daemon
pkill -f ycombo-resize.py 2>/dev/null || true

# Kill stale eww and reopen
eww --config "$EWW_CFG" kill 2>/dev/null || true
sleep 2
eww --config "$EWW_CFG" open ycombo
sleep 1
xdotool search --name "Eww - ycombo" windowlower 2>/dev/null || true

# Start resize daemon (finds window, applies saved width, then enters XRecord loop)
python3 "$YCOMBO_DIR/ycombo-resize.py" &
