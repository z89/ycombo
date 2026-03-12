# YCOMBO

> AI & Dev Intelligence Feed: always-on HN desktop widget

YCOMBO is an [eww](https://github.com/elkowar/eww) desktop widget that continuously surfaces the most relevant Hacker News posts on **AI agents, LLM engineering, agentic workflows, and software engineering best practices**, filtered from the noise, displayed directly on your desktop.

<div align="center">
  <img src="demo.gif" width="600" alt="YCOMBO widget" />
</div>

---

## Features

- **Latest posts** all relevant posts from the past 14 days, refreshed every 5 minutes, sorted by recency, keyword-filtered for AI/agent/LLM relevance
- **Must Read Top 5** highest-scored posts (80+ points) from the past 30 days, sorted by votes
- **Async fetching** all 13 Algolia queries run concurrently via aiohttp, completing in under 1 second
- **Scrollable latest posts** the latest section has a styled scrollbar for browsing long lists
- **Fade-on-idle** panel sits at 10% opacity, fades to 100% on hover, fades back after 10 seconds
- **Close animation** 200ms fade-out when hiding the widget
- **Always-on mode** pin button next to hide keeps the widget fully visible, disabling the fade-out timer
- **Keyboard resize** Super+Ctrl+Arrow keys to resize width and scroll height, dimensions persisted across restarts
- **Pywal-aware styling** colours pulled from your wallpaper theme (requires pywal)
- **Offline resilience** serves cached results when the network is unavailable, shows "Never" as last updated
- **Zero auth** uses the [Algolia HN API](https://hn.algolia.com/api) (free, no key required)
- **Clickable posts** opens directly on Hacker News in Chromium
- **Keyboard shortcuts** `Super+F5` to refresh, `Super+Shift+F5` to toggle

---

## Requirements

- Arch Linux (or any distro with `pacman`)
- Hyprland (Wayland compositor)
- `eww` wayland build (`eww-git` via yay)
- `python3` + `python-aiohttp`
- FiraCode Nerd Font Mono

---

## Install

```bash
git clone git@github.com:z89/ycombo.git ~/Documents/Github-Projects/ycombo
cd ~/Documents/Github-Projects/ycombo
./install.sh
```

The installer will:
1. Install `eww-git` and `python-aiohttp` if missing
2. Set executable permissions on all scripts
3. Fetch initial HN data
4. Add YCOMBO to your Hyprland config (window rules, autostart, keybindings)
5. Launch the widget

---

## Files

| File | Purpose |
|---|---|
| `ycombo.py` | Async daemon: fetches and filters HN posts, writes cache, handles signals |
| `eww/eww.yuck` | Widget layout: sections, posts, footer, hover opacity, close animation |
| `eww/eww.scss` | Styling: pywal colours, opacity transitions, hover states |
| `ycombo-start.sh` | Startup: kills stale processes, starts daemon, opens widget, restores dimensions |
| `ycombo-refresh.sh` | Signal-based refresh trigger |
| `ycombo-toggle.sh` | Toggle widget visibility with close animation |
| `ycombo-resize.sh` | Keybind-driven resize via hyprctl IPC |
| `install.sh` | One-command setup for Hyprland |

---

## Configuration

### Positioning

Edit the window geometry in `eww/eww.yuck`:

```lisp
(defwindow ycombo
  :geometry (geometry :x "15px" :y "46px" :width "860px" :anchor "top left")
  :stacking "bg"
  ...)
```

### Keywords

Edit the `RELEVANT` list in `ycombo.py` to tune which posts pass the filter. Edit `LATEST_QUERIES` and `TOP5_QUERIES` to change the Algolia search terms.

### Colours

Colours are set in `eww/eww.scss` using the pywal palette from your desktop theme.

---

## How It Works

```
ycombo.py --daemon (runs in background):
  Every 5 minutes (or on SIGUSR1):
    |-- fetch_latest()  > 8 Algolia queries (concurrent)
    |                      deduplicated, keyword-filtered, sorted by date
    +-- fetch_top5()    > 5 Algolia queries (concurrent)
                           80+ pts, last 30d, sorted by score > top 5
    |
    Writes $XDG_RUNTIME_DIR/ycombo/cache.json
    |
    eww polls cache every 2s > widget updates
```

---

## Uninstall

```bash
# Stop daemon
kill "$(cat "${XDG_RUNTIME_DIR}/ycombo/daemon.pid")" 2>/dev/null
eww --config ~/Documents/Github-Projects/ycombo/eww close ycombo
# Remove YCOMBO lines from ~/.config/hypr/hyprland.conf
# Delete the ycombo directory
```

---

## License

MIT
