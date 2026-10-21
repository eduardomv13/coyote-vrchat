"""SMOKE test of the interface, without opening a window.

This test swaps tkinter for a "fake tkinter" (widgets that only store their options). It can
prove that the GUI logic runs without errors and talks correctly to the Engine (sliders -> intensity,
STOP ALL, patterns, limits, AI, OSC, simulated Bluetooth). It can NOT prove the appearance:
positions, real colors and mouse behavior in a real window can only be seen by opening the app.
"""
import concurrent.futures
import importlib
import re
import socket
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

from coyote_vrc.ble import SimulatedTransport
from coyote_vrc.control import ControlError
from coyote_vrc.engine import Engine
from coyote_vrc.settings import Settings

# ---------------------------------------------------------------------------- tkinter falso


class _W:
    def __init__(self, master=None, *args, **kw):
        self.master = master
        self._opts = dict(kw)
        self._after_jobs = []
        self.destroyed = False

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: None   # pack, grid, bind, columnconfigure, create_line, ...

    def config(self, **kw):
        self._opts.update(kw)

    configure = config

    def cget(self, key):
        return self._opts.get(key, "")

    def __getitem__(self, key):
        return self._opts.get(key)

    def after(self, ms, fn=None, *args):
        self._after_jobs.append((ms, fn))
        return len(self._after_jobs)

    def winfo_width(self):
        return 300

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def yview(self):
        return (0.0, 1.0)

    def bbox(self, *a):
        return (0, 0, 10, 10)

    def title(self, text=None):
        if text is not None:
            self._opts["title"] = text

    def clipboard_clear(self):
        self._opts["clip"] = ""

    def clipboard_append(self, text):
        self._opts["clip"] = self._opts.get("clip", "") + text

    def destroy(self):
        self.destroyed = True


class _Menu(_W):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.entries = []

    def delete(self, a, b=None):
        self.entries = []

    def add_command(self, **kw):
        self.entries.append(kw)


class _OptionMenu(_W):
    def __init__(self, master, variable, value, *values, command=None, **kw):
        super().__init__(master, **kw)
        self.variable, self.values, self.command = variable, (value,) + values, command
        self._menu = _Menu()

    def __getitem__(self, key):
        return self._menu if key == "menu" else self._opts.get(key)


class _Text(_W):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.lines = []

    def insert(self, pos, text):
        self.lines.extend(text.splitlines())

    def index(self, pos):
        return f"{len(self.lines) + 1}.0"

    def delete(self, a, b=None):
        pass


class _Style:
    """ttk.Style: the theme calls are accepted and ignored."""

    def __init__(self, *a, **kw):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: self.calls.append((name, a, k))


class _Notebook(_W):
    """ttk.Notebook: remembers its tabs and which one is showing."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.tabs, self.current = [], 0

    def add(self, child, text=""):
        self.tabs.append((child, text))

    def select(self, index=None):
        if index is not None:
            self.current = index
        return self.current

    def index(self, what):
        return self.current if what == "current" else len(self.tabs)


class _Var:
    def __init__(self, master=None, value=None):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _StringVar(_Var):
    def __init__(self, master=None, value=""):
        super().__init__(master, value)


class _BooleanVar(_Var):
    def __init__(self, master=None, value=False):
        super().__init__(master, value)


def build_fake_tkinter():
    tk = types.ModuleType("tkinter")
    for name in ("Tk", "Frame", "Label", "Button", "Checkbutton", "Entry", "Canvas", "Scrollbar"):
        setattr(tk, name, type(name, (_W,), {}))
    tk.OptionMenu = _OptionMenu
    tk.Text = _Text
    tk.TclError = type("TclError", (Exception,), {})
    ttk = types.ModuleType("tkinter.ttk")
    ttk.Style = _Style
    ttk.Notebook = _Notebook
    tk.ttk = ttk
    tk.StringVar = _StringVar
    tk.BooleanVar = _BooleanVar
    mb = types.ModuleType("tkinter.messagebox")
    mb.answer = True
    mb.asked = []

    def askyesno(title, message, **kw):
        mb.asked.append((title, message))
        return mb.answer

    mb.askyesno = askyesno
    tk.messagebox = mb
    return tk, mb, ttk


_saved = {}
gui = None
fake_mb = None


def setUpModule():
    global gui, fake_mb
    for name in ("tkinter", "tkinter.messagebox", "tkinter.ttk", "coyote_vrc.gui"):
        _saved[name] = sys.modules.get(name)
    tk, fake_mb, fake_ttk = build_fake_tkinter()
    sys.modules["tkinter"] = tk
    sys.modules["tkinter.messagebox"] = fake_mb
    sys.modules["tkinter.ttk"] = fake_ttk
    sys.modules.pop("coyote_vrc.gui", None)
    gui = importlib.import_module("coyote_vrc.gui")


def tearDownModule():
    for name, mod in _saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


def until(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def click(x):
    return types.SimpleNamespace(x=x, delta=120, widget=None)


# ---------------------------------------------------------------------------- testes


class GuiSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        s = Settings().validate()
        s.osc_port = 0          # any free port (validate() requires >= 1, hence afterwards)
        s.api_port = 0
        s.api_token = "token-de-teste"
        s.ramp_up_per_s = 0
        s.chatbox_port = free_port()    # never 9000: a real VRChat on this machine must not receive test messages
        fake_mb.answer = True
        fake_mb.asked.clear()
        self.engine = Engine(settings=s, settings_path=Path(self.tmp.name) / "settings.json",
                             transport=SimulatedTransport())
        self.engine.start()
        self.app = gui.App(self.engine)

    def tearDown(self):
        self.engine.shutdown()
        self.tmp.cleanup()

    def snap(self):
        return self.engine.control.snapshot()

    def refresh(self):
        self.app._refresh_once()

    # ---- base
    def test_theme_colors_are_valid_hex(self):
        for name in ("BG", "PANEL", "PANEL_HI", "GOLD", "GOLD_HI", "GOLD_DIM", "TEXT", "DIM", "RED", "RED_DARK", "GREEN"):
            self.assertRegex(getattr(gui, name), r"^#[0-9A-Fa-f]{6}$", name)
        self.assertEqual((gui.BG.lower(), gui.GOLD.lower()), ("#0b0b0b", "#d4af37"))

    def test_refresh_runs_repeatedly_and_stays_scheduled(self):
        for _ in range(5):
            self.refresh()
        self.assertEqual(self.app._refresh_errors, 0)
        self.app._refresh()   # version with error handling: reschedules itself
        self.assertTrue(any(fn == self.app._refresh for _, fn in self.app._after_jobs))
        self.assertEqual(self.app._refresh_errors, 0)

    def test_refresh_survives_an_internal_error(self):
        self.app._refresh_once = lambda: 1 / 0
        before = len(self.app._after_jobs)
        self.app._refresh()
        self.assertEqual(self.app._refresh_errors, 1)
        self.assertGreater(len(self.app._after_jobs), before)   # stays scheduled

    # ---- sliders
    def test_dragging_intensity_slider_controls_channel(self):
        sl = self.app.panel_a.s_int
        sl._press(click(150))                       # largura 300, folga 12 -> meio ~ 100
        self.assertTrue(sl.dragging)
        self.assertAlmostEqual(self.snap()["channels"]["A"]["target"], 100, delta=2)
        self.refresh()                              # while dragging, the program does not touch the slider
        self.assertTrue(sl.dragging)
        sl._drag(click(9999))                       # past the end -> 200
        self.assertEqual(self.snap()["channels"]["A"]["target"], 200.0)
        sl._up(click(9999))
        self.assertFalse(sl.dragging)
        self.assertEqual(self.snap()["channels"]["B"]["target"], 0.0)

    def test_slider_follows_values_set_by_osc_or_ai(self):
        self.engine.control.set_fraction("B", 0.5, "osc")
        self.refresh()
        self.assertEqual(self.app.panel_b.s_int.value, 100.0)
        self.assertEqual(self.app.panel_b.lbl_int.cget("text"), "100")

    def test_frequency_and_width_sliders(self):
        self.refresh()                                # the first refresh puts the sliders at the real values (50 Hz, 100)
        self.app.panel_a.s_f._press(click(12))        # extremo esquerdo -> 1 Hz
        self.app.panel_a.s_f._up(click(12))
        self.assertEqual(self.snap()["channels"]["A"]["freq_hz"], 1.0)
        self.app.panel_a.s_f._press(click(9999))      # far right -> 100 Hz (the Coyote 3.0 limit)
        self.assertEqual(self.snap()["channels"]["A"]["freq_hz"], 100.0)
        self.app.panel_b.s_w._press(click(12))
        self.assertEqual(self.snap()["channels"]["B"]["width"], 0.0)
        self.refresh()
        self.assertIn("100 Hz", self.app.panel_a.lbl_f.cget("text"))

    def test_nudge_and_zero_buttons(self):
        self.app.panel_a._nudge(10)
        self.app.panel_a._nudge(1)
        self.assertEqual(self.snap()["channels"]["A"]["target"], 11.0)
        self.app.panel_a._nudge(-50)
        self.assertEqual(self.snap()["channels"]["A"]["target"], 0.0)
        self.app.panel_b._nudge(10)
        self.app.panel_b._zero()
        self.assertEqual(self.snap()["channels"]["B"]["target"], 0.0)

    def test_keyboard_arrows_on_slider(self):
        sl = self.app.panel_a.s_int
        sl._key(1, 10)
        self.assertEqual(self.snap()["channels"]["A"]["target"], 10.0)

    # ---- emergency stop
    def test_emergency_stop_flow(self):
        self.app.panel_a._nudge(80)
        self.app.panic()
        self.refresh()
        snap = self.snap()
        self.assertTrue(snap["estopped"])
        self.assertEqual(snap["channels"]["A"]["target"], 0.0)
        self.assertFalse(self.app.panel_a.s_int.enabled)
        self.assertIn("RE-ENABLE", self.app.btn_stop.cget("text"))
        self.app.panel_a.s_int._press(click(200))           # deslizante bloqueado
        self.assertEqual(self.snap()["channels"]["A"]["target"], 0.0)
        self.app.panel_a._nudge(10)                         # the +10 button is refused with a message
        self.assertEqual(self.snap()["channels"]["A"]["target"], 0.0)
        self.assertIn("EMERGENCY", self.app.msg.cget("text").upper())
        self.app.toggle_stop()                              # RE-ENABLE
        self.refresh()
        self.assertFalse(self.snap()["estopped"])
        self.assertTrue(self.app.panel_a.s_int.enabled)
        self.assertIn("STOP", self.app.btn_stop.cget("text"))
        self.assertEqual(self.snap()["channels"]["A"]["target"], 0.0)   # comes back zeroed

    # ---- patterns
    def test_pattern_controls(self):
        pat = self.app.pat
        pat._on_name("Pulses")
        self.assertEqual(self.snap()["pattern"]["name"], "pulse")
        pat._on_speed(2.0)
        self.assertEqual(self.snap()["pattern"]["speed"], 2.0)
        self.assertEqual(self.snap()["pattern"]["name"], "pulse")        # changing the speed does not restart/switch
        pat.v_b.set(False)
        pat._on_channels()
        self.assertEqual(self.snap()["pattern"]["channels"], "A")
        pat.v_alt.set(True)
        pat._on_alt()
        self.assertTrue(self.snap()["pattern"]["alternate"])
        self.refresh()
        self.assertEqual(pat.v_name.get(), "Pulses")
        self.assertFalse(pat.v_b.get())

    def test_pattern_with_no_channel_is_refused_and_reverts(self):
        pat = self.app.pat
        pat.v_a.set(False)
        pat.v_b.set(False)
        pat._on_channels()
        self.assertEqual(self.snap()["pattern"]["channels"], "A+B")
        self.refresh()
        self.assertTrue(pat.v_a.get() and pat.v_b.get())

    def test_pattern_changed_by_ai_shows_in_menu(self):
        self.engine.control.configure(ai_enabled=True)
        self.engine.control.set_pattern("heartbeat", source="ai")
        self.refresh()
        self.assertEqual(self.app.pat.v_name.get(), "Heartbeat")

    def test_all_pattern_names_are_selectable(self):
        for label in self.app.pat.by_label:
            self.app.pat._on_name(label)
            self.refresh()

    # ---- limites
    def test_limits_apply_on_release(self):
        lim = self.app.limits
        lim.s_max._press(click(150))
        lim.s_max._up(click(150))
        cap = self.engine.settings.max_intensity
        self.assertAlmostEqual(cap, 100, delta=2)
        self.refresh()
        self.assertEqual(self.app.panel_a.s_int.limit, float(cap))
        self.app.panel_a.s_int._press(click(9999))          # does not go past the ceiling
        self.assertEqual(self.snap()["channels"]["A"]["target"], float(cap))

    def test_ramp_and_watchdog_sliders(self):
        self.app.limits.s_ramp.release(150)
        self.app.limits.s_wd.release(30)
        self.assertEqual((self.engine.settings.ramp_up_per_s, self.engine.settings.osc_timeout_s), (150, 30))
        self.refresh()
        self.assertIn("150", self.app.limits.lbl_ramp.cget("text"))
        self.assertIn("30 s", self.app.limits.lbl_wd.cget("text"))

    def test_settings_saved_without_ai_enabled(self):
        self.app.ai.v_enabled.set(True)
        self.app.ai._toggle()
        self.engine.configure(max_intensity=150)
        import json
        data = json.loads((Path(self.tmp.name) / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(data["max_intensity"], 150)
        self.assertFalse(data["ai_enabled"])

    # ---- IA
    def test_ai_toggle_asks_for_confirmation(self):
        ai = self.app.ai
        fake_mb.answer = False
        ai.v_enabled.set(True)
        ai._toggle()
        self.assertFalse(self.engine.settings.ai_enabled)
        self.assertFalse(ai.v_enabled.get())
        self.assertEqual(len(fake_mb.asked), 1)
        fake_mb.answer = True
        ai.v_enabled.set(True)
        ai._toggle()
        self.assertTrue(self.engine.settings.ai_enabled)
        self.refresh()
        self.assertIn("active", self.app.chip_ai.text.cget("text"))
        ai.v_enabled.set(False)
        ai._toggle()
        self.assertFalse(self.engine.settings.ai_enabled)
        self.assertEqual(len(fake_mb.asked), 2)   # turning it off does not ask

    def test_ai_cap_slider_and_last_action(self):
        self.app.ai.s_cap.release(30)
        self.assertEqual(self.engine.settings.ai_cap, 30)
        self.engine.control.configure(ai_enabled=True)
        self.engine.control.set_intensity("A", 90, "ai")
        self.assertEqual(self.snap()["channels"]["A"]["target"], 30.0)
        self.refresh()
        self.assertIn("intensity A = 30", self.app.ai.lbl_last.cget("text"))

    def test_mcp_command_and_token_copy(self):
        cmd = self.app.ai.mcp_command()
        self.assertTrue(cmd.startswith("claude mcp add --scope user coyote -- "))
        self.assertIn(sys.executable.replace("pythonw", "python"), cmd)
        script = str(Path(__file__).resolve().parent.parent / "coyote_mcp.py")
        self.assertIn(script, cmd)
        self.assertTrue(Path(script).exists())
        self.app.ai._copy_cmd()
        self.assertEqual(self.app._opts["clip"], cmd)
        self.app.ai._copy_token()
        self.assertEqual(self.app._opts["clip"], "token-de-teste")

    def test_register_in_claude_desktop_button(self):
        import json
        cfg = Path(self.tmp.name) / "Claude" / "claude_desktop_config.json"
        orig = gui.mcp_register.candidate_paths
        gui.mcp_register.candidate_paths = lambda env=None: [cfg]
        try:
            self.app.ai._register_desktop()
        finally:
            gui.mcp_register.candidate_paths = orig
        entry = json.loads(cfg.read_text("utf-8"))["mcpServers"]["coyote"]
        self.assertTrue(entry["args"][0].endswith("coyote_mcp.py"))
        self.assertIn("MCP registered", self.app.msg.cget("text"))
        self.assertIn("fully quit", self.app.msg.cget("text"))
        self.assertTrue(any("Claude Desktop" in l for l in self.engine.control.log_since(0)[1]))

    def test_register_in_claude_desktop_reports_bad_file(self):
        cfg = Path(self.tmp.name) / "bad.json"
        cfg.write_text("{ quebrado", "utf-8")
        orig = gui.mcp_register.candidate_paths
        gui.mcp_register.candidate_paths = lambda env=None: [cfg]
        try:
            self.app.ai._register_desktop()
        finally:
            gui.mcp_register.candidate_paths = orig
        self.assertIn("Could not", self.app.msg.cget("text"))
        self.assertEqual(self.app.msg.cget("fg").lower(), gui.RED.lower())
        self.assertEqual(cfg.read_text("utf-8"), "{ quebrado")

    def test_api_status_is_shown(self):
        self.refresh()
        self.assertIn("ready", self.app.ai.lbl_api.cget("text"))

    # ---- OSC
    def test_osc_apply_validation_and_restart(self):
        osc = self.app.osc
        old_port = self.engine.settings.osc_port
        osc.vars["osc_port"].set("abc")
        osc._apply()
        self.assertEqual(self.engine.settings.osc_port, old_port)
        self.assertIn("Invalid port", self.app.msg.cget("text"))
        osc.vars["osc_port"].set("70000")
        osc._apply()
        self.assertEqual(self.engine.settings.osc_port, old_port)

        port = free_port()
        osc.vars["osc_port"].set(str(port))
        osc.vars["osc_param_a"].set("MeuA")
        osc.vars["osc_param_freq"].set("  MinhaFreq ")
        osc._apply()
        self.assertEqual((self.engine.settings.osc_port, self.engine.settings.osc_param_a), (port, "MeuA"))
        self.assertEqual(self.engine.settings.osc_param_freq, "MinhaFreq")
        self.assertTrue(self.engine.osc_status()["listening"])
        self.refresh()
        self.assertIn(str(port), self.app.osc.lbl_status.cget("text"))

    def test_osc_port_conflict_is_shown_in_red(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("127.0.0.1", 0))
        try:
            self.app.osc.vars["osc_port"].set(str(blocker.getsockname()[1]))
            self.app.osc._apply()
            self.refresh()
            self.assertEqual(self.app.osc.lbl_status.cget("fg").lower(), gui.RED.lower())
            self.assertIn("another OSC program", self.app.osc.lbl_status.cget("text"))
            self.assertEqual(self.app.chip_osc.text.cget("text"), "OSC: error")
        finally:
            blocker.close()

    def test_osc_packets_move_sliders(self):
        from coyote_vrc import osc as oscmod
        port = free_port()
        self.app.osc.vars["osc_port"].set(str(port))
        self.app.osc._apply()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(oscmod.encode_message("/avatar/parameters/CoyoteA", 0.25), ("127.0.0.1", port))
            self.assertTrue(until(lambda: self.snap()["channels"]["A"]["target"] == 50.0))
        finally:
            sock.close()
        self.refresh()
        self.assertEqual(self.app.panel_a.s_int.value, 50.0)
        self.assertEqual(self.app.chip_osc.text.cget("text"), "OSC: receiving")
        self.assertIn("25%", self.app.osc.lbl_values.cget("text"))

    # ---- shock trigger (ShockOSC contact)
    # ---- the three tabs
    def tab_of(self, widget):
        """The index of the tab a widget lives in (found by walking up to the tab's scrollable area)."""
        node = widget
        while node is not None:
            for i, scroll in enumerate(self.app.tab_scrolls):
                if node is scroll:
                    return i
            node = getattr(node, "master", None)
        return None

    def test_the_window_has_three_tabs_with_the_right_cards(self):
        self.assertEqual([title for _, title in self.app.notebook.tabs], ["Coyote settings", "Shock contact", "Extras"])
        app = self.app
        for card in (app.bt, app.panel_a, app.panel_b, app.pat, app.limits):
            self.assertEqual(self.tab_of(card), 0, card)
        for card in (app.shock, app.contacts, app.shock_a, app.shock_b, app.chat):
            self.assertEqual(self.tab_of(card), 1, card)
        for card in (app.osc, app.ai, app.log):
            self.assertEqual(self.tab_of(card), 2, card)
        self.refresh()
        self.assertEqual(self.app._refresh_errors, 0)

    def test_the_mouse_wheel_scrolls_the_tab_that_is_showing(self):
        calls = []
        for i, scroll in enumerate(self.app.tab_scrolls):
            scroll.wheel = lambda delta, i=i: calls.append(i)
        for tab in (0, 1, 2):
            self.app.notebook.select(tab)
            self.app._on_wheel(click(120))
        self.assertEqual(calls, [0, 1, 2])

    # ---- the shock trigger card
    def test_one_click_switches_the_shock_trigger_on_and_off_without_asking(self):
        card = self.app.shock
        asked = []
        self.engine.connect = lambda *a, **k: asked.append(1)      # the real Bluetooth is not under test here
        card.v_enabled.set(True)
        card._toggle()                                             # the single click on the box
        self.assertTrue(self.engine.settings.shock_enabled)
        self.assertEqual(fake_mb.asked, [])                        # no question, no pop-up
        self.assertEqual(asked, [1])                               # enabling asked for a Bluetooth connection
        self.assertIn("connecting", self.app.msg.cget("text"))
        self.refresh()
        self.assertEqual(self.app.chip_shock.text.cget("text"), "Shock trigger: chatbox only")   # not connected yet
        self.engine.link.state = "connected"
        self.refresh()
        self.assertEqual(self.app.chip_shock.text.cget("text"), "Shock trigger: armed")
        card.v_enabled.set(False)
        card._toggle()
        self.assertFalse(self.engine.settings.shock_enabled)
        self.assertEqual(fake_mb.asked, [])
        self.refresh()
        self.assertEqual(self.app.chip_shock.text.cget("text"), "Shock trigger: off")

    def test_the_shock_trigger_still_starts_off_at_every_start(self):
        card = self.app.shock
        self.engine.connect = lambda *a, **k: None
        card.v_enabled.set(True)
        card._toggle()
        self.assertTrue(self.engine.settings.shock_enabled)
        self.engine.save()
        from coyote_vrc.settings import load_settings
        self.assertFalse(load_settings(Path(self.tmp.name) / "settings.json").shock_enabled)

    def test_shock_state_text_follows_the_trigger(self):
        card = self.app.shock
        self.engine.connect = lambda *a, **k: None      # the real Bluetooth is not under test here
        self.engine.settings.chatbox_enabled = False    # this test is about the window, not the chatbox
        for ch in "ab":
            self.engine.configure_shock(**{f"shock_{ch}_min_pct": 40, f"shock_{ch}_max_pct": 40,
                                           f"shock_{ch}_min_s": 5, f"shock_{ch}_max_s": 5})
        self.refresh()
        self.assertIn("Off", card.lbl_state.cget("text"))
        self.assertIn("no contact touched since the program started", card.lbl_touch.cget("text"))
        self.engine.set_shock_enabled(True)
        self.refresh()
        self.assertIn("not connected", card.lbl_state.cget("text"))
        self.engine._on_osc("/avatar/parameters/ShockOsc/_all", [True])       # a touch that cannot fire
        self.engine._on_osc("/avatar/parameters/ShockOsc/_all", [False])
        self.refresh()
        self.assertIn("Ignored a touch", card.lbl_ignored.cget("text"))
        self.assertIn("the Coyote is not connected", card.lbl_ignored.cget("text"))
        self.assertIn("a touch was ignored", self.app.msg.cget("text"))        # also shown at the bottom of the window
        self.assertEqual(self.app.msg.cget("fg").lower(), gui.RED.lower())
        self.assertIn("ShockOsc/_all: last touched", card.lbl_touch.cget("text"))
        self.assertEqual(self.app.chip_shock.text.cget("text"), "Shock trigger: chatbox only")
        self.engine.link.state = "connected"
        self.refresh()
        self.assertIn("waiting for a touch on ShockOsc/_all", card.lbl_state.cget("text"))
        self.assertEqual(card.lbl_state.cget("fg").lower(), gui.GREEN.lower())
        self.assertIn("none yet", card.lbl_last.cget("text"))
        self.assertEqual(self.app.chip_shock.text.cget("text"), "Shock trigger: armed")
        self.engine._on_osc("/avatar/parameters/ShockOsc/_all", [True])
        self.refresh()
        self.assertIn("SHOCK", card.lbl_state.cget("text"))
        self.assertIn("A 80", card.lbl_state.cget("text"))                      # both channels, each with its own level
        self.assertIn("B 80", card.lbl_state.cget("text"))
        self.assertEqual(card.lbl_state.cget("fg").lower(), gui.RED.lower())
        self.assertEqual(self.app.chip_shock.text.cget("text"), "Shock: ACTIVE")
        self.assertIn("A 40% (80 of 200)", card.lbl_last.cget("text"))
        self.engine.emergency_stop("gui")
        self.refresh()
        self.assertIn("emergency stop", card.lbl_state.cget("text"))

    def test_the_state_line_names_every_contact_and_warns_when_there_is_none(self):
        card = self.app.shock
        self.engine.connect = lambda *a, **k: None
        self.engine.link.state = "connected"
        self.engine.configure_shock(shock_triggers=[{"param": "ShockOsc/_all", "a": True, "b": True},
                                                    {"param": "Collar/Touch", "a": True, "b": False}])
        self.engine.set_shock_enabled(True)
        self.refresh()
        self.assertIn("ShockOsc/_all, Collar/Touch", card.lbl_state.cget("text"))
        self.engine.configure_shock(shock_triggers=[])
        self.refresh()
        self.assertIn("no contact is set", card.lbl_state.cget("text"))
        self.assertEqual(card.lbl_state.cget("fg").lower(), gui.RED.lower())

    def test_a_touch_without_a_coyote_is_shown_as_chatbox_only(self):
        from coyote_vrc import osc as oscmod
        card = self.app.shock
        self.engine.connect = lambda *a, **k: None      # the real Bluetooth is not under test here
        vrc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        vrc.bind(("127.0.0.1", 0))
        vrc.settimeout(2.0)
        try:
            self.engine.settings.chatbox_port = vrc.getsockname()[1]
            self.engine.set_shock_enabled(True)
            self.refresh()
            self.assertIn("only shows the chatbox message", card.lbl_state.cget("text"))
            self.assertEqual(self.app.chip_shock.text.cget("text"), "Shock trigger: chatbox only")
            self.assertEqual(self.app.chip_shock.dot.cget("fg").lower(), gui.GOLD.lower())   # not the red of NOT READY
            self.engine._on_osc("/avatar/parameters/ShockOsc/_all", [True])
            self.engine._on_osc("/avatar/parameters/ShockOsc/_all", [False])
            data, _ = vrc.recvfrom(4096)
            self.assertRegex(oscmod.parse_message(data)[1][0], r"^Shock A \d+% for \d+ s, B \d+% for \d+ s$")
            self.refresh()
            self.assertIn("shown in the chatbox", card.lbl_ignored.cget("text"))
            self.assertIn("no shock", card.lbl_ignored.cget("text"))
            self.assertNotIn("Ignored", card.lbl_ignored.cget("text"))
            self.assertEqual(card.lbl_ignored.cget("fg").lower(), gui.GOLD.lower())
            self.assertIn("chatbox only", self.app.msg.cget("text"))
            self.assertEqual(self.app.msg.cget("fg").lower(), gui.GOLD.lower())
            self.assertFalse(self.engine.control.shock_active())
            self.assertIn("chatbox only", card.lbl_last.cget("text"))
        finally:
            vrc.close()

    def test_shock_test_buttons(self):
        from coyote_vrc import osc as oscmod
        card, chat = self.app.shock, self.app.chat
        self.engine.connect = lambda *a, **k: None      # the real Bluetooth is not under test here
        vrc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        vrc.bind(("127.0.0.1", 0))
        vrc.settimeout(2.0)
        try:
            self.engine.settings.chatbox_port = vrc.getsockname()[1]
            chat._test_chatbox()
            data, _ = vrc.recvfrom(4096)
            # the middle of each channel's default limits: 10..30 % and 3..5 s
            self.assertEqual(oscmod.parse_message(data)[1][0], "Shock A 20% for 4 s, B 20% for 4 s (test)")
            self.assertIn("Test message sent", self.app.msg.cget("text"))
            card._test_shock("AB")
            self.assertIn("No shock: the trigger is off", self.app.msg.cget("text"))
            self.engine.set_shock_enabled(True)
            self.engine.shock._last_send = -1e9    # a real VRChat drops a message that follows within 1.6 s; skip that wait
            card._test_shock("AB")
            self.assertIn("not connected", self.app.msg.cget("text"))
            self.assertIn("only shown in the chatbox", self.app.msg.cget("text"))     # no Coyote: the message, not a shock
            self.assertFalse(self.engine.control.shock_active())
            data, _ = vrc.recvfrom(4096)
            self.assertRegex(oscmod.parse_message(data)[1][0], r"^Shock A \d+% for \d+ s, B \d+% for \d+ s$")
            self.engine.link.state = "connected"
            self.engine.shock._last_send = -1e9
            card._test_shock("A")                  # one channel only
            self.assertIn("Test shock: A ", self.app.msg.cget("text"))
            self.assertTrue(self.engine.control.shock_active("A"))
            self.assertFalse(self.engine.control.shock_active("B"))
            data, _ = vrc.recvfrom(4096)
            self.assertRegex(oscmod.parse_message(data)[1][0], r"^Shock A \d+% for \d+ s$")
            self.engine.shock._last_send = -1e9
            card._test_shock("AB")                 # A is still shocking: the test is refused, like a real touch
            self.assertIn("already running on A", self.app.msg.cget("text"))
            card._test_shock("B")                  # B is free
            self.assertTrue(self.engine.control.shock_active("B"))
        finally:
            vrc.close()

    # ---- the two channel cards
    def test_each_channel_card_applies_its_own_ranges_on_release(self):
        a, b = self.app.shock_a, self.app.shock_b
        s = self.engine.settings
        a.s_pmin._press(click(150))
        a.s_pmin._up(click(150))                        # about 50%
        self.assertAlmostEqual(s.shock_a_min_pct, 50, delta=2)
        self.assertGreaterEqual(s.shock_a_max_pct, s.shock_a_min_pct)       # the highest end was pushed up with it
        self.assertEqual(s.shock_limits("B"), (10, 30, 3, 5))               # channel B did not move
        a.s_pmax._press(click(12))
        a.s_pmax._up(click(12))                         # all the way left: 1%
        self.assertEqual((s.shock_a_min_pct, s.shock_a_max_pct), (1, 1))
        b.s_smin._user_set(12)                          # B's duration: a minimum of 12 s pushes the maximum along
        b.s_smin.release(12)
        self.assertEqual((s.shock_b_min_s, s.shock_b_max_s), (12, 12))
        b.s_smax._user_set(20)
        b.s_smax.release(20)
        self.assertEqual((s.shock_b_min_s, s.shock_b_max_s), (12, 20))
        self.assertEqual((s.shock_a_min_s, s.shock_a_max_s), (3, 5))        # A's durations did not move
        self.refresh()
        self.assertIn("Minimum random power: 1%", a.lbl_pmin.cget("text"))
        self.assertIn("Maximum random power: 1%", a.lbl_pmax.cget("text"))
        self.assertIn("Minimum random duration: 12 s", b.lbl_smin.cget("text"))
        self.assertIn("Maximum random duration: 20 s", b.lbl_smax.cget("text"))
        self.assertIn("1–1% for 3–5 s on channel A", a.lbl_sum.cget("text"))
        self.assertIn("10–30% for 12–20 s on channel B", b.lbl_sum.cget("text"))
        self.assertNotIn("s_cool", vars(a))                                 # there is no pause slider
        for slider in (a.s_smin, a.s_smax, b.s_smin, b.s_smax):             # the durations top out at 30 seconds
            slider._user_set(99)
            self.assertEqual(slider.value, 30.0)

    def test_the_channel_cards_follow_changes_made_elsewhere(self):
        self.engine.configure_shock(shock_a_min_pct=33, shock_a_max_pct=66, shock_b_min_s=7, shock_b_max_s=9)
        self.refresh()
        self.assertEqual((self.app.shock_a.s_pmin.value, self.app.shock_a.s_pmax.value), (33.0, 66.0))
        self.assertEqual((self.app.shock_b.s_smin.value, self.app.shock_b.s_smax.value), (7.0, 9.0))
        self.assertEqual((self.app.shock_b.s_pmin.value, self.app.shock_b.s_pmax.value), (10.0, 30.0))

    def test_the_power_labels_show_the_ceiling(self):
        self.engine.configure(max_intensity=137)
        self.refresh()
        text = self.app.shock_a.lbl_pmin.cget("text")
        self.assertIn("[ceiling 137]", text)
        self.assertIn("= 14 of 200", text)                  # 10% of 137

    # ---- the contact list
    def test_the_contact_list_starts_with_the_standard_contact_firing_both_channels(self):
        card = self.app.contacts
        self.assertEqual(len(card.rows), 1)
        row = card.rows[0]
        self.assertEqual((row["param"].get(), row["a"].get(), row["b"].get()), ("ShockOsc/_all", True, True))

    def test_adding_editing_and_removing_contacts(self):
        card = self.app.contacts
        s = self.engine.settings
        card._add()
        self.assertEqual(len(card.rows), 2)
        card.rows[1]["param"].set("  Collar/Touch ")
        card.rows[1]["b"].set(False)
        card._apply()
        self.assertEqual(s.shock_triggers, [{"param": "ShockOsc/_all", "a": True, "b": True},
                                            {"param": "Collar/Touch", "a": True, "b": False}])
        self.assertIn("2 contact triggers applied", self.app.msg.cget("text"))
        card._add()                                      # a row with no name is left out
        card._apply()
        self.assertEqual(len(s.shock_triggers), 2)
        card._remove(card.rows[2])
        card._remove(card.rows[1])
        self.assertEqual(s.shock_triggers, [{"param": "ShockOsc/_all", "a": True, "b": True}])
        card._remove(card.rows[0])                       # none left: allowed, and the window says nothing can fire
        self.assertEqual(s.shock_triggers, [])
        card._apply()
        self.assertIn("No contact set", self.app.msg.cget("text"))
        self.assertEqual(self.app.msg.cget("fg").lower(), gui.RED.lower())

    def test_a_contact_has_to_fire_at_least_one_channel(self):
        card = self.app.contacts
        row = card.rows[0]
        row["a"].set(False)
        card._on_check(row, "a")                         # B is still on: fine
        self.assertEqual(self.engine.settings.shock_triggers, [{"param": "ShockOsc/_all", "a": False, "b": True}])
        row["b"].set(False)
        card._on_check(row, "b")                         # nothing left: refused and put back
        self.assertTrue(row["b"].get())
        self.assertIn("at least one channel", self.app.msg.cget("text"))
        self.assertEqual(self.engine.settings.shock_triggers, [{"param": "ShockOsc/_all", "a": False, "b": True}])

    def test_a_repeated_contact_is_refused(self):
        card = self.app.contacts
        card._add()
        card.rows[1]["param"].set("shockosc/_ALL")       # the same contact in other letters
        card._apply()
        self.assertIn("listed twice", self.app.msg.cget("text"))
        self.assertEqual(len(self.engine.settings.shock_triggers), 1)

    def test_the_number_of_contacts_is_limited(self):
        from coyote_vrc.settings import MAX_SHOCK_TRIGGERS
        card = self.app.contacts
        for _ in range(MAX_SHOCK_TRIGGERS + 3):
            card._add()
        self.assertEqual(len(card.rows), MAX_SHOCK_TRIGGERS)
        self.assertEqual(card.btn_add.cget("state"), "disabled")
        self.assertIn("At most", self.app.msg.cget("text"))
        card._remove(card.rows[-1])
        self.assertEqual(card.btn_add.cget("state"), "normal")

    def test_the_rows_follow_changes_from_elsewhere_but_not_what_is_being_typed(self):
        card = self.app.contacts
        self.engine.configure_shock(shock_triggers=[{"param": "X/Y", "a": False, "b": True}])
        self.refresh()
        self.assertEqual([(r["param"].get(), r["a"].get(), r["b"].get()) for r in card.rows], [("X/Y", False, True)])
        card.rows[0]["param"].set("Typing/Now")          # typed but not applied yet
        self.refresh()
        self.assertEqual(card.rows[0]["param"].get(), "Typing/Now")

    def test_enter_and_the_check_boxes_apply_at_once(self):
        card = self.app.contacts
        card.rows[0]["param"].set("Renamed/Contact")
        card._apply(quiet=True)
        self.assertEqual(self.engine.settings.shock_triggers[0]["param"], "Renamed/Contact")
        self.assertEqual(self.app.msg.cget("text"), "")  # quiet: no message for every keystroke

    # ---- the chatbox card
    def test_chatbox_switch(self):
        card = self.app.chat
        card.v_chat.set(False)
        card._on_chat()
        self.assertFalse(self.engine.settings.chatbox_enabled)
        self.refresh()
        self.assertFalse(card.v_chat.get())
        self.engine.configure_shock(chatbox_enabled=True)       # changed from elsewhere: the box follows
        self.refresh()
        self.assertTrue(card.v_chat.get())

    def test_chatbox_fields_validation_and_apply(self):
        card = self.app.chat
        old = self.engine.settings.chatbox_port
        card.vars["chatbox_port"].set("abc")
        card._apply()
        self.assertEqual(self.engine.settings.chatbox_port, old)
        self.assertIn("Invalid chatbox port", self.app.msg.cget("text"))
        card.vars["chatbox_port"].set("70000")
        card._apply()
        self.assertEqual(self.engine.settings.chatbox_port, old)
        card.vars["chatbox_port"].set("9100")
        card.vars["chatbox_clear_s"].set("abc")
        card._apply()
        self.assertIn("Invalid number of seconds", self.app.msg.cget("text"))
        card.vars["chatbox_clear_s"].set("61")
        card._apply()
        self.assertEqual(self.engine.settings.chatbox_clear_s, 3)
        card.vars["chatbox_clear_s"].set("1")
        card.vars["chatbox_port"].set("9100")
        card._apply()
        self.assertEqual(self.engine.settings.chatbox_clear_s, 2)          # one second is too fast for VRChat: 2
        self.assertEqual(card.vars["chatbox_clear_s"].get(), "2")
        card.vars["chatbox_clear_s"].set("0")
        card.vars["chatbox_text"].set("Zap {a_percent}% {b_percent}%")
        card._apply()
        s = self.engine.settings
        self.assertEqual((s.chatbox_port, s.chatbox_text), (9100, "Zap {a_percent}% {b_percent}%"))
        self.assertEqual(s.chatbox_clear_s, 0)
        self.assertNotIn("osc_param_shock", card.vars)                      # the contacts live in their own card

    # ---- Bluetooth (simulado)
    def test_scan_connect_and_status(self):
        bt = self.app.bt
        # The simulated scan finishes instantly, which would race with the assertion below. Hand the button a
        # pending future and complete it ourselves, so "Scanning…" is observable deterministically.
        pending = concurrent.futures.Future()
        real_scan = self.app.engine.scan
        self.app.engine.scan = lambda: pending
        try:
            bt._scan()
            self.assertEqual(bt.btn_scan.cget("text"), "Scanning…")
        finally:
            self.app.engine.scan = real_scan
        pending.set_result(real_scan().result(timeout=5))
        end = time.time() + 3
        while bt.btn_scan.cget("text") != "Scan" and time.time() < end:   # plays the role of the tkinter clock
            if bt._after_jobs:
                _, fn = bt._after_jobs.pop()
                fn()
            time.sleep(0.05)
        self.assertEqual(bt.btn_scan.cget("text"), "Scan")
        self.assertTrue(bt._labels)
        self.assertTrue(bt.v_dev.get().startswith("47L121000") or "simulado" in bt.v_dev.get().lower())
        self.assertEqual(len(bt.menu["menu"].entries), len(bt._labels))

        bt._connect()
        self.assertTrue(until(lambda: self.engine.link.status()["state"] == "connected"))
        self.refresh()
        self.assertEqual(self.app.chip_ble.text.cget("text"), "Bluetooth: Connected")
        self.assertTrue(until(lambda: self.engine.link.status()["battery"] is not None))
        self.refresh()
        self.assertIn("battery", bt.lbl_battery.cget("text"))

        self.app.panel_a._nudge(40)
        self.assertTrue(until(lambda: self.engine.transport.a == 40))
        bt._disconnect()
        self.assertTrue(until(lambda: self.engine.link.status()["state"] == "disconnected"))
        self.refresh()
        self.assertEqual(self.app.chip_ble.text.cget("text"), "Bluetooth: Disconnected")
        self.assertEqual(self.engine.transport.a, 0)

    def test_connect_error_is_displayed(self):
        self.engine.transport.fail_next_connect = True
        self.app.bt._connect()
        self.assertTrue(until(lambda: self.engine.link.status()["error"] != ""))
        self.refresh()
        self.assertIn("simulated", self.app.bt.lbl_err.cget("text"))

    def test_auto_reconnect_checkbox_persists(self):
        self.app.bt.v_auto.set(False)
        self.app.bt._auto()
        self.assertFalse(self.engine.settings.auto_reconnect)

    # ---- log and shutdown
    def test_log_lines_reach_the_log_box(self):
        self.engine.control.log("linha de teste")
        self.refresh()
        self.assertTrue(any("linha de teste" in l for l in self.app.log.text.lines))
        n = len(self.app.log.text.lines)
        self.refresh()
        self.assertEqual(len(self.app.log.text.lines), n)   # without duplicating

    def test_closing_window_shuts_everything_down(self):
        self.app.panel_a._nudge(30)
        self.app.on_close()
        self.assertTrue(self.app.destroyed)
        self.assertTrue(self.engine._closed)
        self.assertTrue(self.snap()["estopped"])
        jobs = len(self.app._after_jobs)
        self.app._refresh()
        self.assertEqual(len(self.app._after_jobs), jobs)    # does not reschedule after closing
        self.engine.shutdown()                               # the second call is harmless


class SliderMath(unittest.TestCase):
    def test_slider_respects_limit_and_disabled_state(self):
        s = gui.GoldSlider(None, 0, 200, limit=80)
        got = []
        s.command = got.append
        s._press(click(9999))
        self.assertEqual(s.value, 80.0)
        self.assertEqual(got, [80.0])
        s._up(click(9999))
        s.set_enabled(False)
        s._press(click(12))
        self.assertEqual(s.value, 80.0)
        self.assertFalse(s.dragging)

    def test_set_is_ignored_while_dragging_and_clamped_otherwise(self):
        s = gui.GoldSlider(None, 0, 100)
        s._press(click(150))
        v = s.value
        s.set(5)
        self.assertEqual(s.value, v)
        s._up(click(150))
        s.set(5000)
        self.assertEqual(s.value, 100.0)


if __name__ == "__main__":
    unittest.main()
