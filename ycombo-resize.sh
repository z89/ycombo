#!/usr/bin/env bash
# YCOMBO — resize handler
# Called by: eww onscroll (passes "up"/"down"), or keybinds (+w/-w/+h/-h)
# Scroll = height, Shift+scroll = width (detected via evtest)

CONFIG_FILE="$HOME/.config/ycombo/config.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EWW_CFG="$SCRIPT_DIR/eww"
YUCK_FILE="$EWW_CFG/eww.yuck"

SCROLL_STEP=30
KEY_HEIGHT_STEP=50
KEY_WIDTH_STEP=80
MIN_WIDTH=500
MAX_WIDTH=1920
MIN_SCROLL=150
MAX_SCROLL=1400

mkdir -p "$(dirname "$CONFIG_FILE")"

# Read current config (pure bash — no python spawn on scroll hot path)
width=860
scroll_height=420
if [[ -f "$CONFIG_FILE" ]]; then
    while IFS=: read -r key val; do
        key="${key//[\" ]/}"
        val="${val//[^0-9]/}"
        case "$key" in
            width) width="${val:-860}" ;;
            scroll_height) scroll_height="${val:-420}" ;;
        esac
    done < <(tr '{},\n' '\n\n\n\n' < "$CONFIG_FILE")
fi

# Detect shift key for scroll events (up/down)
shift_held=false
if [[ "$1" == up || "$1" == down ]] && command -v evtest &>/dev/null; then
    for dev in /dev/input/by-id/*-kbd; do
        [[ -e "$dev" ]] || continue
        if evtest --query "$dev" EV_KEY KEY_LEFTSHIFT 2>/dev/null; then
            shift_held=true; break
        fi
        if evtest --query "$dev" EV_KEY KEY_RIGHTSHIFT 2>/dev/null; then
            shift_held=true; break
        fi
    done
fi

width_changed=false
height_changed=false

case "${1:-}" in
    down)
        if [[ "$shift_held" == true ]]; then
            width=$((width + SCROLL_STEP)); width_changed=true
        else
            scroll_height=$((scroll_height + SCROLL_STEP)); height_changed=true
        fi ;;
    up)
        if [[ "$shift_held" == true ]]; then
            width=$((width - SCROLL_STEP)); width_changed=true
        else
            scroll_height=$((scroll_height - SCROLL_STEP)); height_changed=true
        fi ;;
    +h) scroll_height=$((scroll_height + KEY_HEIGHT_STEP)); height_changed=true ;;
    -h) scroll_height=$((scroll_height - KEY_HEIGHT_STEP)); height_changed=true ;;
    +w) width=$((width + KEY_WIDTH_STEP)); width_changed=true ;;
    -w) width=$((width - KEY_WIDTH_STEP)); width_changed=true ;;
    *)  echo "Usage: $0 {up|down|+w|-w|+h|-h}" >&2; exit 1 ;;
esac

# Clamp
(( width < MIN_WIDTH )) && width=$MIN_WIDTH
(( width > MAX_WIDTH )) && width=$MAX_WIDTH
(( scroll_height < MIN_SCROLL )) && scroll_height=$MIN_SCROLL
(( scroll_height > MAX_SCROLL )) && scroll_height=$MAX_SCROLL

# Save
printf '{"width": %d, "scroll_height": %d}\n' "$width" "$scroll_height" > "$CONFIG_FILE"

# Apply height (dynamic via eww variable)
if [[ "$height_changed" == true ]]; then
    eww --config "$EWW_CFG" update "ycombo-scroll-height=$scroll_height"
fi

# Apply width (requires close + rewrite geometry + reopen)
if [[ "$width_changed" == true ]]; then
    sed -i "s/:width \"[0-9]*px\"/:width \"${width}px\"/" "$YUCK_FILE"
    eww --config "$EWW_CFG" close ycombo
    eww --config "$EWW_CFG" open ycombo
    eww --config "$EWW_CFG" update "ycombo-scroll-height=$scroll_height"
fi
