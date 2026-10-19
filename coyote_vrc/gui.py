"""Graphical interface (tkinter) — black and gold theme.

The GUI only talks to the Engine (engine.py). It never touches Bluetooth directly: it reads the state
every 100 ms (`_refresh`) and sends commands to the Controller. That way the device keeps receiving
packets even if the window freezes or is being dragged.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from . import mcp_register, patterns, protocol
from .control import ControlError
from .uimath import clamp, value_from_x, x_from_value

# ---------------------------------------------------------------------- theme
BG = "#0B0B0B"
PANEL = "#151515"
PANEL_HI = "#222222"
GOLD = "#D4AF37"
GOLD_HI = "#F0CB5A"
GOLD_DIM = "#8A6D1F"
TEXT = "#EDE6D0"
DIM = "#8F896F"
RED = "#E0483E"
RED_DARK = "#8E1F19"
GREEN = "#5DBB63"
FONT = "Segoe UI"

SOURCE_NAMES = {"gui": "window", "osc": "VRChat (OSC)", "ai": "AI", "": "—"}
STATE_STYLE = {  # Bluetooth state -> (color, text)
    "disconnected": (DIM, "Disconnected"),
    "searching": (GOLD, "Searching for the Coyote…"),
    "connecting": (GOLD, "Connecting…"),
    "connected": (GREEN, "Connected"),
    "reconnecting": (GOLD, "Reconnecting…"),
}


# ---------------------------------------------------------------------- basic widgets
def make_label(parent, text="", fg=TEXT, bg=PANEL, font=None, **kw):
    return tk.Label(parent, text=text, fg=fg, bg=bg, font=font or (FONT, 10), anchor="w", **kw)


def make_button(parent, text, command, kind="normal", **kw):
    colors = {
        "normal": dict(bg=PANEL_HI, fg=GOLD, activebackground=GOLD, activeforeground=BG),
        "gold": dict(bg=GOLD, fg=BG, activebackground=GOLD_HI, activeforeground=BG),
        "danger": dict(bg=RED_DARK, fg="#FFFFFF", activebackground=RED, activeforeground="#FFFFFF"),
    }[kind]
    return tk.Button(
        parent, text=text, command=command, relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
        font=(FONT, 10, "bold" if kind != "normal" else "normal"), disabledforeground=DIM,
        highlightthickness=0, **colors, **kw,
    )


def make_check(parent, text, var, command=None):
    return tk.Checkbutton(
        parent, text=text, variable=var, command=command, bg=PANEL, fg=TEXT, selectcolor=BG,
        activebackground=PANEL, activeforeground=GOLD, highlightthickness=0, bd=0,
        font=(FONT, 10), anchor="w", cursor="hand2",
    )


def make_entry(parent, var, width=12):
    return tk.Entry(
        parent, textvariable=var, width=width, bg=BG, fg=TEXT, insertbackground=GOLD, relief="flat",
        highlightthickness=1, highlightbackground=GOLD_DIM, highlightcolor=GOLD, font=(FONT, 10),
    )


def make_option_menu(parent, var, values, command=None):
    om = tk.OptionMenu(parent, var, *values, command=command)
    om.config(
        bg=PANEL_HI, fg=GOLD, activebackground=GOLD_DIM, activeforeground=TEXT, highlightthickness=0,
        bd=0, relief="flat", anchor="w", font=(FONT, 10), cursor="hand2",
    )
    om["menu"].config(bg=PANEL_HI, fg=TEXT, activebackground=GOLD, activeforeground=BG, bd=0, font=(FONT, 10))
    return om


def set_text(label, text, fg=None):
    """Only touches the widget if something changed (avoids flicker every 100 ms)."""
    if str(label.cget("text")) != text:
        label.config(text=text)
    if fg is not None and str(label.cget("fg")).lower() != fg.lower():
        label.config(fg=fg)


class Card(tk.Frame):
    """Box with a thin gold border and a title."""

    def __init__(self, parent, title):
        super().__init__(parent, bg=PANEL, highlightthickness=1, highlightbackground=GOLD_DIM)
        tk.Label(self, text=title, fg=GOLD, bg=PANEL, font=(FONT, 11, "bold"), anchor="w").pack(
            fill="x", padx=12, pady=(8, 0))
        tk.Frame(self, bg=GOLD_DIM, height=1).pack(fill="x", padx=12, pady=(4, 6))
        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill="both", expand=True, padx=12, pady=(0, 10))


class GoldSlider(tk.Canvas):
    """Hand-drawn slider (ttk.Scale does not accept the gold theme).

    `command(value)` runs while the user drags; `release(value)` runs on release.
    `set()` (called by the program) is ignored while the user is dragging.
    `limit` shows a blocked red band above the ceiling; `marker` shows a ▼ (actual output value).
    """

    PAD = 12

    def __init__(self, parent, vmin, vmax, value=None, resolution=1.0, command=None, release=None,
                 limit=None, height=30):
        super().__init__(parent, height=height, bg=PANEL, highlightthickness=0, bd=0, takefocus=1)
        self.vmin, self.vmax, self.res = float(vmin), float(vmax), float(resolution)
        self.value = float(vmin if value is None else value)
        self.limit = None if limit is None else float(limit)
        self.marker = None
        self.enabled = True
        self.dragging = False
        self.command, self.release = command, release
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._up)
        for key, direction in (("Left", -1), ("Down", -1), ("Right", 1), ("Up", 1)):
            self.bind(f"<{key}>", lambda e, d=direction: self._key(d, 1))
            self.bind(f"<Shift-{key}>", lambda e, d=direction: self._key(d, 10))

    # ---- called by the program
    def set(self, value):
        if self.dragging:
            return
        value = clamp(float(value), self.vmin, self.vmax)
        if value != self.value:
            self.value = value
            self._draw()

    def set_limit(self, limit):
        limit = None if limit is None else float(limit)
        if limit != self.limit:
            self.limit = limit
            self._draw()

    def set_marker(self, marker):
        marker = None if marker is None else float(marker)
        if marker != self.marker:
            self.marker = marker
            self._draw()

    def set_enabled(self, enabled):
        if enabled != self.enabled:
            self.enabled = enabled
            self._draw()

    # ---- user input
    def _width(self):
        return max(60, self.winfo_width())

    def _clip(self, value):
        value = clamp(value, self.vmin, self.vmax)
        return min(value, self.limit) if self.limit is not None else value

    def _user_set(self, value):
        value = self._clip(value)
        if value != self.value:
            self.value = value
            self._draw()
            if self.command:
                self.command(value)

    def _press(self, event):
        self.focus_set()
        if not self.enabled:
            return
        self.dragging = True
        self._user_set(value_from_x(event.x, self._width(), self.PAD, self.vmin, self.vmax, self.res))

    def _drag(self, event):
        if self.dragging:
            self._user_set(value_from_x(event.x, self._width(), self.PAD, self.vmin, self.vmax, self.res))

    def _up(self, _event):
        if not self.dragging:
            return
        self.dragging = False
        if self.release:
            self.release(self.value)

    def _key(self, direction, mult):
        if not self.enabled:
            return
        self._user_set(self.value + direction * self.res * mult)
        if self.release:
            self.release(self.value)

    # ---- drawing
    def _draw(self):
        self.delete("all")
        w, h = self._width(), int(self.cget("height"))
        mid = h // 2
        x0, x1 = self.PAD, w - self.PAD
        fill = GOLD if self.enabled else "#5A5030"
        self.create_line(x0, mid, x1, mid, fill="#2A2A2A", width=6, capstyle="round")
        xv = x_from_value(self.value, w, self.PAD, self.vmin, self.vmax)
        if self.limit is not None and self.limit < self.vmax:
            xl = x_from_value(self.limit, w, self.PAD, self.vmin, self.vmax)
            self.create_line(xl, mid, x1, mid, fill="#4A1B17", width=6, capstyle="round")
        if xv > x0:
            self.create_line(x0, mid, xv, mid, fill=fill, width=6, capstyle="round")
        if self.limit is not None and self.limit < self.vmax:
            self.create_line(xl, mid - 9, xl, mid + 9, fill=RED, width=2)
        if self.marker is not None:
            xm = x_from_value(self.marker, w, self.PAD, self.vmin, self.vmax)
            self.create_polygon(xm, mid - 6, xm - 4, mid - 13, xm + 4, mid - 13, fill=GOLD_HI, outline="")
        self.create_oval(xv - 8, mid - 8, xv + 8, mid + 8, fill=fill if self.enabled else "#3A3520",
                         outline=BG, width=2)


class Chip(tk.Frame):
    """Colored dot + text, used in the header."""

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.dot = tk.Label(self, text="●", bg=BG, fg=DIM, font=(FONT, 12))
        self.dot.pack(side="left")
        self.text = tk.Label(self, text="", bg=BG, fg=TEXT, font=(FONT, 10))
        self.text.pack(side="left", padx=(3, 14))

    def show(self, color, text):
        set_text(self.dot, "●", color)
        set_text(self.text, text)


class Scrollable(tk.Frame):
    """Scrollable area (for small screens). The header with the STOP button stays outside it."""

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, yscrollincrement=24)
        self.vbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")
        self.inner = tk.Frame(self.canvas, bg=BG)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))

    def wheel(self, delta):
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return  # everything fits: nothing to scroll
        step = -1 if delta > 0 else 1
        self.canvas.yview_scroll(step * max(1, abs(int(delta)) // 120), "units")


# ---------------------------------------------------------------------- panels
class ChannelPanel(Card):
    def __init__(self, parent, app, idx):
        self.ch = "AB"[idx]
        super().__init__(parent, f"CHANNEL {self.ch}")
        self.app = app
        b = self.body

        top = tk.Frame(b, bg=PANEL)
        top.pack(fill="x")
        make_label(top, "Intensity (0–200)", fg=DIM).pack(side="left")
        self.lbl_int = make_label(top, "0", fg=GOLD, font=(FONT, 22, "bold"))
        self.lbl_int.pack(side="right")
        self.s_int = GoldSlider(b, 0, 200, command=self._on_int, limit=200)
        self.s_int.pack(fill="x")

        row = tk.Frame(b, bg=PANEL)
        row.pack(fill="x", pady=(2, 8))
        for text, delta in (("-10", -10), ("-1", -1), ("+1", 1), ("+10", 10)):
            make_button(row, text, lambda d=delta: self._nudge(d)).pack(side="left", padx=(0, 4))
        make_button(row, "Zero", self._zero).pack(side="right")

        self.lbl_f = make_label(b, "", fg=TEXT)
        self.lbl_f.pack(fill="x")
        self.s_f = GoldSlider(b, 1, 100, resolution=1, command=self._on_freq)
        self.s_f.pack(fill="x")

        self.lbl_w = make_label(b, "", fg=TEXT)
        self.lbl_w.pack(fill="x")
        self.s_w = GoldSlider(b, 0, 100, resolution=1, command=self._on_width)
        self.s_w.pack(fill="x")

        self.lbl_info = make_label(b, "", fg=DIM, font=(FONT, 9))
        self.lbl_info.pack(fill="x", pady=(4, 0))

    def _on_int(self, v):
        self.app.do(self.app.engine.control.set_intensity, self.ch, v, "gui")

    def _on_freq(self, v):
        self.app.do(self.app.engine.control.set_frequency, self.ch, v, "gui")

    def _on_width(self, v):
        self.app.do(self.app.engine.control.set_width, self.ch, v, "gui")

    def _nudge(self, delta):
        current = self.app.engine.control.snapshot()["channels"][self.ch]["target"]
        self.app.do(self.app.engine.control.set_intensity, self.ch, current + delta, "gui")

    def _zero(self):
        self.app.do(self.app.engine.control.set_intensity, self.ch, 0, "gui")

    def refresh(self, ch, limit, estopped):
        self.s_int.set_limit(limit)
        self.s_int.set_enabled(not estopped)
        self.s_int.set(ch["target"])
        self.s_int.set_marker(ch["output"] if ch["output"] != ch["target"] else None)
        self.s_f.set(ch["freq_hz"])
        self.s_w.set(ch["width"])
        set_text(self.lbl_int, f"{ch['target']:.0f}")
        hz = max(1.0, ch["freq_hz"])
        set_text(self.lbl_f, f"Frequency: {ch['freq_hz']:.0f} Hz   (period {1000.0 / hz:.0f} ms)")
        set_text(self.lbl_w, f"Pulse width: {ch['width']:.0f}")
        info = f"output now: {ch['output']:.0f}"
        if ch["actual"] is not None:
            info += f"  ·  device confirmed: {ch['actual']}"
        info += f"  ·  last command: {SOURCE_NAMES.get(ch['source'], ch['source'])}"
        set_text(self.lbl_info, info)


class BluetoothCard(Card):
    def __init__(self, parent, app):
        super().__init__(parent, "BLUETOOTH CONNECTION")
        self.app = app
        b = self.body
        top = tk.Frame(b, bg=PANEL)
        top.pack(fill="x")
        self.dot = make_label(top, "●", fg=DIM, font=(FONT, 16))
        self.dot.pack(side="left")
        self.lbl_state = make_label(top, "Disconnected", fg=TEXT, font=(FONT, 12, "bold"))
        self.lbl_state.pack(side="left", padx=6)
        self.lbl_battery = make_label(top, "", fg=GOLD)
        self.lbl_battery.pack(side="right")
        self.lbl_detail = make_label(b, "", fg=DIM, font=(FONT, 9), wraplength=330, justify="left")
        self.lbl_detail.pack(fill="x")

        self._labels: dict[str, str] = {}
        self.v_dev = tk.StringVar(value="(use Scan to list devices)")
        self.menu = make_option_menu(b, self.v_dev, ["(use Scan to list devices)"])
        self.menu.pack(fill="x", pady=(8, 4))

        row = tk.Frame(b, bg=PANEL)
        row.pack(fill="x")
        self.btn_scan = make_button(row, "Scan", self._scan)
        self.btn_scan.pack(side="left", padx=(0, 4))
        make_button(row, "Connect", self._connect, "gold").pack(side="left", padx=(0, 4))
        make_button(row, "Disconnect", self._disconnect).pack(side="left")

        self.v_auto = tk.BooleanVar(value=app.engine.settings.auto_reconnect)
        make_check(b, "Reconnect automatically if it drops", self.v_auto, self._auto).pack(fill="x", pady=(6, 0))
        self.lbl_err = make_label(b, "", fg=RED, font=(FONT, 9), wraplength=330, justify="left")
        self.lbl_err.pack(fill="x")

    def _auto(self):
        self.app.engine.settings.auto_reconnect = bool(self.v_auto.get())
        self.app.engine.save()

    def _scan(self):
        self.btn_scan.config(state="disabled", text="Scanning…")
        self._poll(self.app.engine.scan())

    def _poll(self, future):
        if not future.done():
            self.after(200, lambda: self._poll(future))
            return
        self.btn_scan.config(state="normal", text="Scan")
        try:
            devices = future.result()
        except Exception as exc:
            self.app.flash(f"Scan failed: {exc}", RED)
            return
        self._labels = {}
        for d in devices:
            rssi = f"  {d['rssi']} dBm" if d.get("rssi") is not None else ""
            label = f"{d['name'] or '(no name)'}  [{d['address']}]{rssi}"
            self._labels[label] = d["address"]
        menu = self.menu["menu"]
        menu.delete(0, "end")
        if not self._labels:
            self.v_dev.set("(no device found)")
            self.app.flash("No Bluetooth device found. Is the Coyote on and nearby?", RED)
            return
        for label in self._labels:
            menu.add_command(label=label, command=lambda l=label: self.v_dev.set(l))
        coyote = [l for l in self._labels if l.startswith(protocol.DEVICE_NAME)]
        self.v_dev.set(coyote[0] if coyote else next(iter(self._labels)))
        self.app.flash(f"{len(self._labels)} device(s) found.", GOLD)

    def _connect(self):
        self.app.engine.connect(self._labels.get(self.v_dev.get()))

    def _disconnect(self):
        self.app.engine.disconnect()

    def refresh(self, link):
        color, text = STATE_STYLE.get(link["state"], (DIM, link["state"]))
        set_text(self.dot, "●", color)
        set_text(self.lbl_state, text)
        set_text(self.lbl_battery, f"battery {link['battery']}%" if link["battery"] is not None else "")
        detail = ""
        if link["name"]:
            detail = f"{link['name']}  [{link['address']}]"
        set_text(self.lbl_detail, detail)
        set_text(self.lbl_err, link["error"] or "")


class OscCard(Card):
    def __init__(self, parent, app):
        super().__init__(parent, "VRCHAT OSC")
        self.app = app
        s = app.engine.settings
        b = self.body
        self.lbl_status = make_label(b, "", fg=DIM, wraplength=330, justify="left")
        self.lbl_status.pack(fill="x")
        self.lbl_values = make_label(b, "", fg=GOLD, font=(FONT, 9))
        self.lbl_values.pack(fill="x", pady=(0, 6))

        self.v_enabled = tk.BooleanVar(value=s.osc_enabled)
        make_check(b, "Listen to VRChat", self.v_enabled).pack(fill="x")

        grid = tk.Frame(b, bg=PANEL)
        grid.pack(fill="x", pady=4)
        self.vars = {}
        rows = (
            ("Address", "osc_host", 14), ("Port (VRChat sends on 9001)", "osc_port", 8),
            ("Channel A parameter", "osc_param_a", 16), ("Channel B parameter", "osc_param_b", 16),
            ("Stop parameter (bool)", "osc_param_stop", 16),
            ("Frequency parameter (int Hz)", "osc_param_freq", 16),
        )
        for r, (text, attr, width) in enumerate(rows):
            make_label(grid, text, fg=DIM).grid(row=r, column=0, sticky="w", pady=2)
            var = tk.StringVar()
            self.vars[attr] = var
            make_entry(grid, var, width).grid(row=r, column=1, sticky="e", padx=(8, 0), pady=2)
        grid.columnconfigure(0, weight=1)
        self._load_fields()

        row = tk.Frame(b, bg=PANEL)
        row.pack(fill="x", pady=(4, 0))
        make_button(row, "Apply and restart OSC", self._apply, "gold").pack(side="left")
        make_label(b, "The names are the /avatar/parameters/<name> ones on your avatar.", fg=DIM,
                   font=(FONT, 9), wraplength=330, justify="left").pack(fill="x", pady=(4, 0))

    def _load_fields(self):
        s = self.app.engine.settings
        for attr, var in self.vars.items():
            var.set(str(getattr(s, attr)))
        self.v_enabled.set(s.osc_enabled)

    def _apply(self):
        s = self.app.engine.settings
        try:
            port = int(self.vars["osc_port"].get().strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.app.flash("Invalid port: use a number from 1 to 65535.", RED)
            return
        s.osc_enabled = bool(self.v_enabled.get())
        s.osc_host = self.vars["osc_host"].get().strip() or "127.0.0.1"
        s.osc_port = port
        for attr in ("osc_param_a", "osc_param_b", "osc_param_stop", "osc_param_freq"):
            setattr(s, attr, self.vars[attr].get().strip())
        s.validate()
        self.app.engine.save()
        self.app.engine.start_osc()
        self._load_fields()
        err = self.app.engine.osc_error
        self.app.flash(err if err else "OSC restarted.", RED if err else GOLD)

    def refresh(self, osc, snap_osc):
        if osc["error"]:
            set_text(self.lbl_status, "● " + osc["error"], RED)
        elif not osc["enabled"]:
            set_text(self.lbl_status, "● OSC disabled", DIM)
        elif osc["listening"]:
            age = snap_osc["last_packet_age_s"]
            seen = "no packet yet" if age is None else f"last packet {age:.1f} s ago"
            set_text(self.lbl_status,
                     f"● Listening on {osc['host']}:{osc['port']}  ·  {osc['packets']} packets  ·  {seen}", GREEN)
        else:
            set_text(self.lbl_status, "● OSC stopped", DIM)

        def fmt(v):
            return "—" if v is None else f"{v * 100:.0f}%"
        set_text(self.lbl_values, f"last value received:  A {fmt(snap_osc['A'])}   ·   B {fmt(snap_osc['B'])}")


class PatternCard(Card):
    def __init__(self, parent, app):
        super().__init__(parent, "PATTERNS")
        self.app = app
        b = self.body
        self.by_label = {p.label: p.key for p in patterns.PATTERNS.values()}
        first = patterns.PATTERNS[patterns.DEFAULT_PATTERN].label
        self.v_name = tk.StringVar(value=first)
        make_option_menu(b, self.v_name, list(self.by_label), command=self._on_name).pack(fill="x")
        self.lbl_desc = make_label(b, "", fg=DIM, font=(FONT, 9), wraplength=330, justify="left")
        self.lbl_desc.pack(fill="x", pady=(2, 4))

        self.lbl_speed = make_label(b, "", fg=TEXT)
        self.lbl_speed.pack(fill="x")
        self.s_speed = GoldSlider(b, 0.25, 4.0, value=1.0, resolution=0.05, command=self._on_speed)
        self.s_speed.pack(fill="x")

        row = tk.Frame(b, bg=PANEL)
        row.pack(fill="x", pady=(4, 0))
        make_label(row, "Apply to:", fg=DIM).pack(side="left")
        self.v_a = tk.BooleanVar(value=True)
        self.v_b = tk.BooleanVar(value=True)
        self.v_alt = tk.BooleanVar(value=False)
        make_check(row, "A", self.v_a, self._on_channels).pack(side="left", padx=(6, 0))
        make_check(row, "B", self.v_b, self._on_channels).pack(side="left", padx=(6, 0))
        make_check(b, "Alternate A/B (B starts half a cycle later)", self.v_alt, self._on_alt).pack(fill="x")
        make_label(b, "A pattern changes the waveform (Hz and width); the intensity still comes from the sliders/OSC.",
                   fg=DIM, font=(FONT, 9), wraplength=330, justify="left").pack(fill="x", pady=(4, 0))

    def _on_name(self, label):
        self.app.do(self.app.engine.control.set_pattern, self.by_label[label])

    def _on_speed(self, v):
        self.app.do(self.app.engine.control.set_pattern, None, v)

    def _on_channels(self):
        chans = "".join(n for n, var in (("A", self.v_a), ("B", self.v_b)) if var.get())
        self.app.do(self.app.engine.control.set_pattern, None, None, chans)

    def _on_alt(self):
        self.app.do(self.app.engine.control.set_pattern, None, None, None, bool(self.v_alt.get()))

    def refresh(self, pat):
        label = patterns.PATTERNS[pat["name"]].label
        if self.v_name.get() != label:
            self.v_name.set(label)
        set_text(self.lbl_desc, patterns.PATTERNS[pat["name"]].description)
        self.s_speed.set(pat["speed"])
        set_text(self.lbl_speed, f"Speed: ×{pat['speed']:.2f}")
        for var, letter in ((self.v_a, "A"), (self.v_b, "B")):
            if var.get() != (letter in pat["channels"]):
                var.set(letter in pat["channels"])
        if self.v_alt.get() != pat["alternate"]:
            self.v_alt.set(pat["alternate"])


class AiCard(Card):
    def __init__(self, parent, app):
        super().__init__(parent, "AI (CLAUDE CODE / MCP)")
        self.app = app
        s = app.engine.settings
        b = self.body
        self.v_enabled = tk.BooleanVar(value=False)
        make_check(b, "Allow an AI to control (always starts off)", self.v_enabled,
                   self._toggle).pack(fill="x")
        self.lbl_cap = make_label(b, "", fg=TEXT)
        self.lbl_cap.pack(fill="x", pady=(6, 0))
        self.s_cap = GoldSlider(b, 0, 200, value=s.ai_cap, command=self._cap_label, release=self._cap_apply)
        self.s_cap.pack(fill="x")
        self.lbl_last = make_label(b, "", fg=DIM, font=(FONT, 9), wraplength=330, justify="left")
        self.lbl_last.pack(fill="x", pady=(2, 0))
        self.lbl_api = make_label(b, "", fg=DIM, font=(FONT, 9), wraplength=330, justify="left")
        self.lbl_api.pack(fill="x")
        row = tk.Frame(b, bg=PANEL)
        row.pack(fill="x", pady=(6, 0))
        make_button(row, "Copy MCP command", self._copy_cmd, "gold").pack(side="left", padx=(0, 4))
        make_button(row, "Copy token", self._copy_token).pack(side="left")
        row2 = tk.Frame(b, bg=PANEL)
        row2.pack(fill="x", pady=(4, 0))
        make_button(row2, "Register in the Claude Desktop app", self._register_desktop).pack(side="left")
        make_label(b, "Claude Code (terminal): paste the copied command into a terminal, once. Claude app/chat: "
                      "click Register, then fully quit and reopen the Claude app. "
                      "Only this window can re-enable after STOP ALL.",
                   fg=DIM, font=(FONT, 9), wraplength=330, justify="left").pack(fill="x", pady=(6, 0))

    @staticmethod
    def mcp_script():
        return Path(__file__).resolve().parent.parent / "coyote_mcp.py"

    def mcp_command(self):
        return f'claude mcp add --scope user coyote -- "{mcp_register.python_for_mcp()}" "{self.mcp_script()}"'

    def _register_desktop(self):
        results = mcp_register.register_desktop(mcp_register.python_for_mcp(), str(self.mcp_script()))
        good = [r for r in results if r.action != "error"]
        for r in results:
            self.app.engine.control.log(
                f"Claude Desktop: {r.action} {r.path}" + (f" ({r.error})" if r.error else ""))
        if good:
            where = "; ".join(str(r.path) for r in good)
            self.app.flash(f"MCP registered in {where}. Now fully quit and reopen the Claude app.", GOLD, 15000)
        else:
            self.app.flash("Could not register in Claude Desktop: " + results[0].error, RED, 15000)

    def _clip(self, text, what):
        self.app.clipboard_clear()
        self.app.clipboard_append(text)
        self.app.update()
        self.app.flash(f"{what} copied to the clipboard.", GOLD)

    def _copy_cmd(self):
        self._clip(self.mcp_command(), "Command")

    def _copy_token(self):
        self._clip(self.app.engine.settings.api_token, "Token")

    def _toggle(self):
        want = bool(self.v_enabled.get())
        if want:
            s = self.app.engine.settings
            limit = min(s.ai_cap, s.max_intensity)
            ok = messagebox.askyesno(
                "Allow AI control",
                "An AI connected to this program will be able to change the intensity (up to "
                f"{limit}), the frequency and the patterns of your Coyote.\n\n"
                "You can revoke this at any time: untick the box or click STOP ALL.\n\n"
                "Allow?",
                parent=self.app,
            )
            if not ok:
                self.v_enabled.set(False)
                return
        self.app.engine.configure(ai_enabled=want)

    def _cap_label(self, v):
        set_text(self.lbl_cap, f"Maximum intensity the AI may request: {v:.0f}")

    def _cap_apply(self, v):
        self.app.engine.configure(ai_cap=int(v))

    def refresh(self, lim, ai_last, api_ok, api_error, port):
        if self.v_enabled.get() != lim["ai_enabled"]:
            self.v_enabled.set(lim["ai_enabled"])
        self.s_cap.set(lim["ai_cap"])
        shown = self.s_cap.value
        effective = min(shown, lim["max_intensity"])
        text = f"Maximum intensity the AI may request: {shown:.0f}"
        if effective != shown:
            text += f"  (effectively {effective:.0f}, because of the global ceiling)"
        set_text(self.lbl_cap, text)
        set_text(self.lbl_last, "Last AI action: " + (ai_last or "—"))
        if api_error:
            set_text(self.lbl_api, "Local API: " + api_error, RED)
        elif api_ok:
            set_text(self.lbl_api, f"Local API ready at 127.0.0.1:{port} (this computer only)", DIM)
        else:
            set_text(self.lbl_api, "Local API stopped", DIM)


class LimitsCard(Card):
    def __init__(self, parent, app):
        super().__init__(parent, "SAFETY LIMITS")
        self.app = app
        s = app.engine.settings
        b = self.body

        self.lbl_max = make_label(b, "", fg=TEXT)
        self.lbl_max.pack(fill="x")
        self.s_max = GoldSlider(b, 0, 200, value=s.max_intensity, command=self._max_label,
                                release=lambda v: app.engine.configure(max_intensity=int(v)))
        self.s_max.pack(fill="x")

        self.lbl_ramp = make_label(b, "", fg=TEXT)
        self.lbl_ramp.pack(fill="x", pady=(4, 0))
        self.s_ramp = GoldSlider(b, 0, 400, value=s.ramp_up_per_s, resolution=10, command=self._ramp_label,
                                 release=lambda v: app.engine.configure(ramp_up_per_s=int(v)))
        self.s_ramp.pack(fill="x")

        self.lbl_wd = make_label(b, "", fg=TEXT)
        self.lbl_wd.pack(fill="x", pady=(4, 0))
        self.s_wd = GoldSlider(b, 0, 120, value=s.osc_timeout_s, resolution=1, command=self._wd_label,
                               release=lambda v: app.engine.configure(osc_timeout_s=int(v)))
        self.s_wd.pack(fill="x")

        make_label(b, "The global ceiling applies to sliders, VRChat and AI, and is also written to the device itself. "
                      "Increasing intensity is always gradual (ramp); lowering is immediate.",
                   fg=DIM, font=(FONT, 9), wraplength=330, justify="left").pack(fill="x", pady=(6, 0))

    def _max_label(self, v):
        set_text(self.lbl_max, f"Intensity ceiling (all sources): {v:.0f} / 200")

    def _ramp_label(self, v):
        if v <= 0:
            set_text(self.lbl_ramp, "Max rise: unlimited (not recommended)")
        else:
            set_text(self.lbl_ramp, f"Max rise: {v:.0f} per second  (0 → 200 in {200.0 / v:.1f} s)")

    def _wd_label(self, v):
        if v <= 0:
            set_text(self.lbl_wd, "If VRChat goes silent: do not zero (off)")
        else:
            set_text(self.lbl_wd, f"If VRChat is silent for {v:.0f} s: zero the OSC channels")

    def refresh(self, lim):
        self.s_max.set(lim["max_intensity"])
        self.s_ramp.set(lim["ramp_up_per_s"])
        self.s_wd.set(lim["osc_timeout_s"])
        self._max_label(self.s_max.value)
        self._ramp_label(self.s_ramp.value)
        self._wd_label(self.s_wd.value)


class ShockCard(Card):
    """The ShockOSC contact trigger: a touch on the avatar's contact -> a random shock for a few seconds."""

    def __init__(self, parent, app):
        super().__init__(parent, "SHOCK TRIGGER (SHOCKOSC CONTACT)")
        self.app = app
        s = app.engine.settings
        b = self.body
        self.v_enabled = tk.BooleanVar(value=False)
        make_check(b, "Enabled: a touch fires a random shock (always starts off)", self.v_enabled,
                   self._toggle).pack(fill="x")
        self.lbl_state = make_label(b, "", fg=DIM, wraplength=330, justify="left")
        self.lbl_state.pack(fill="x", pady=(2, 6))

        self.lbl_power = make_label(b, "", fg=TEXT, wraplength=330, justify="left")
        self.lbl_power.pack(fill="x")
        make_label(b, "Lowest power (%)", fg=DIM, font=(FONT, 9)).pack(fill="x")
        self.s_min = GoldSlider(b, 1, 100, value=s.shock_min_pct, command=self._on_min, release=self._apply_range)
        self.s_min.pack(fill="x")
        make_label(b, "Highest power (%)", fg=DIM, font=(FONT, 9)).pack(fill="x")
        self.s_max = GoldSlider(b, 1, 100, value=s.shock_max_pct, command=self._on_max, release=self._apply_range)
        self.s_max.pack(fill="x")

        self.lbl_secs = make_label(b, "", fg=TEXT)
        self.lbl_secs.pack(fill="x", pady=(4, 0))
        self.s_secs = GoldSlider(b, 1, 30, value=s.shock_seconds, command=self._secs_label,
                                 release=lambda v: self.app.engine.configure_shock(shock_seconds=int(v)))
        self.s_secs.pack(fill="x")

        self.lbl_cool = make_label(b, "", fg=TEXT)
        self.lbl_cool.pack(fill="x", pady=(4, 0))
        self.s_cool = GoldSlider(b, 0, 120, value=s.shock_cooldown_s, command=self._cool_label,
                                 release=lambda v: self.app.engine.configure_shock(shock_cooldown_s=int(v)))
        self.s_cool.pack(fill="x")

        row = tk.Frame(b, bg=PANEL)
        row.pack(fill="x", pady=(4, 0))
        make_label(row, "Shock channels:", fg=DIM).pack(side="left")
        self.v_a = tk.BooleanVar(value="A" in s.shock_channels)
        self.v_b = tk.BooleanVar(value="B" in s.shock_channels)
        make_check(row, "A", self.v_a, self._on_channels).pack(side="left", padx=(6, 0))
        make_check(row, "B", self.v_b, self._on_channels).pack(side="left", padx=(6, 0))

        self.v_chat = tk.BooleanVar(value=s.chatbox_enabled)
        make_check(b, "Say the power in the VRChat chatbox when a shock starts", self.v_chat,
                   self._on_chat).pack(fill="x", pady=(4, 0))

        grid = tk.Frame(b, bg=PANEL)
        grid.pack(fill="x", pady=4)
        self.vars = {}
        rows = (("Contact parameter (bool)", "osc_param_shock", 16),
                ("Chatbox text ({percent}, {seconds})", "chatbox_text", 16),
                ("Chatbox port (VRChat listens on 9000)", "chatbox_port", 8))
        for r, (text, attr, width) in enumerate(rows):
            make_label(grid, text, fg=DIM).grid(row=r, column=0, sticky="w", pady=2)
            var = tk.StringVar()
            self.vars[attr] = var
            make_entry(grid, var, width).grid(row=r, column=1, sticky="e", padx=(8, 0), pady=2)
        grid.columnconfigure(0, weight=1)
        self._load_fields()

        btns = tk.Frame(b, bg=PANEL)
        btns.pack(fill="x", pady=(2, 0))
        make_button(btns, "Apply", self._apply, "gold").pack(side="left", padx=(0, 4))
        make_button(btns, "Test chatbox", self._test_chatbox).pack(side="left", padx=(0, 4))
        make_button(btns, "Test shock now", self._test_shock).pack(side="left")
        self.lbl_last = make_label(b, "", fg=DIM, font=(FONT, 9), wraplength=330, justify="left")
        self.lbl_last.pack(fill="x", pady=(4, 0))
        make_label(b, "One shock per touch (a contact that stays on does not repeat), then the pause. The power is a "
                      "percentage of the intensity ceiling and follows the rise limit; STOP ALL cancels it. "
                      "Whoever can touch the contact on your avatar can fire it.",
                   fg=DIM, font=(FONT, 9), wraplength=330, justify="left").pack(fill="x", pady=(4, 0))

    # ---- helpers
    def _units(self, pct):
        cap = self.app.engine.control.cap("gui")
        return 0 if cap <= 0 else max(1, int(round(pct * cap / 100.0)))

    def _load_fields(self):
        s = self.app.engine.settings
        for attr, var in self.vars.items():
            var.set(str(getattr(s, attr)))

    def _power_label(self):
        lo, hi = int(self.s_min.value), int(self.s_max.value)
        cap = self.app.engine.control.cap("gui")
        text = f"Random power: {lo}% to {hi}% of the ceiling  =  {self._units(lo)} to {self._units(hi)}"
        if cap != 200:
            text += f"  (ceiling {cap})"
        set_text(self.lbl_power, text)

    def _secs_label(self, v):
        set_text(self.lbl_secs, f"Each shock lasts {v:.0f} s  (up to 30)")

    def _cool_label(self, v):
        set_text(self.lbl_cool, "Pause after a shock: none" if v <= 0 else f"Pause after a shock: {v:.0f} s")

    # ---- actions
    def _toggle(self):
        want = bool(self.v_enabled.get())
        e = self.app.engine
        if want:
            s = e.settings
            lo, hi = s.shock_min_pct, s.shock_max_pct
            ok = messagebox.askyesno(
                "Enable the shock trigger",
                f"Whoever touches the contact {s.osc_param_shock} on your avatar will shock you.\n\n"
                f"Power: a random value between {lo}% and {hi}% of your intensity ceiling "
                f"({self._units(lo)} to {self._units(hi)}), for {s.shock_seconds} s, on channel(s) {s.shock_channels}, "
                f"with {s.shock_cooldown_s} s between shocks.\n\n"
                "The ceiling, the rise limit and STOP ALL still apply. It starts off every time you open the program.\n\n"
                "Enable?",
                parent=self.app,
            )
            if not ok:
                self.v_enabled.set(False)
                return
        e.set_shock_enabled(want)

    def _on_min(self, v):
        if v > self.s_max.value:
            self.s_max.set(v)
        self._power_label()

    def _on_max(self, v):
        if v < self.s_min.value:
            self.s_min.set(v)
        self._power_label()

    def _apply_range(self, _v):
        self.app.engine.configure_shock(shock_min_pct=int(self.s_min.value), shock_max_pct=int(self.s_max.value))

    def _on_channels(self):
        letters = "".join(n for n, var in (("A", self.v_a), ("B", self.v_b)) if var.get())
        if not letters:
            self.app.flash("Pick at least one channel for the shock.", RED)
            self.v_a.set("A" in self.app.engine.settings.shock_channels)
            self.v_b.set("B" in self.app.engine.settings.shock_channels)
            return
        self.app.engine.configure_shock(shock_channels=letters)

    def _on_chat(self):
        self.app.engine.configure_shock(chatbox_enabled=bool(self.v_chat.get()))

    def _apply(self):
        try:
            port = int(self.vars["chatbox_port"].get().strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.app.flash("Invalid chatbox port: use a number from 1 to 65535.", RED)
            return
        self.app.engine.configure_shock(
            osc_param_shock=self.vars["osc_param_shock"].get().strip(),
            chatbox_text=self.vars["chatbox_text"].get(),
            chatbox_port=port,
        )
        self._load_fields()
        self.app.flash("Shock trigger settings applied.", GOLD)

    def _test_chatbox(self):
        s = self.app.engine.settings
        if self.app.engine.test_chatbox():
            self.app.flash(f"Test message sent to the VRChat chatbox ({s.chatbox_host}:{s.chatbox_port}).", GOLD)
        else:
            self.app.flash("Could not send the chatbox message (see the log).", RED)

    def _test_shock(self):
        res = self.app.engine.test_shock()
        if res["fired"]:
            self.app.flash(f"Test shock: {res['percent']}% for {res['seconds']:.0f} s.", GOLD)
        else:
            self.app.flash("No shock: " + res["reason"], RED)

    # ---- periodic refresh
    def refresh(self, st, lim):
        s = self.app.engine.settings
        if self.v_enabled.get() != st["enabled"]:
            self.v_enabled.set(st["enabled"])
        if not (self.s_min.dragging or self.s_max.dragging):
            self.s_min.set(s.shock_min_pct)
            self.s_max.set(s.shock_max_pct)
        self.s_secs.set(s.shock_seconds)
        self.s_cool.set(s.shock_cooldown_s)
        for var, letter in ((self.v_a, "A"), (self.v_b, "B")):
            if var.get() != (letter in s.shock_channels):
                var.set(letter in s.shock_channels)
        if self.v_chat.get() != s.chatbox_enabled:
            self.v_chat.set(s.chatbox_enabled)
        self._power_label()
        self._secs_label(self.s_secs.value)
        self._cool_label(self.s_cool.value)

        if not st["enabled"]:
            set_text(self.lbl_state, "● Off: touching the contact does nothing", DIM)
        elif st["active"]:
            lv = st["level"]
            set_text(self.lbl_state,
                     f"● SHOCK  A {lv['A']:.0f}  ·  B {lv['B']:.0f}  ·  {st['remaining_s']:.1f} s left", RED)
        elif st["estopped"]:
            set_text(self.lbl_state, "● Armed, but the emergency stop is active: touches are ignored", RED)
        elif not st["connected"]:
            set_text(self.lbl_state, "● Armed, but the Coyote is not connected: touches are ignored", GOLD)
        elif st["cooldown_s"] > 0:
            set_text(self.lbl_state, f"● Pausing between shocks: {st['cooldown_s']:.0f} s", GOLD)
        else:
            set_text(self.lbl_state, f"● Armed: waiting for a touch on {s.osc_param_shock or '(no parameter set)'}", GREEN)
        set_text(self.lbl_last, "Last shock: " + (st["last"] or "none yet"))


class LogCard(Card):
    MAX_LINES = 400

    def __init__(self, parent):
        super().__init__(parent, "LOG")
        self.text = tk.Text(
            self.body, height=14, width=44, bg="#050505", fg=TEXT, relief="flat", wrap="word",
            highlightthickness=1, highlightbackground=GOLD_DIM, font=("Consolas", 9), state="disabled",
        )
        bar = tk.Scrollbar(self.body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

    def append(self, lines):
        self.text.config(state="normal")
        for line in lines:
            self.text.insert("end", line + "\n")
        total = int(self.text.index("end-1c").split(".")[0])
        if total > self.MAX_LINES:
            self.text.delete("1.0", f"{total - self.MAX_LINES + 1}.0")
        self.text.see("end")
        self.text.config(state="disabled")


# ---------------------------------------------------------------------- main window
class App(tk.Tk):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self._closing = False
        self._estop_shown = None
        self._flash_job = None
        self._log_n = 0
        self._refresh_errors = 0

        self.title("Coyote × VRChat")
        self.configure(bg=BG)
        width = max(900, min(1200, self.winfo_screenwidth() - 80))
        height = max(560, min(820, self.winfo_screenheight() - 120))
        self.geometry(f"{width}x{height}")
        self.minsize(900, 560)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_header()
        self.msg = tk.Label(self, text="", bg=BG, fg=GOLD, font=(FONT, 10), anchor="w")
        self.msg.pack(side="bottom", fill="x", padx=14, pady=(0, 6))
        self.scroll = Scrollable(self)
        self.scroll.pack(fill="both", expand=True)
        self._build_body(self.scroll.inner)

        self.bind_all("<Escape>", lambda e: self.panic())
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.after(100, self._refresh)

    # ---- construction
    def _build_header(self):
        header = tk.Frame(self, bg=BG)
        header.pack(side="top", fill="x", padx=14, pady=(10, 4))
        title = tk.Frame(header, bg=BG)
        title.pack(side="left")
        tk.Label(title, text="COYOTE", fg=GOLD, bg=BG, font=(FONT, 20, "bold")).pack(side="left")
        tk.Label(title, text="  ×  VRChat", fg=DIM, bg=BG, font=(FONT, 14)).pack(side="left", pady=(5, 0))

        self.btn_stop = tk.Button(
            header, text="STOP ALL  (Esc)", command=self.toggle_stop, relief="flat", bd=0,
            bg=RED_DARK, fg="#FFFFFF", activebackground=RED, activeforeground="#FFFFFF",
            font=(FONT, 12, "bold"), padx=18, pady=8, cursor="hand2",
        )
        self.btn_stop.pack(side="right")

        chips = tk.Frame(header, bg=BG)
        chips.pack(side="right", padx=20)
        self.chip_ble = Chip(chips)
        self.chip_osc = Chip(chips)
        self.chip_ai = Chip(chips)
        self.chip_shock = Chip(chips)
        for chip in (self.chip_ble, self.chip_osc, self.chip_ai, self.chip_shock):
            chip.pack(side="left")
        tk.Frame(self, bg=GOLD_DIM, height=1).pack(side="top", fill="x", padx=14)

    def _build_body(self, inner):
        for c in range(3):
            inner.columnconfigure(c, weight=1, uniform="col")
        cols = []
        for c in range(3):
            frame = tk.Frame(inner, bg=BG)
            frame.grid(row=0, column=c, sticky="nsew", padx=(14 if c == 0 else 6, 14 if c == 2 else 6), pady=10)
            cols.append(frame)

        self.bt = BluetoothCard(cols[0], self)
        self.panel_a = ChannelPanel(cols[0], self, 0)
        self.panel_b = ChannelPanel(cols[0], self, 1)
        self.osc = OscCard(cols[1], self)
        self.pat = PatternCard(cols[1], self)
        self.limits = LimitsCard(cols[1], self)
        self.shock = ShockCard(cols[2], self)
        self.ai = AiCard(cols[2], self)
        self.log = LogCard(cols[2])
        for card in (self.bt, self.panel_a, self.panel_b, self.osc, self.pat, self.limits, self.shock, self.ai):
            card.pack(fill="x", pady=(0, 10))
        self.log.pack(fill="both", expand=True)

    # ---- actions
    def do(self, fn, *args):
        """Runs a Controller command; shows the reason if it is refused (e.g. emergency stop)."""
        try:
            return fn(*args)
        except ControlError as exc:
            self.flash(str(exc), RED)
            return None

    def flash(self, text, color=GOLD, ms=6000):
        self.msg.config(text=text, fg=color)
        if self._flash_job is not None:
            self.after_cancel(self._flash_job)
        self._flash_job = self.after(ms, lambda: self.msg.config(text=""))

    def panic(self):
        self.engine.emergency_stop("gui")
        self.flash("EMERGENCY STOP: everything zeroed. Click RE-ENABLE to control again.", RED, 10000)

    def toggle_stop(self):
        if self.engine.control.estopped:
            self.engine.resume()
            self.flash("Controls re-enabled. All intensities are still at 0.", GOLD)
        else:
            self.panic()

    def _on_wheel(self, event):
        if isinstance(event.widget, tk.Text):
            return  # the log scrolls by itself
        self.scroll.wheel(event.delta)

    def on_close(self):
        self._closing = True
        self.title("Shutting down… (zeroing the device)")
        self.update_idletasks()
        try:
            self.engine.shutdown()
        finally:
            self.destroy()

    # ---- periodic update (100 ms)
    def _refresh(self):
        try:
            self._refresh_once()
        except Exception as exc:  # a drawing error must not stop the update or the device
            self._refresh_errors += 1
            if self._refresh_errors <= 5:
                self.engine.control.log(f"interface error: {exc!r}")
        finally:
            if not self._closing:
                self.after(100, self._refresh)

    def _refresh_once(self):
        e = self.engine
        snap = e.control.snapshot()
        link = e.link.status()
        osc = e.osc_status()
        lim = snap["limits"]
        estop = snap["estopped"]

        if estop != self._estop_shown:
            self._estop_shown = estop
            if estop:
                self.btn_stop.config(text="RE-ENABLE CONTROLS", bg=GOLD, fg=BG, activebackground=GOLD_HI,
                                     activeforeground=BG)
            else:
                self.btn_stop.config(text="STOP ALL  (Esc)", bg=RED_DARK, fg="#FFFFFF", activebackground=RED,
                                     activeforeground="#FFFFFF")

        color, text = STATE_STYLE.get(link["state"], (DIM, link["state"]))
        self.chip_ble.show(color, "Bluetooth: " + text)
        if osc["error"]:
            self.chip_osc.show(RED, "OSC: error")
        elif not osc["enabled"]:
            self.chip_osc.show(DIM, "OSC: disabled")
        elif osc["listening"]:
            age = snap["osc"]["last_packet_age_s"]
            if age is not None and age < 3:
                self.chip_osc.show(GREEN, "OSC: receiving")
            else:
                self.chip_osc.show(GOLD, "OSC: waiting for VRChat")
        else:
            self.chip_osc.show(DIM, "OSC: stopped")
        if lim["ai_enabled"]:
            self.chip_ai.show(GOLD, f"AI: active (up to {min(lim['ai_cap'], lim['max_intensity'])})")
        else:
            self.chip_ai.show(DIM, "AI: disabled")
        shock = e.shock_status()
        if shock["active"]:
            self.chip_shock.show(RED, "Shock: ACTIVE")
        elif shock["enabled"]:
            self.chip_shock.show(GOLD, "Shock trigger: armed")
        else:
            self.chip_shock.show(DIM, "Shock trigger: off")

        self.panel_a.refresh(snap["channels"]["A"], lim["max_intensity"], estop)
        self.panel_b.refresh(snap["channels"]["B"], lim["max_intensity"], estop)
        self.bt.refresh(link)
        self.osc.refresh(osc, snap["osc"])
        self.pat.refresh(snap["pattern"])
        self.limits.refresh(lim)
        self.shock.refresh(shock, lim)
        api = e.api
        self.ai.refresh(lim, snap["ai_last_action"], api is not None, e.api_error,
                        api.port if api is not None else e.settings.api_port)

        self._log_n, lines = e.control.log_since(self._log_n)
        if lines:
            self.log.append(lines)
