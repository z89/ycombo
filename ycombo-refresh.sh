#!/usr/bin/env bash
touch /tmp/ycombo_loading
python3 /home/archie/Documents/Github-Projects/ycombo/ycombo.py
rm -f /tmp/ycombo_loading
xdotool search --name "Eww - ycombo" windowlower 2>/dev/null || true
