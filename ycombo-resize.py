#!/usr/bin/env python3
"""
YCOMBO — resize daemon

Drag the ⠿ grip (bottom-right 35×35 px of the eww window) to resize.

  Width  → XConfigureWindow directly from the XRecord event loop (instant).
  Height → eww variable 'ycombo-scroll-height' controls the scroll area.
           GTK auto-expands but won't auto-shrink, so after every eww update
           the updater thread also forces XConfigureWindow height when the
           new size is smaller than the current window height.

           Two separate Xlib connections are used so each thread has its own
           exclusive display handle (Xlib is not thread-safe):
             ops        — width configure, used only in the XRecord thread
             height_ops — height configure, used only in EwwHeightUpdater

  fixed_h = window height when scroll variable == DEF_SCROLL (420 px).
            Measured at startup after GTK settles. Scroll height is then:
              scroll_height = window_height - fixed_h

Width  persisted → ~/.local/share/ycombo/width
Height persisted → ~/.local/share/ycombo/scroll-height

Requires: python-xlib  (pacman -S python-xlib)
"""

import os
import sys
import time
import struct
import subprocess
import threading

try:
    from Xlib import X, display as xdisplay
    from Xlib.ext import record
except ImportError:
    print("python-xlib not found: pacman -S python-xlib", file=sys.stderr)
    sys.exit(1)

# ── constants ─────────────────────────────────────────────────────────────────

EWW_CFG    = "/home/archie/Documents/Github-Projects/ycombo/eww"
WIN_NAME   = "Eww - ycombo"
WIDTH_SAVE  = os.path.expanduser("~/.local/share/ycombo/width")
HEIGHT_SAVE = os.path.expanduser("~/.local/share/ycombo/scroll-height")

GRIP_PX   = 35      # bottom-right corner square that activates drag (px)
MIN_WIDTH  = 500
MAX_WIDTH  = 1920
MIN_SCROLL = 150
MAX_SCROLL = 1400
DEF_SCROLL = 420    # matches defvar default in eww.yuck

os.makedirs(os.path.dirname(WIDTH_SAVE), exist_ok=True)

# X11 events are fixed 32-byte packets.
# ButtonPress(4), ButtonRelease(5), MotionNotify(6) share this layout:
#   [0]    type
#   [1]    detail  (button number / is_hint)
#   [2-3]  sequence number
#   [4-7]  timestamp
#   [8-11] root window id
#  [12-15] event window id
#  [16-19] child window id
#  [20-21] root_x  (signed 16-bit LE)
#  [22-23] root_y
_EV_SIZE   = 32
_EV_STRUCT = struct.Struct("<BBHIIIIhh")


# ── persistence ───────────────────────────────────────────────────────────────

def _read(path: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(open(path).read().strip())))
    except Exception:
        return default

def _save(path: str, value: int) -> None:
    try:
        open(path, "w").write(str(value))
    except Exception:
        pass


# ── window helpers ────────────────────────────────────────────────────────────

def find_eww_id(disp) -> int | None:
    """Return the X11 window ID of the eww ycombo window, or None."""
    try:
        for win in disp.screen().root.query_tree().children:
            try:
                if win.get_wm_name() == WIN_NAME:
                    return win.id
            except Exception:
                continue
    except Exception:
        pass
    return None

def win_from(disp, wid: int):
    return disp.create_resource_object("window", wid)

def get_geom(disp, wid: int) -> tuple[int,int,int,int] | None:
    try:
        g = win_from(disp, wid).get_geometry()
        return g.x, g.y, g.width, g.height
    except Exception:
        return None


# ── eww height updater ────────────────────────────────────────────────────────

class EwwHeightUpdater(threading.Thread):
    """
    Background thread that serialises scroll-height updates.

    For each queued value h:
      1. Call `eww update ycombo-scroll-height=h`  (GTK expands/sets variable)
      2. If the resulting target window height < current window height
         (GTK won't auto-shrink), force it via XConfigureWindow on height_ops.

    Uses its own Xlib display connection (height_ops) so it never races with
    the XRecord thread that uses ops.
    """

    def __init__(self, wid_ref: "list[int|None]", fixed_h_ref: "list[int]") -> None:
        super().__init__(daemon=True)
        self._wid      = wid_ref      # [window_id]  — written by main thread
        self._fixed_h  = fixed_h_ref  # [fixed_h]    — written once at startup
        self._lock     = threading.Lock()
        self._pending: int | None = None
        self._event    = threading.Event()
        self._disp     = xdisplay.Display()   # exclusive to this thread

    def update(self, h: int) -> None:
        with self._lock:
            self._pending = h
        self._event.set()

    def run(self) -> None:
        while True:
            self._event.wait()
            self._event.clear()
            with self._lock:
                h = self._pending
            if h is None:
                continue

            # 1. Update the eww variable — GTK will expand if needed.
            subprocess.run(
                ["eww", "--config", EWW_CFG, "update",
                 f"ycombo-scroll-height={h}"],
                capture_output=True,
            )

            # 2. Force X11 height if we need to shrink (GTK won't do it).
            wid     = self._wid[0]
            fixed_h = self._fixed_h[0]
            if wid is None or fixed_h == 0:
                continue
            target = fixed_h + h
            geom = get_geom(self._disp, wid)
            if geom and target < geom[3]:          # geom[3] = height
                try:
                    win_from(self._disp, wid).configure(height=target)
                    self._disp.flush()
                except Exception:
                    pass


# ── daemon ────────────────────────────────────────────────────────────────────

class ResizeDaemon:
    def __init__(self) -> None:
        self.rec = xdisplay.Display()   # XRecord only
        self.ops = xdisplay.Display()   # width configure (XRecord thread only)

        # Shared state accessed from both threads — use simple types (GIL-safe).
        self._wid:     list[int | None] = [None]
        self._fixed_h: list[int]        = [0]

        self.dragging    = False
        self.start_x     = 0
        self.start_y     = 0
        self.base_w      = 0
        self.base_scroll = 0

        # Geometry snapshot refreshed on every ButtonPress (main thread only).
        self.win_x = 0
        self.win_y = 0
        self.win_h = 0

        self._updater = EwwHeightUpdater(self._wid, self._fixed_h)
        self._updater.start()

    # ── window management ─────────────────────────────────────────────────────

    def _geom(self) -> tuple[int,int,int,int] | None:
        wid = self._wid[0]
        return get_geom(self.ops, wid) if wid else None

    def refresh_win(self) -> bool:
        wid = find_eww_id(self.ops)
        self._wid[0] = wid
        return wid is not None

    def refresh_geom(self) -> bool:
        g = self._geom()
        if g is None:
            self._wid[0] = None
            return False
        self.win_x, self.win_y, self.base_w, self.win_h = g
        return True

    # ── grip detection ────────────────────────────────────────────────────────

    def in_grip(self, rx: int, ry: int) -> bool:
        return (
            rx >= self.win_x + self.base_w - GRIP_PX
            and rx <= self.win_x + self.base_w + 2
            and ry >= self.win_y + self.win_h - GRIP_PX
            and ry <= self.win_y + self.win_h + 2
        )

    # ── resize (width only — height goes via updater thread) ─────────────────

    def apply_width(self, w: int) -> None:
        w = max(MIN_WIDTH, min(MAX_WIDTH, w))
        wid = self._wid[0]
        if wid is None:
            return
        try:
            win_from(self.ops, wid).configure(width=w)
            self.ops.flush()
        except Exception:
            self._wid[0] = None
            self.dragging = False

    # ── XRecord event handler ─────────────────────────────────────────────────

    def on_event(self, reply) -> None:
        if reply.category != record.FromServer or reply.client_swapped:
            return
        data = reply.data
        if not data or len(data) < _EV_SIZE:
            return

        i = 0
        while i + _EV_SIZE <= len(data):
            ev_type, detail, _, _, _, _, _, root_x, root_y = \
                _EV_STRUCT.unpack_from(data, i)
            i += _EV_SIZE
            ev_type &= 0x7F

            if ev_type == X.ButtonPress and detail == 1:
                if not self._wid[0] or not self.refresh_geom():
                    self.refresh_win()
                    continue
                if self.in_grip(root_x, root_y):
                    self.dragging    = True
                    self.start_x     = root_x
                    self.start_y     = root_y
                    self.base_scroll = self.win_h - self._fixed_h[0]

            elif ev_type == X.MotionNotify and self.dragging:
                dx = root_x - self.start_x
                dy = root_y - self.start_y
                new_scroll = max(MIN_SCROLL, min(MAX_SCROLL,
                                                 self.base_scroll + dy))
                self.apply_width(self.base_w + dx)
                self._updater.update(new_scroll)

            elif ev_type == X.ButtonRelease and detail == 1 and self.dragging:
                self.dragging = False
                dy = root_y - self.start_y
                final_scroll = max(MIN_SCROLL, min(MAX_SCROLL,
                                                   self.base_scroll + dy))
                g = self._geom()
                if g:
                    _save(WIDTH_SAVE,  g[2])
                _save(HEIGHT_SAVE, final_scroll)

    # ── startup ───────────────────────────────────────────────────────────────

    def _wait_stable_height(self, timeout: float = 8.0) -> int | None:
        """
        Poll window height until it stops changing for 400 ms.
        Returns the stable height, or None on timeout.
        """
        wid = self._wid[0]
        deadline = time.time() + timeout
        last_h, stable_since = -1, 0.0
        while time.time() < deadline:
            g = get_geom(self.ops, wid)
            if g:
                h = g[3]
                if h != last_h:
                    last_h     = h
                    stable_since = time.time()
                elif time.time() - stable_since >= 0.4:
                    return h
            time.sleep(0.1)
        return last_h if last_h > 0 else None

    def wait_and_init(self, timeout: float = 20.0) -> bool:
        """
        Wait for the eww window to appear, measure fixed_h, restore saved
        dimensions.

        fixed_h is the window height when scroll == DEF_SCROLL.  We wait for
        GTK to settle at that natural height before measuring so the baseline
        is accurate.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.refresh_win():
                time.sleep(0.25)
                continue

            stable_h = self._wait_stable_height()
            if stable_h is None:
                continue

            # The eww variable starts at DEF_SCROLL, so stable_h = fixed + DEF_SCROLL
            fixed_h = stable_h - DEF_SCROLL
            self._fixed_h[0] = fixed_h
            self.refresh_geom()

            # Restore saved width via X11.
            saved_w = _read(WIDTH_SAVE, self.base_w, MIN_WIDTH, MAX_WIDTH)
            if saved_w != self.base_w:
                try:
                    win_from(self.ops, self._wid[0]).configure(width=saved_w)
                    self.ops.flush()
                except Exception:
                    pass

            # Restore saved scroll height — updater handles eww + X11 shrink.
            saved_h = _read(HEIGHT_SAVE, DEF_SCROLL, MIN_SCROLL, MAX_SCROLL)
            self._updater.update(saved_h)
            return True

        return False

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        if not self.wait_and_init():
            print("ycombo-resize: timed out waiting for eww window",
                  file=sys.stderr)
            sys.exit(1)

        ctx = self.rec.record_create_context(
            0,
            [record.AllClients],
            [{
                "core_requests":    (0, 0),
                "core_replies":     (0, 0),
                "ext_requests":     (0, 0, 0, 0),
                "ext_replies":      (0, 0, 0, 0),
                "delivered_events": (0, 0),
                "device_events":    (X.ButtonPress, X.MotionNotify),  # 4–6
                "errors":           (0, 0),
                "client_started":   False,
                "client_died":      False,
            }],
        )
        self.rec.record_enable_context(ctx, self.on_event)
        self.rec.record_free_context(ctx)


if __name__ == "__main__":
    ResizeDaemon().run()
