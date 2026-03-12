#!/usr/bin/env python3
"""
YCOMBO - AI & Dev Intelligence Feed
Native GTK3 + gtk-layer-shell widget for Hyprland/Wayland.

Modes:
  (no flag)   Single fetch and exit (for install/testing)
  --daemon    GTK app with async fetch loop, SIGUSR1=refresh, SIGUSR2=toggle
  --refresh   Send SIGUSR1 to running daemon
  --toggle    Send SIGUSR2 to running daemon
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import aiohttp
except ImportError:
    print("python-aiohttp not found: pacman -S python-aiohttp", file=sys.stderr)
    sys.exit(1)

import fcntl
import glob

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, Gio, GLib, GtkLayerShell, Pango

log = logging.getLogger("ycombo")
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s", stream=sys.stderr)

# ── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "ycombo"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
PID_FILE = RUNTIME_DIR / "daemon.pid"
CACHE_JSON = RUNTIME_DIR / "cache.json"
CONFIG_FILE = Path.home() / ".config" / "ycombo" / "config.json"
CSS_FILE = SCRIPT_DIR / "ycombo.css"
COLORS_FILE = SCRIPT_DIR / "colors.conf"

# ── Input helpers ────────────────────────────────────────────────────────────

_EVIOCGKEY = 0x80604518  # ioctl to read key state bitmap
_KEY_LEFTSHIFT = 42
_KEY_RIGHTSHIFT = 54

def _is_shift_held() -> bool:
    """Query /dev/input directly for shift key state (works on unfocused surfaces)."""
    for path in glob.glob("/dev/input/by-id/*-kbd"):
        if "-if0" in path:
            continue
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            buf = bytearray(96)
            fcntl.ioctl(fd, _EVIOCGKEY, buf)
            os.close(fd)
            left = bool(buf[_KEY_LEFTSHIFT // 8] & (1 << (_KEY_LEFTSHIFT % 8)))
            right = bool(buf[_KEY_RIGHTSHIFT // 8] & (1 << (_KEY_RIGHTSHIFT % 8)))
            if left or right:
                return True
        except (OSError, PermissionError):
            continue
    return False

# ── Color helpers ────────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.strip().lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"

def parse_colors(path: Path) -> dict[str, str]:
    """Parse colors.conf (key=value) and build template substitution dict."""
    raw: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                raw[k.strip()] = v.strip()

    # Defaults if colors.conf is missing/incomplete
    defaults = {
        "yc_bg": "#1a1a2e", "yc_bg_container": "#222244",
        "yc_fg": "#e0e0e0", "yc_fg_dim": "#a0a0a0",
        "yc_primary": "#7c83ff", "yc_primary_container": "#3b4279",
        "yc_secondary": "#c4c5dd", "yc_tertiary": "#e9b6e7",
        "yc_outline": "#909099", "yc_outline_variant": "#464650",
        "yc_error": "#ffb4ab",
    }
    for k, v in defaults.items():
        raw.setdefault(k, v)

    # Build substitution dict: plain colors + alpha variants
    subs: dict[str, str] = {}
    for k, v in raw.items():
        subs[k] = v
    # Pre-computed alpha variants used in CSS template
    alpha_map = {
        "yc_bg_92": ("yc_bg", 0.92),
        "yc_outline_35": ("yc_outline", 0.35),
        "yc_outline_55": ("yc_outline", 0.55),
        "yc_outline_15": ("yc_outline", 0.15),
        "yc_primary_50": ("yc_primary", 0.50),
        "yc_primary_13": ("yc_primary", 0.13),
        "yc_primary_28": ("yc_primary", 0.28),
        "yc_primary_20": ("yc_primary", 0.20),
        "yc_primary_35": ("yc_primary", 0.35),
        "yc_primary_12": ("yc_primary", 0.12),
        "yc_primary_10": ("yc_primary", 0.10),
        "yc_primary_18": ("yc_primary", 0.18),
        "yc_tertiary_10": ("yc_tertiary", 0.10),
        "yc_error_12": ("yc_error", 0.12),
    }
    for name, (base, alpha) in alpha_map.items():
        subs[name] = _rgba(raw[base], alpha)

    return subs

def build_css(template_path: Path, colors_path: Path) -> str:
    """Read CSS template and substitute $color placeholders."""
    import re
    subs = parse_colors(colors_path)
    template = template_path.read_text()
    # Replace $var_name with color values (longest match first to avoid partial)
    for key in sorted(subs, key=len, reverse=True):
        template = template.replace(f"${key}", subs[key])
    return template

# ── Dimensions ───────────────────────────────────────────────────────────────

DEFAULT_WIDTH = 860
DEFAULT_SCROLL_HEIGHT = 420
MIN_WIDTH, MAX_WIDTH = 500, 1920
MIN_SCROLL, MAX_SCROLL = 150, 1400
SCROLL_STEP = 30

# ── Keywords & Queries ───────────────────────────────────────────────────────

RELEVANT = [
    "ai", "llm", "agent", "claude", "gpt", "openai", "anthropic",
    "cursor", "copilot", "rag", "embedding", "transformer", "agentic",
    "langchain", "langgraph", "workflow", "mcp", "context protocol",
    "neural", "inference", "fine-tun", "prompt engineering", "benchmark",
    "multimodal", "autonomous", "code generation", "software engineer",
    "gemini", "mistral", "llama", "deepseek", "o1", "o3",
    "computer use", "function calling", "tool use", "ai coding",
]

LATEST_QUERIES = [
    "AI agent", "LLM coding", "agentic workflow", "Claude GPT",
    "software engineering AI", "RAG embedding", "MCP model context",
    "cursor copilot",
]

TOP5_QUERIES = [
    "AI agent architecture", "LLM engineering", "agentic system",
    "AI workflow best practices", "software engineering LLM",
]

# ── Data helpers ─────────────────────────────────────────────────────────────

def is_relevant(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in RELEVANT)

def time_ago(ts: int) -> str:
    diff = int(time.time()) - ts
    if diff < 3600:  return f"{diff // 60}m"
    if diff < 86400: return f"{diff // 3600}h"
    return f"{diff // 86400}d"

def fmt_pts(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)

def trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "\u2026"

def to_post(h: dict[str, Any], idx: int) -> dict[str, Any]:
    return {
        "idx":      idx,
        "id":       h.get("objectID", ""),
        "title":    trunc(h.get("title", "Untitled"), 90),
        "pts":      fmt_pts(h.get("points", 0)),
        "comments": h.get("num_comments", 0),
        "ago":      time_ago(h.get("created_at_i", 0)),
    }

# ── Async fetch ──────────────────────────────────────────────────────────────

ALGOLIA_BASE = "https://hn.algolia.com/api/v1"
MAX_RETRIES = 3
BACKOFF = [1, 2, 4]

async def algolia(
    session: aiohttp.ClientSession, query: str,
    by_date: bool = False, hours: int = 0, min_pts: int = 0, limit: int = 50,
) -> list[dict[str, Any]]:
    endpoint = "search_by_date" if by_date else "search"
    params: dict[str, Any] = {"query": query, "tags": "story", "hitsPerPage": limit}
    filters = []
    if hours:
        filters.append(f"created_at_i>{int(time.time()) - hours * 3600}")
    if min_pts:
        filters.append(f"points>{min_pts}")
    if filters:
        params["numericFilters"] = ",".join(filters)

    for attempt in range(MAX_RETRIES):
        try:
            async with session.get(
                f"{ALGOLIA_BASE}/{endpoint}", params=params,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data.get("hits", [])
        except Exception:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BACKOFF[attempt])
            else:
                raise
    return []

async def fetch_latest(session: aiohttp.ClientSession) -> list[dict[str, Any]]:
    tasks = [algolia(session, q, by_date=True, hours=336, limit=50) for q in LATEST_QUERIES]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    seen: dict[str, dict[str, Any]] = {}
    for result in results:
        if isinstance(result, Exception):
            log.warning("query failed: %s", result)
            continue
        for h in result:
            oid = h.get("objectID")
            if oid not in seen and h.get("title") and is_relevant(h["title"]):
                seen[oid] = h
    return sorted(seen.values(), key=lambda x: x.get("created_at_i", 0), reverse=True)

async def fetch_top5(session: aiohttp.ClientSession) -> list[dict[str, Any]]:
    tasks = [algolia(session, q, by_date=False, hours=720, min_pts=80, limit=20) for q in TOP5_QUERIES]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    seen: dict[str, dict[str, Any]] = {}
    for result in results:
        if isinstance(result, Exception):
            log.warning("query failed: %s", result)
            continue
        for h in result:
            oid = h.get("objectID")
            pts = h.get("points", 0)
            if oid not in seen and h.get("title") and is_relevant(h["title"]) and pts >= 80:
                seen[oid] = h
    return sorted(seen.values(), key=lambda x: x.get("points", 0), reverse=True)[:5]

async def do_fetch() -> dict[str, Any]:
    try:
        async with aiohttp.ClientSession() as session:
            latest, top5 = await asyncio.gather(fetch_latest(session), fetch_top5(session))
            return {
                "updated": datetime.now().strftime("%I:%M %p").lstrip("0"),
                "offline": False,
                "latest":  [to_post(h, i) for i, h in enumerate(latest, 1)],
                "top5":    [to_post(h, i) for i, h in enumerate(top5, 1)],
            }
    except Exception as e:
        log.error("fetch failed: %s", e)
        if CACHE_JSON.exists():
            data = json.loads(CACHE_JSON.read_text())
            data["offline"] = True
            data["updated"] = "offline"
            return data
        return {"updated": "offline", "offline": True, "latest": [], "top5": []}

def write_cache(data: dict[str, Any]) -> None:
    CACHE_JSON.write_text(json.dumps(data))

# ── GTK Widget ───────────────────────────────────────────────────────────────

SPINNER_CHARS = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"
ICON_REFRESH  = "\uf021"
ICON_OFFLINE  = "\uf071"
ICON_EYE      = "\uf06e"
ICON_EYE_OFF  = "\uf070"
ICON_CLOSE    = "\uf00d"
ICON_GRIP     = "\u283f"

class YComboWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__()

        # Layer shell
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 5)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, 5)
        GtkLayerShell.set_namespace(self, "ycombo")
        self.set_decorated(False)
        self.set_resizable(False)

        # Transparency
        self.set_app_paintable(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.connect("screen-changed", self._on_screen_changed)

        # State
        self.hovered = False
        self._shown = True
        self.always_on = False
        self.loading = False
        self.fade_timer_id = None
        self.spinner_timer_id = None
        self.spinner_idx = 0
        self._scroll_accum_x = 0.0
        self._scroll_accum_y = 0.0
        self.data: dict[str, Any] = {
            "updated": "loading\u2026", "offline": False, "latest": [], "top5": [],
        }

        # Config
        self.width = DEFAULT_WIDTH
        self.scroll_height = DEFAULT_SCROLL_HEIGHT
        self._load_config()

        # CSS
        self._load_css()

        # Build UI
        self._build_ui()

        # Fixed window size (transparent beyond content) - avoids compositor
        # roundtrip bounce on resize. Only inner content changes visually.
        self.set_size_request(MAX_WIDTH, MAX_SCROLL + 400)
        self.root_box.set_size_request(self.width, -1)
        self.scroll_win.set_size_request(-1, self.scroll_height)

        # Fetch thread
        self.fetch_loop: asyncio.AbstractEventLoop | None = None
        self.refresh_event = threading.Event()
        self.shutdown_event = threading.Event()

    @staticmethod
    def _on_screen_changed(widget: Gtk.Widget, _old: Gdk.Screen | None) -> None:
        screen = widget.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            widget.set_visual(visual)

    def _load_config(self) -> None:
        if CONFIG_FILE.exists():
            try:
                cfg = json.loads(CONFIG_FILE.read_text())
                self.width = cfg.get("width", DEFAULT_WIDTH)
                self.scroll_height = cfg.get("scroll_height", DEFAULT_SCROLL_HEIGHT)
            except (json.JSONDecodeError, OSError):
                pass

    def _save_config(self) -> None:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps({
            "width": self.width, "scroll_height": self.scroll_height,
        }))

    def _load_css(self) -> None:
        self._screen = Gdk.Screen.get_default()
        self._css_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            self._screen, self._css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER + 100,
        )
        self._apply_css()
        self._watch_colors()

    def _apply_css(self) -> None:
        try:
            css_str = build_css(CSS_FILE, COLORS_FILE)
            self._css_provider.load_from_data(css_str.encode())
            log.info("CSS applied with colors from %s", COLORS_FILE)
        except Exception as e:
            log.warning("CSS load failed: %s", e)

    def _watch_colors(self) -> None:
        """Watch colors.conf for changes (matugen theme switch)."""
        if not COLORS_FILE.exists():
            return
        gfile = Gio.File.new_for_path(str(COLORS_FILE))
        self._color_monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self._color_monitor.connect("changed", self._on_colors_changed)

    def _on_colors_changed(self, _monitor, _file, _other, event) -> None:
        if event in (Gio.FileMonitorEvent.CHANGED, Gio.FileMonitorEvent.CREATED):
            GLib.timeout_add(200, self._apply_css)  # debounce

    def _build_ui(self) -> None:
        # Root eventbox for hover detection
        self.eventbox = Gtk.EventBox()
        self.eventbox.set_events(
            Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        self.eventbox.connect("enter-notify-event", self._on_hover_enter)
        self.eventbox.connect("leave-notify-event", self._on_hover_leave)
        self.add(self.eventbox)

        # Root box - left/top aligned within the fixed-size transparent window
        self.root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.root_box.set_halign(Gtk.Align.START)
        self.root_box.set_valign(Gtk.Align.START)
        self.root_box.get_style_context().add_class("root")
        self.root_box.get_style_context().add_class("hidden")
        self.eventbox.add(self.root_box)

        # Helper: icon button using EventBox + Label (no Adwaita padding)
        def _icon_btn(icon: str, css_class: str, tooltip: str, callback) -> Gtk.EventBox:
            eb = Gtk.EventBox()
            eb.get_style_context().add_class("icon-btn")
            eb.get_style_context().add_class(css_class)
            eb.set_tooltip_text(tooltip)
            eb.set_size_request(28, 28)
            eb.add_events(
                Gdk.EventMask.BUTTON_PRESS_MASK
                | Gdk.EventMask.ENTER_NOTIFY_MASK
                | Gdk.EventMask.LEAVE_NOTIFY_MASK
            )
            eb.connect("button-press-event", lambda w, e: callback(w))
            def _on_enter(w, e):
                w.get_style_context().add_class("hover")
                self.get_window().set_cursor(Gdk.Cursor.new_from_name(w.get_display(), "pointer"))
            def _on_leave(w, e):
                w.get_style_context().remove_class("hover")
                self.get_window().set_cursor(None)
            eb.connect("enter-notify-event", _on_enter)
            eb.connect("leave-notify-event", _on_leave)
            inner = Gtk.Box()
            inner.set_halign(Gtk.Align.FILL)
            inner.set_valign(Gtk.Align.FILL)
            lbl = Gtk.Label(label=icon)
            lbl.set_halign(Gtk.Align.CENTER)
            lbl.set_valign(Gtk.Align.CENTER)
            inner.set_center_widget(lbl)
            eb.add(inner)
            return eb

        # Top bar: grip + LATEST label + spacer + controls
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        top_bar.get_style_context().add_class("top-bar")

        # Resize grip
        grip_event = Gtk.EventBox()
        grip_event.get_style_context().add_class("resize-grip")
        grip_event.set_tooltip_text("Scroll to resize height, Shift+scroll for width")
        grip_event.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        grip_event.connect("scroll-event", self._on_resize_scroll)
        grip_event.set_valign(Gtk.Align.CENTER)
        grip_event.set_margin_top(3)
        grip_event.set_margin_start(6)
        grip_event.set_margin_end(10)
        grip_label = Gtk.Label(label=ICON_GRIP)
        grip_label.get_style_context().add_class("resize-grip-icon")
        grip_label.set_valign(Gtk.Align.CENTER)
        grip_event.add(grip_label)
        top_bar.pack_start(grip_event, False, False, 0)

        latest_label = Gtk.Label(label="LATEST - PAST 14 DAYS")
        latest_label.get_style_context().add_class("section-label")
        latest_label.get_style_context().add_class("section-label-latest")
        latest_label.set_halign(Gtk.Align.START)
        latest_label.set_valign(Gtk.Align.CENTER)
        top_bar.pack_start(latest_label, False, False, 0)

        top_bar.pack_start(Gtk.Box(), True, True, 0)  # spacer

        # Spinner
        self.spinner_label = Gtk.Label(label=SPINNER_CHARS[0])
        self.spinner_label.get_style_context().add_class("spinner-inline")
        self.spinner_label.set_visible(False)
        self.spinner_label.set_no_show_all(True)
        self.spinner_label.set_valign(Gtk.Align.CENTER)
        top_bar.pack_start(self.spinner_label, False, False, 0)

        # Offline indicator
        self.offline_label = Gtk.Label(label=f" {ICON_OFFLINE}")
        self.offline_label.get_style_context().add_class("sig-offline")
        self.offline_label.set_visible(False)
        self.offline_label.set_no_show_all(True)
        self.offline_label.set_valign(Gtk.Align.CENTER)
        top_bar.pack_start(self.offline_label, False, False, 0)

        # Last updated text
        self.time_label = Gtk.Label(label="loading\u2026")
        self.time_label.get_style_context().add_class("sig-time")
        self.time_label.set_valign(Gtk.Align.CENTER)
        self.time_label.set_margin_end(14)
        top_bar.pack_start(self.time_label, False, False, 0)

        # Refresh button
        self._refresh_btn = _icon_btn(ICON_REFRESH, "btn-refresh", "Force refresh", self._on_refresh_click)
        self._refresh_btn.set_valign(Gtk.Align.CENTER)
        self._refresh_btn.set_margin_end(5)
        top_bar.pack_start(self._refresh_btn, False, False, 0)

        # Always-on button
        self._always_btn = _icon_btn(ICON_EYE_OFF, "btn-always-on", "Keep always visible", self._on_always_on_click)
        self._always_label = self._always_btn.get_child().get_center_widget()
        self._always_btn.set_valign(Gtk.Align.CENTER)
        self._always_btn.set_margin_end(5)
        top_bar.pack_start(self._always_btn, False, False, 0)

        # Close button (larger)
        self._close_btn = _icon_btn(ICON_CLOSE, "btn-toggle", "Hide YCOMBO", self._on_close_click)
        self._close_btn.set_valign(Gtk.Align.CENTER)
        self._close_btn.set_size_request(32, 32)
        top_bar.pack_start(self._close_btn, False, False, 0)

        self.root_box.pack_start(top_bar, False, False, 0)

        # Scrolled window for latest posts
        self.scroll_win = Gtk.ScrolledWindow()
        self.scroll_win.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll_win.set_overlay_scrolling(False)
        self.latest_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.latest_box.get_style_context().add_class("post-list")
        self.scroll_win.add(self.latest_box)
        self.root_box.pack_start(self.scroll_win, False, False, 0)

        # Top 5 section
        top5_label = Gtk.Label(label="      \u2731   MUST READ - TOP 5")
        top5_label.get_style_context().add_class("section-label")
        top5_label.set_halign(Gtk.Align.START)
        top5_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        top5_section.get_style_context().add_class("top5-section")
        top5_section.pack_start(top5_label, False, False, 0)
        self.top5_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.top5_box.get_style_context().add_class("post-list")
        top5_section.pack_start(self.top5_box, False, False, 0)
        self.root_box.pack_start(top5_section, False, False, 0)

    def _make_post_button(self, post: dict[str, Any], is_top: bool) -> Gtk.Button:
        btn = Gtk.Button()
        btn.get_style_context().add_class("post-btn")
        if is_top:
            btn.get_style_context().add_class("post-top")
        btn.set_tooltip_text("Open on Hacker News")
        btn.connect("enter-notify-event", lambda w, e:
            self.get_window().set_cursor(Gdk.Cursor.new_from_name(w.get_display(), "pointer")))
        btn.connect("leave-notify-event", lambda w, e:
            self.get_window().set_cursor(None))
        post_id = post["id"]
        btn.connect("clicked", lambda _w: subprocess.Popen(
            ["xdg-open", f"https://news.ycombinator.com/item?id={post_id}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        inner.get_style_context().add_class("post-inner")

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        num = Gtk.Label(label=f"{post['idx']}.")
        num.get_style_context().add_class("post-num")
        num.set_size_request(28, -1)
        title_row.pack_start(num, False, False, 0)

        title = Gtk.Label(label=post["title"])
        title.get_style_context().add_class("post-title")
        if is_top:
            title.get_style_context().add_class("bold")
        title.set_halign(Gtk.Align.START)
        title.set_hexpand(True)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title_row.pack_start(title, True, True, 0)

        inner.pack_start(title_row, False, False, 0)

        meta = Gtk.Label(label=f"{post['pts']} pts  \u00b7  {post['comments']} comments  \u00b7  {post['ago']}")
        meta.get_style_context().add_class("post-meta")
        meta.set_halign(Gtk.Align.START)
        inner.pack_start(meta, False, False, 0)

        btn.add(inner)
        return btn

    def _update_posts(self) -> None:
        # Clear old posts
        for child in self.latest_box.get_children():
            self.latest_box.remove(child)
        for child in self.top5_box.get_children():
            self.top5_box.remove(child)

        # Add latest
        for post in self.data.get("latest", []):
            btn = self._make_post_button(post, False)
            self.latest_box.pack_start(btn, False, False, 0)

        # Add top 5
        for post in self.data.get("top5", []):
            btn = self._make_post_button(post, True)
            self.top5_box.pack_start(btn, False, False, 0)

        # Update footer
        if self.data.get("offline"):
            self.time_label.set_text("Never")
            self.offline_label.set_visible(True)
        else:
            self.time_label.set_text(self.data.get("updated", ""))
            self.offline_label.set_visible(False)

        self.latest_box.show_all()
        self.top5_box.show_all()

    # ── Hover / fade ─────────────────────────────────────────────────────────

    def _on_hover_enter(self, _w: Gtk.Widget, _e: Gdk.EventCrossing) -> bool:
        self.hovered = True
        if self.fade_timer_id:
            GLib.source_remove(self.fade_timer_id)
            self.fade_timer_id = None
        ctx = self.root_box.get_style_context()
        ctx.remove_class("hidden")
        ctx.add_class("visible")
        return False

    def _on_hover_leave(self, _w: Gtk.Widget, _e: Gdk.EventCrossing) -> bool:
        self.hovered = False
        win = self.get_window()
        if win:
            win.set_cursor(None)
        if self.always_on:
            return False
        if self.fade_timer_id:
            GLib.source_remove(self.fade_timer_id)
        self.fade_timer_id = GLib.timeout_add_seconds(10, self._do_fade_out)
        return False

    def _do_fade_out(self) -> bool:
        if not self.hovered and not self.always_on:
            ctx = self.root_box.get_style_context()
            ctx.remove_class("visible")
            ctx.add_class("hidden")
        self.fade_timer_id = None
        return False  # don't repeat

    # ── Resize ───────────────────────────────────────────────────────────────

    def _on_resize_scroll(self, _w: Gtk.Widget, event: Gdk.EventScroll) -> bool:
        # event.state and keymap are empty on unfocused Wayland layer-shell;
        # query /dev/input directly for shift key state
        shift = _is_shift_held()
        is_width = False
        delta = 0

        log.info("scroll: dir=%s dx=%.3f dy=%.3f", event.direction, event.delta_x, event.delta_y)

        if event.direction == Gdk.ScrollDirection.UP:
            delta = -SCROLL_STEP
        elif event.direction == Gdk.ScrollDirection.DOWN:
            delta = SCROLL_STEP
        elif event.direction == Gdk.ScrollDirection.LEFT:
            delta = -SCROLL_STEP
            is_width = True
        elif event.direction == Gdk.ScrollDirection.RIGHT:
            delta = SCROLL_STEP
            is_width = True
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            # Accumulate smooth scroll deltas and only fire at threshold
            self._scroll_accum_x += event.delta_x
            self._scroll_accum_y += event.delta_y

            if abs(self._scroll_accum_x) > abs(self._scroll_accum_y) and abs(self._scroll_accum_x) >= 1.0:
                sign = 1 if self._scroll_accum_x > 0 else -1
                self._scroll_accum_x = 0.0
                self._scroll_accum_y = 0.0
                delta = sign * SCROLL_STEP
                is_width = True
            elif abs(self._scroll_accum_y) >= 1.0:
                sign = 1 if self._scroll_accum_y > 0 else -1
                self._scroll_accum_x = 0.0
                self._scroll_accum_y = 0.0
                delta = sign * SCROLL_STEP
            else:
                return True
        else:
            return False

        if shift or is_width:
            self.width = max(MIN_WIDTH, min(MAX_WIDTH, self.width + delta))
            log.info("resize width: delta=%d -> %d", delta, self.width)
            self._resize_width(self.width)
        else:
            old = self.scroll_height
            self.scroll_height = max(MIN_SCROLL, min(MAX_SCROLL, self.scroll_height + delta))
            log.info("resize height: delta=%d old=%d -> %d", delta, old, self.scroll_height)
            self._resize_height(self.scroll_height)

        self._save_config()
        return True

    def _resize_width(self, width: int) -> None:
        """Resize inner content only - window stays fixed size."""
        self.root_box.set_size_request(width, -1)

    def _resize_height(self, height: int) -> None:
        """Resize scroll height only - window stays fixed size."""
        self.scroll_win.set_size_request(-1, height)

    # ── Button handlers ──────────────────────────────────────────────────────

    def _on_refresh_click(self, _w: Gtk.Widget) -> None:
        if self.refresh_event:
            self.refresh_event.set()

    def _on_always_on_click(self, _w: Gtk.Widget) -> None:
        self.always_on = not self.always_on
        ctx = self._always_btn.get_style_context()
        if self.always_on:
            ctx.add_class("active")
            self._always_label.set_text(ICON_EYE)
            self._always_btn.set_tooltip_text("Disable always on")
            # Cancel pending fade
            if self.fade_timer_id:
                GLib.source_remove(self.fade_timer_id)
                self.fade_timer_id = None
        else:
            ctx.remove_class("active")
            self._always_label.set_text(ICON_EYE_OFF)
            self._always_btn.set_tooltip_text("Keep always visible")

    def _on_close_click(self, _w: Gtk.Widget) -> None:
        self._set_shown(False)

    def _set_shown(self, shown: bool) -> None:
        ctx = self.root_box.get_style_context()
        self._shown = shown
        if shown:
            ctx.remove_class("hidden")
            ctx.remove_class("closing")
            ctx.add_class("visible")
            log.info("shown")
        else:
            ctx.remove_class("visible")
            ctx.remove_class("hidden")
            ctx.add_class("closing")
            log.info("hidden")

    def toggle_visibility(self) -> None:
        shown = getattr(self, "_shown", True)
        log.info("toggle_visibility called, currently shown=%s", shown)
        self._set_shown(not shown)

    # ── Spinner ──────────────────────────────────────────────────────────────

    def _set_loading(self, active: bool) -> None:
        self.loading = active
        self.spinner_label.set_visible(active)
        if active and not self.spinner_timer_id:
            self.spinner_timer_id = GLib.timeout_add(120, self._tick_spinner)
        elif not active and self.spinner_timer_id:
            GLib.source_remove(self.spinner_timer_id)
            self.spinner_timer_id = None

    def _tick_spinner(self) -> bool:
        if not self.loading:
            self.spinner_timer_id = None
            return False
        self.spinner_idx = (self.spinner_idx + 1) % len(SPINNER_CHARS)
        self.spinner_label.set_text(SPINNER_CHARS[self.spinner_idx])
        return True

    # ── Fetch thread ─────────────────────────────────────────────────────────

    def start_fetch_thread(self) -> None:
        t = threading.Thread(target=self._fetch_worker, daemon=True)
        t.start()

    def _fetch_worker(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        def do_refresh():
            GLib.idle_add(self._set_loading, True)
            data = loop.run_until_complete(do_fetch())
            write_cache(data)
            self.data = data
            GLib.idle_add(self._set_loading, False)
            GLib.idle_add(self._update_posts)
            log.info("refreshed at %s (%d latest, %d top5)",
                     data["updated"], len(data["latest"]), len(data["top5"]))

        # Initial fetch
        do_refresh()

        # Loop
        while not self.shutdown_event.is_set():
            self.refresh_event.wait(timeout=300)
            if self.shutdown_event.is_set():
                break
            self.refresh_event.clear()
            do_refresh()

        loop.close()

    def shutdown(self) -> None:
        self.shutdown_event.set()
        self.refresh_event.set()  # wake up the wait
        PID_FILE.unlink(missing_ok=True)

# ── Signal handling ──────────────────────────────────────────────────────────

def send_signal(sig: int) -> bool:
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, sig)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return False

# ── Main ─────────────────────────────────────────────────────────────────────

def _kill_stale_daemon() -> None:
    """Kill any existing daemon before starting a new one."""
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            if old_pid != os.getpid():
                os.kill(old_pid, signal.SIGKILL)
                log.info("killed stale daemon (pid %d)", old_pid)
        except (ValueError, ProcessLookupError, OSError):
            pass
        PID_FILE.unlink(missing_ok=True)

def run_daemon() -> None:
    _kill_stale_daemon()
    PID_FILE.write_text(str(os.getpid()))

    win = YComboWindow()
    win.connect("destroy", lambda _w: Gtk.main_quit())
    win.show_all()
    win.spinner_label.set_visible(False)
    win.offline_label.set_visible(False)

    # Signal handlers (run on GLib main loop via GLib.unix_signal_add)
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1, lambda: (win.refresh_event.set(), True)[1])
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR2, lambda: (win.toggle_visibility(), True)[1])
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, lambda: (win.shutdown(), Gtk.main_quit(), True)[2])
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, lambda: (win.shutdown(), Gtk.main_quit(), True)[2])

    win.start_fetch_thread()

    log.info("daemon started (pid %d)", os.getpid())
    Gtk.main()
    win.shutdown()

def main() -> None:
    if "--daemon" in sys.argv:
        run_daemon()
    elif "--refresh" in sys.argv:
        if send_signal(signal.SIGUSR1):
            log.info("sent SIGUSR1 to daemon")
        else:
            log.warning("no running daemon, doing direct fetch")
            data = asyncio.run(do_fetch())
            write_cache(data)
            print(json.dumps(data))
    elif "--toggle" in sys.argv:
        if send_signal(signal.SIGUSR2):
            log.info("sent SIGUSR2 to daemon")
        else:
            log.warning("no running daemon")
    else:
        data = asyncio.run(do_fetch())
        write_cache(data)
        print(json.dumps(data))

if __name__ == "__main__":
    main()
