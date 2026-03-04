#!/usr/bin/env bash
# YCOMBO — install script
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EWW_CFG="$SCRIPT_DIR/eww"
I3_CONFIG="$HOME/.config/i3/config"

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[x]${NC} $1"; exit 1; }

info "Installing YCOMBO..."

# 1. Check deps
for dep in eww xdotool python3; do
    if ! command -v "$dep" &>/dev/null; then
        case "$dep" in
            eww)     warn "eww not found — installing via yay..."; yay -S --noconfirm eww ;;
            xdotool) warn "xdotool not found — installing..."; sudo pacman -S --noconfirm xdotool ;;
            python3) error "python3 not found. Install it first." ;;
        esac
    else
        info "$dep OK"
    fi
done

if ! python3 -c "import requests" &>/dev/null; then
    warn "python-requests not found — installing..."
    sudo pacman -S --noconfirm python-requests
else
    info "python-requests OK"
fi

# 2. Permissions
chmod +x "$SCRIPT_DIR/ycombo.py" \
         "$SCRIPT_DIR/ycombo-daemon.sh" \
         "$SCRIPT_DIR/ycombo-refresh.sh" \
         "$SCRIPT_DIR/ycombo-start.sh" \
         "$SCRIPT_DIR/ycombo-toggle.sh"
info "Script permissions set."

# 3. Initial data fetch
info "Fetching initial data..."
python3 "$SCRIPT_DIR/ycombo.py" > /dev/null && info "Cache populated." || error "Fetch failed — check network."

# 4. i3 config (idempotent)
if [[ -f "$I3_CONFIG" ]]; then
    add_i3() {
        grep -qF "$1" "$I3_CONFIG" && warn "Already in i3 config: $1" || {
            echo "$1" >> "$I3_CONFIG"
            info "Added to i3 config: $1"
        }
    }

    if ! grep -qF "YCOMBO" "$I3_CONFIG"; then
        echo "" >> "$I3_CONFIG"
        echo "# YCOMBO — AI & Dev HN feed" >> "$I3_CONFIG"
    fi

    add_i3 "for_window [class=\"eww-ycombo\"] border none"
    add_i3 "no_focus [class=\"eww-ycombo\"]"
    add_i3 "exec_always --no-startup-id $SCRIPT_DIR/ycombo-start.sh &"
    add_i3 "bindsym \$mod+F5 exec --no-startup-id $SCRIPT_DIR/ycombo-refresh.sh"
    add_i3 "bindsym \$mod+Shift+F5 exec --no-startup-id $SCRIPT_DIR/ycombo-toggle.sh"
else
    warn "i3 config not found at $I3_CONFIG — skipping i3 setup."
fi

# 5. Kill stale processes and launch
info "Launching YCOMBO..."
pkill -f "ycombo-daemon.sh" 2>/dev/null || true
pkill -f "eww.*ycombo" 2>/dev/null || true
sleep 0.5

"$SCRIPT_DIR/ycombo-daemon.sh" &
disown

sleep 2
eww --config "$EWW_CFG" open ycombo
sleep 1
xdotool search --name "Eww - ycombo" windowlower 2>/dev/null || true

echo ""
info "YCOMBO is live on your desktop."
echo ""
echo "  Click any post       — opens on Hacker News"
echo "  Click  button      — force refresh"
echo "  Super+F5             — force refresh (keyboard)"
echo "  Super+Shift+F5       — toggle show/hide"
echo ""
echo "  Reload i3 to persist autostart: i3-msg reload"
