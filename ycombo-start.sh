#!/usr/bin/env bash
# YCOMBO — startup: (re)start daemon and eww widget

# Kill stale daemon and relaunch
pkill -f ycombo-daemon.sh 2>/dev/null || true
/home/archie/Documents/Github-Projects/ycombo/ycombo-daemon.sh &

# Kill stale eww and reopen
EWW_CFG="/home/archie/Documents/Github-Projects/ycombo/eww"
eww --config "$EWW_CFG" kill 2>/dev/null || true
sleep 2
eww --config "$EWW_CFG" open ycombo
sleep 1
xdotool search --name "Eww - ycombo" windowlower 2>/dev/null || true
