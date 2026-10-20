"""Engine: wires Controller + Bluetooth + OSC + local API together. The GUI only talks to this class."""
from __future__ import annotations

from typing import Optional

from .api import ApiServer
from .ble import AsyncThread, BleakTransport, CoyoteLink
from .control import ControlError, Controller
from .osc import OscListener, OscSender
from .settings import Settings, load_settings, save_settings
from .shock import ShockTrigger, render_text

OSC_PREFIX = "/avatar/parameters/"


def _to_float(arg) -> Optional[float]:
    if isinstance(arg, bool):
        return 1.0 if arg else 0.0
    if isinstance(arg, (int, float)):
        return float(arg)
    return None


def _osc_hz(arg) -> Optional[float]:
    """Frequency from the avatar: INTEGER only, in Hz (1..100). Zero and floats are ignored on purpose:
    a parameter that is not initialized yet arrives as 0 and must not drop the frequency to 1 Hz."""
    if isinstance(arg, bool) or not isinstance(arg, int) or arg <= 0:
        return None
    return float(arg)


class Engine:
    def __init__(self, settings: Optional[Settings] = None, settings_path=None, transport=None):
        self.settings_path = settings_path
        self.settings = settings or load_settings(settings_path)
        self.control = Controller(self.settings)
        self.loop = AsyncThread()
        self.loop.start_and_wait()
        self.transport = transport or BleakTransport()
        self.link = CoyoteLink(self.control, self.settings, self.transport)
        self.vrc_out = OscSender()   # to VRChat (chatbox)
        self.shock = ShockTrigger(self.settings, self.control, lambda: self.link.state == "connected", self.vrc_out)
        self.osc: Optional[OscListener] = None
        self.osc_error = ""
        self.api: Optional[ApiServer] = None
        self.api_error = ""
        self._closed = False

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.start_osc()
        self.start_api()

    def shutdown(self) -> None:
        if self._closed:  # may be called by the GUI and again by main.py
            return
        self._closed = True
        self.control.emergency_stop("program exit")
        try:
            self.loop.submit(self.link.disconnect()).result(timeout=6)
        except Exception:
            pass
        self.stop_osc()
        self.stop_api()
        self.shock.clear_now()     # do not leave our chatbox message on screen after the program is gone
        self.vrc_out.close()
        self.save()
        self.loop.stop()

    def save(self) -> None:
        save_settings(self.settings, self.settings_path)

    # ------------------------------------------------------------------ Bluetooth
    def connect(self, address: Optional[str] = None) -> None:
        self.loop.submit(self.link.connect(address or None))

    def disconnect(self) -> None:
        self.loop.submit(self.link.disconnect())

    def scan(self):
        """Returns a Future (concurrent.futures) with the list of devices."""
        return self.loop.submit(self.link.scan())

    # ------------------------------------------------------------------ control
    def emergency_stop(self, source: str = "gui") -> None:
        self.control.emergency_stop(source)
        self.shock.clear_now()     # a "Shock 37%" message must not outlive a shock that was just cancelled
        self.link.poke()

    def resume(self) -> None:
        self.control.resume("gui")

    def configure(self, **kw) -> set:
        changed = self.control.configure(**kw)
        if "max_intensity" in changed:
            self.link.bf_dirty = True  # rewrite the soft limit (BF) on the device
            self.link.poke()
        if changed:
            self.save()
        return changed

    # ------------------------------------------------------------------ shock trigger (ShockOSC contact)
    _SHOCK_KEYS = ("osc_param_shock", "shock_min_pct", "shock_max_pct", "shock_seconds",
                   "shock_channels", "chatbox_enabled", "chatbox_host", "chatbox_port", "chatbox_text",
                   "chatbox_clear_s")

    def set_shock_enabled(self, on: bool) -> None:
        on = bool(on)
        if on == self.settings.shock_enabled:
            return
        self.settings.shock_enabled = on
        self.control.log("Shock trigger " + ("ENABLED" if on else "disabled"))
        if on:
            # Armed means ready: a shock needs the Coyote, so connect it now unless it is connected or on its way.
            if self.link.state in ("disconnected",):
                self.control.log("Shock trigger: the Coyote is not connected, connecting now…")
                self.connect()
        else:   # also cancel a shock that is running right now, and take our message off the screen
            self.control.stop_shock("trigger switched off")
            self.shock.clear_now()
            self.link.poke()

    def configure_shock(self, **kw) -> set:
        """Changes the shock-trigger settings (and the chatbox ones). Returns the keys that actually changed."""
        unknown = set(kw) - set(self._SHOCK_KEYS)
        if unknown:
            raise ControlError("unknown setting: " + ", ".join(sorted(unknown)))
        s = self.settings
        before = {k: getattr(s, k) for k in self._SHOCK_KEYS}
        for key, value in kw.items():
            setattr(s, key, value)
        # moving only one end of the range past the other pushes the other end along (instead of swapping them)
        if "shock_min_pct" in kw and "shock_max_pct" not in kw and s.shock_min_pct > s.shock_max_pct:
            s.shock_max_pct = s.shock_min_pct
        if "shock_max_pct" in kw and "shock_min_pct" not in kw and s.shock_max_pct < s.shock_min_pct:
            s.shock_min_pct = s.shock_max_pct
        s.validate()
        changed = {k for k in self._SHOCK_KEYS if getattr(s, k) != before[k]}
        if changed:
            self.save()
        return changed

    def shock_status(self) -> dict:
        return self.shock.status()

    def test_shock(self) -> dict:
        """The same as a touch on the contact (it obeys every rule: switched on, no shock running, no emergency stop; without
        a connected Coyote it only shows the chatbox message)."""
        return self.shock.fire("gui")

    def test_chatbox(self) -> bool:
        s = self.settings
        text = render_text(s.chatbox_text, (s.shock_min_pct + s.shock_max_pct) // 2, s.shock_seconds)
        return self.shock.show((text + " (test)")[:144])    # shown like a real one, so it is cleared like a real one

    # ------------------------------------------------------------------ OSC
    def _on_osc(self, address: str, args: list) -> None:
        self.control.note_osc_packet()
        if not address.startswith(OSC_PREFIX) or not args:
            return
        name = address[len(OSC_PREFIX):]
        s = self.settings
        value = _to_float(args[0])
        if value is None:
            return
        try:
            if s.osc_param_a and name == s.osc_param_a:
                self.control.record_osc_value(0, value)
                self.control.set_fraction(0, value, "osc")
            elif s.osc_param_b and name == s.osc_param_b:
                self.control.record_osc_value(1, value)
                self.control.set_fraction(1, value, "osc")
            elif s.osc_param_stop and name == s.osc_param_stop and value >= 0.5:
                self.emergency_stop("osc")
            elif s.osc_param_freq and name == s.osc_param_freq:
                hz = _osc_hz(args[0])
                if hz is not None:
                    self.control.set_frequency("AB", hz, "osc")
            elif s.osc_param_shock and name.lower() == s.osc_param_shock.lower():
                self.shock.on_param(value >= 0.5)   # the ShockOSC contact (case-insensitive: _all / _All)
        except ControlError:
            pass  # emergency stop active etc.: ignore silently

    def start_osc(self) -> None:
        self.stop_osc()
        self.osc_error = ""
        s = self.settings
        if not s.osc_enabled:
            return
        listener = OscListener(s.osc_host, s.osc_port, self._on_osc)
        try:
            listener.start()
        except OSError as exc:
            self.osc_error = (
                f"could not listen on {s.osc_host}:{s.osc_port} ({exc.strerror or exc}) — "
                "another OSC program (e.g. another Coyote controller) may be using this port"
            )
            self.control.log("OSC: " + self.osc_error)
            return
        self.osc = listener
        self.control.log(f"OSC listening on {s.osc_host}:{s.osc_port}")

    def stop_osc(self) -> None:
        if self.osc is not None:
            self.osc.stop()
            self.osc = None

    def osc_status(self) -> dict:
        o = self.osc
        return {
            "enabled": self.settings.osc_enabled,
            "listening": bool(o and o.listening),
            "error": self.osc_error,
            "packets": o.packets if o else 0,
            "host": self.settings.osc_host,
            "port": self.settings.osc_port,
        }

    # ------------------------------------------------------------------ local API
    def start_api(self) -> None:
        self.stop_api()
        self.api_error = ""
        server = ApiServer(self, "127.0.0.1", self.settings.api_port, self.settings.api_token)
        try:
            server.start()
        except OSError as exc:
            self.api_error = f"port {self.settings.api_port} unavailable ({exc.strerror or exc})"
            self.control.log("AI API: " + self.api_error)
            return
        self.api = server
        self.control.log(f"Local AI API at http://127.0.0.1:{server.port} (disabled until you allow it in the GUI)")

    def stop_api(self) -> None:
        if self.api is not None:
            self.api.stop()
            self.api = None
