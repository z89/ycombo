#!/usr/bin/env bash
# YCOMBO — install script for Hyprland
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HYPR_CONFIG="$HOME/.config/hypr/hyprland.conf"

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[x]${NC} $1"; exit 1; }

info "Installing YCOMBO..."

# 1. Check deps
if ! command -v python3 &>/dev/null; then
    error "python3 not found. Install it first."
fi
info "python3 OK"

if ! python3 -c "import aiohttp" &>/dev/null; then
    warn "python-aiohttp not found — installing..."
    sudo pacman -S --noconfirm python-aiohttp
else
    info "python-aiohttp OK"
fi

if ! python3 -c "import gi; gi.require_version('Gtk', '3.0'); gi.require_version('GtkLayerShell', '0.1')" &>/dev/null; then
    warn "gtk-layer-shell not found — installing..."
    sudo pacman -S --noconfirm gtk-layer-shell python-gobject
else
    info "gtk-layer-shell + PyGObject OK"
fi

if ! command -v matugen &>/dev/null; then
    warn "matugen not found — colors will use defaults until installed"
else
    info "matugen OK"
fi

# 2. Permissions
chmod +x "$SCRIPT_DIR/ycombo.py" \
         "$SCRIPT_DIR/ycombo-refresh.sh" \
         "$SCRIPT_DIR/ycombo-start.sh" \
         "$SCRIPT_DIR/ycombo-toggle.sh"
info "Script permissions set."

# 3. Initial data fetch
info "Fetching initial data..."
python3 "$SCRIPT_DIR/ycombo.py" > /dev/null && info "Cache populated." || error "Fetch failed — check network."

# 4. Hyprland config (idempotent)
if [[ -f "$HYPR_CONFIG" ]]; then
    add_hypr() {
        grep -qF "$1" "$HYPR_CONFIG" && warn "Already in hyprland config: $1" || {
            echo "$1" >> "$HYPR_CONFIG"
            info "Added to hyprland config: $1"
        }
    }

    if ! grep -qF "YCOMBO" "$HYPR_CONFIG"; then
        echo "" >> "$HYPR_CONFIG"
        echo "# YCOMBO — AI & Dev HN feed" >> "$HYPR_CONFIG"
    fi

    add_hypr "bind = \$mainMod, F5, exec, $SCRIPT_DIR/ycombo-refresh.sh"
    add_hypr "bind = \$mainMod, Y, exec, $SCRIPT_DIR/ycombo-toggle.sh"
    add_hypr "exec-once = $SCRIPT_DIR/ycombo-start.sh"
else
    warn "Hyprland config not found at $HYPR_CONFIG — skipping Hyprland setup."
fi

# 5. Kill stale processes and launch
info "Launching YCOMBO..."
PID_FILE="${XDG_RUNTIME_DIR:-/tmp}/ycombo/daemon.pid"
if [[ -f "$PID_FILE" ]]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
fi
sleep 0.5

"$SCRIPT_DIR/ycombo-start.sh" &
disown

sleep 3

echo ""
info "YCOMBO is live on your desktop."
echo ""
echo "  Click any post           — opens on Hacker News"
echo "  Super+F5                 — force refresh"
echo "  Super+Y                  — toggle open/close"
echo "  Scroll on grip icon      — resize height"
echo "  Shift+scroll on grip     — resize width"
echo ""
