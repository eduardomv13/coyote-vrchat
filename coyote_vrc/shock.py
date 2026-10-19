"""Shock trigger: someone touches the avatar's ShockOSC contact -> a timed shock at a random power.

The avatar has a contact receiver whose parameter is "ShockOsc/_all" (a bool that is true while the contact is touched; the
name comes from the ShockOSC / OpenShock avatar prefabs). VRChat sends it over OSC like any other avatar parameter. When it
turns on, this module draws a random power between the two limits the user set, asks the controller to hold the chosen
channels at that level for N seconds, and says the percentage in the VRChat chatbox.

Safety (the device delivers shocks, and here OTHER PLAYERS pull the trigger):
  * it is off every time the program starts and has to be switched on in the window;
  * one shock per touch (a contact that stays on does not repeat), then a pause before the next one can start;
  * the power is a percentage of the intensity ceiling, and the controller applies the ceiling, the rise limit and the
    latched emergency stop exactly as for every other source (see control.py: a shock is only a temporary MINIMUM level);
  * nothing happens, and nothing is announced, unless the Coyote is connected and the emergency stop is not active.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Callable, Optional

from .control import ControlError, Controller
from .osc import CHATBOX_MAX_CHARS, OscSender
from .settings import Settings

CHATBOX_MIN_INTERVAL_S = 1.6   # VRChat drops chatbox messages that arrive faster than about this


def render_text(template: str, percent: int, seconds: int) -> str:
    """Fills {percent} and {seconds} in the chatbox template (plain replacement: a stray brace cannot break it)."""
    text = str(template).replace("{percent}", str(int(percent))).replace("{seconds}", str(int(seconds)))
    return " ".join(text.split())[:CHATBOX_MAX_CHARS]


class ShockTrigger:
    def __init__(self, settings: Settings, control: Controller, is_connected: Callable[[], bool], sender: OscSender,
                 rng: Optional[random.Random] = None, clock=time.monotonic):
        self.settings = settings
        self.control = control
        self._is_connected = is_connected
        self._sender = sender
        self._rng = rng or random.Random()
        self._clock = clock
        self._lock = threading.Lock()
        self._prev_on = False
        self._cooldown_until = 0.0
        self._last_chatbox = -1e9
        self.last = ""   # description of the last shock (shown in the window)

    # ------------------------------------------------------------------ from VRChat
    def on_param(self, on: bool) -> Optional[dict]:
        """Called with every value of the contact parameter. Only a change from off to on counts as a touch, so a contact
        that stays on (or that is already on when the trigger is switched on) never fires by itself."""
        with self._lock:
            rising = bool(on) and not self._prev_on
            self._prev_on = bool(on)
        return self.fire("osc") if rising else None

    # ------------------------------------------------------------------ one touch
    def fire(self, source: str = "osc") -> dict:
        """Draws a power and starts the shock, or says why not. Returns {"fired": True, ...} or {"fired": False, "reason"}."""
        s, ctl = self.settings, self.control

        def refuse(reason: str) -> dict:
            ctl.log(f"Shock trigger: touch ignored — {reason}")
            return {"fired": False, "reason": reason}

        if not s.shock_enabled:
            return refuse("the trigger is off")
        if ctl.estopped:
            return refuse("the emergency stop is active")
        if not self._is_connected():
            return refuse("the Coyote is not connected")
        now = self._clock()
        if ctl.shock_active():
            return refuse("a shock is already running")
        with self._lock:
            wait = self._cooldown_until - now
        if wait > 0:
            return refuse(f"pausing between shocks ({wait:.0f} s left)")
        cap = ctl.cap("gui")
        if cap <= 0:
            return refuse("the intensity ceiling is 0")

        percent = self._rng.randint(s.shock_min_pct, s.shock_max_pct)
        level = max(1, int(round(percent * cap / 100.0)))
        try:
            res = ctl.start_shock(s.shock_channels, level, s.shock_seconds, source)
        except ControlError as exc:
            return refuse(str(exc))
        with self._lock:
            self._cooldown_until = now + res["seconds"] + s.shock_cooldown_s
        self.last = f"{percent}% ({res['applied']:.0f} of {cap}) on {res['channels']} for {res['seconds']:.0f} s"
        ctl.log(f"Shock trigger: drew {percent}% of the ceiling")
        self._announce(percent, int(res["seconds"]))
        return {"fired": True, "percent": percent, "level": res["applied"], "seconds": res["seconds"],
                "channels": res["channels"]}

    # ------------------------------------------------------------------ chatbox
    def _announce(self, percent: int, seconds: int) -> None:
        s = self.settings
        if not s.chatbox_enabled:
            return
        text = render_text(s.chatbox_text, percent, seconds)
        if not text:
            return
        now = self._clock()
        with self._lock:
            if now - self._last_chatbox < CHATBOX_MIN_INTERVAL_S:
                self.control.log("Chatbox: message skipped (VRChat drops messages that come too fast)")
                return
            self._last_chatbox = now
        self.send_chatbox(text)

    def send_chatbox(self, text: str) -> bool:
        s = self.settings
        try:
            self._sender.send_chatbox(s.chatbox_host, s.chatbox_port, text)
        except OSError as exc:
            self.control.log(f"Chatbox: could not send ({exc.strerror or exc})")
            return False
        self.control.log(f"Chatbox: {text!r} sent to {s.chatbox_host}:{s.chatbox_port}")
        return True

    # ------------------------------------------------------------------ for the window
    def status(self) -> dict:
        snap = self.control.snapshot()["shock"]
        now = self._clock()
        with self._lock:
            cooldown = max(0.0, self._cooldown_until - now)
        return {
            "enabled": self.settings.shock_enabled,
            "active": snap["active"],
            "remaining_s": snap["remaining_s"],
            "level": snap["level"],
            "cooldown_s": 0.0 if snap["active"] else round(cooldown, 1),
            "connected": bool(self._is_connected()),
            "estopped": self.control.estopped,
            "last": self.last,
        }
