"""Shock trigger: someone touches the avatar's ShockOSC contact -> a timed shock at a random power.

The avatar has a contact receiver whose parameter is "ShockOsc/_all" (a bool that is true while the contact is touched; the
name comes from the ShockOSC / OpenShock avatar prefabs). VRChat sends it over OSC like any other avatar parameter. When it
turns on, this module draws a random power between the two limits the user set, asks the controller to hold the chosen
channels at that level for N seconds, and says the percentage in the VRChat chatbox (and clears the chatbox again a few
seconds later).

Safety (the device delivers shocks, and here OTHER PLAYERS pull the trigger):
  * it is off every time the program starts and has to be switched on in the window;
  * one shock per touch (a contact that stays on does not repeat), then a pause before the next one can start;
  * the power is a percentage of the intensity ceiling, and the controller applies the ceiling, the rise limit and the
    latched emergency stop exactly as for every other source (see control.py: a shock is only a temporary MINIMUM level);
  * nothing happens, and nothing is announced, unless the Coyote is connected and the emergency stop is not active.

About clearing the chatbox: VRChat's documentation says nothing about removing a message through OSC. What chatbox tools do
is send an EMPTY message (with the "send now" flag), and that is what is done here. It is not guaranteed: if VRChat ignores
it, the message simply goes away when VRChat's own "chatbox display duration" setting says so.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Callable, Optional

from .control import ControlError, Controller
from .osc import CHATBOX_MAX_CHARS, OscSender
from .settings import Settings

CHATBOX_MIN_INTERVAL_S = 1.6   # VRChat drops chatbox messages that arrive faster than about this (any message, also a clear)


def render_text(template: str, percent: int, seconds: int) -> str:
    """Fills {percent} and {seconds} in the chatbox template (plain replacement: a stray brace cannot break it)."""
    text = str(template).replace("{percent}", str(int(percent))).replace("{seconds}", str(int(seconds)))
    return " ".join(text.split())[:CHATBOX_MAX_CHARS]


def timer_schedule(delay: float, fn: Callable[[], None]):
    """Runs fn after `delay` seconds on a daemon thread. Returns an object with cancel()."""
    timer = threading.Timer(delay, fn)
    timer.daemon = True
    timer.start()
    return timer


class ShockTrigger:
    def __init__(self, settings: Settings, control: Controller, is_connected: Callable[[], bool], sender: OscSender,
                 rng: Optional[random.Random] = None, clock=time.monotonic, schedule=timer_schedule):
        self.settings = settings
        self.control = control
        self._is_connected = is_connected
        self._sender = sender
        self._rng = rng or random.Random()
        self._clock = clock
        self._schedule = schedule
        self._lock = threading.Lock()
        self._prev_on = False
        self._cooldown_until = 0.0
        self._last_send = -1e9           # when the last chatbox message of ANY kind went out
        self._chat_gen = 0               # bumped for every message we put on screen: a stale clear must do nothing
        self._chat_visible = False       # our message is (as far as we know) still on screen
        self._clear_handle = None
        self._last_touch: Optional[float] = None      # when the contact last turned on (whatever happened next)
        self._ignored: Optional[tuple] = None         # (time, reason) of the last touch that did not fire
        self._ignored_n = 0
        self.last = ""   # description of the last shock (shown in the window)

    # ------------------------------------------------------------------ from VRChat
    def on_param(self, on: bool) -> Optional[dict]:
        """Called with every value of the contact parameter. Only a change from off to on counts as a touch, so a contact
        that stays on (or that is already on when the trigger is switched on) never fires by itself."""
        with self._lock:
            rising = bool(on) and not self._prev_on
            self._prev_on = bool(on)
            if rising:
                self._last_touch = self._clock()
        return self.fire("osc") if rising else None

    # ------------------------------------------------------------------ one touch
    def fire(self, source: str = "osc") -> dict:
        """Draws a power and starts the shock, or says why not. Returns {"fired": True, ...} or {"fired": False, "reason"}."""
        s, ctl = self.settings, self.control

        def refuse(reason: str) -> dict:
            ctl.log(f"Shock trigger: touch ignored — {reason}")
            with self._lock:
                self._ignored = (self._clock(), reason)
                self._ignored_n += 1
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
        with self._lock:
            if self._clock() - self._last_send < CHATBOX_MIN_INTERVAL_S:
                too_fast = True
            else:
                too_fast = False
        if too_fast:
            self.control.log("Chatbox: message skipped (VRChat drops messages that come too fast)")
            return
        self.show(text)

    def show(self, text: str) -> bool:
        """Puts a message in the chatbox and arranges for it to be removed after `chatbox_clear_s` seconds."""
        if not self.send_chatbox(text):
            return False
        delay = self.settings.chatbox_clear_s
        with self._lock:
            self._chat_gen += 1                  # a clear that is still waiting for an older message becomes stale
            gen = self._chat_gen
            self._cancel_clear_locked()
            self._chat_visible = True
            if delay > 0:
                self._clear_handle = self._schedule(delay, lambda: self._clear(gen))
        return True

    def send_chatbox(self, text: str) -> bool:
        s = self.settings
        try:
            self._sender.send_chatbox(s.chatbox_host, s.chatbox_port, text)
        except OSError as exc:
            self.control.log(f"Chatbox: could not send ({exc.strerror or exc})")
            return False
        with self._lock:
            self._last_send = self._clock()
        self.control.log(f"Chatbox: {text!r} sent to {s.chatbox_host}:{s.chatbox_port}")
        return True

    def _cancel_clear_locked(self) -> None:
        handle, self._clear_handle = self._clear_handle, None
        if handle is not None:
            try:
                handle.cancel()
            except Exception:
                pass

    def _clear(self, gen: int) -> None:
        """The timer: removes the message, unless a newer one is on screen by now or it was removed already."""
        with self._lock:
            if gen != self._chat_gen or not self._chat_visible:
                return
            self._chat_visible = False
            self._clear_handle = None
        self._send_empty()

    def _send_empty(self) -> None:
        s = self.settings
        try:
            self._sender.send_chatbox(s.chatbox_host, s.chatbox_port, "")
        except OSError as exc:
            self.control.log(f"Chatbox: could not clear ({exc.strerror or exc})")
            return
        with self._lock:
            self._last_send = self._clock()
        self.control.log("Chatbox: cleared")

    def clear_now(self) -> None:
        """Removes our message at once (emergency stop, trigger switched off, program closing), if clearing is switched on
        and the message is still on screen. A pending timer is cancelled so it cannot clear a later message early."""
        with self._lock:
            visible = self._chat_visible and self.settings.chatbox_clear_s > 0
            self._cancel_clear_locked()
            self._chat_gen += 1
            self._chat_visible = False
        if visible:
            self._send_empty()

    # ------------------------------------------------------------------ for the window
    def status(self) -> dict:
        snap = self.control.snapshot()["shock"]
        now = self._clock()
        with self._lock:
            cooldown = max(0.0, self._cooldown_until - now)
            touch_age = None if self._last_touch is None else round(now - self._last_touch, 1)
            ignored, ignored_n = self._ignored, self._ignored_n
        return {
            "touch_age_s": touch_age,                      # None = the contact has not been touched since the program started
            "ignored_reason": ignored[1] if ignored else "",
            "ignored_age_s": None if ignored is None else round(now - ignored[0], 1),
            "ignored_count": ignored_n,
            "enabled": self.settings.shock_enabled,
            "active": snap["active"],
            "remaining_s": snap["remaining_s"],
            "level": snap["level"],
            "cooldown_s": 0.0 if snap["active"] else round(cooldown, 1),
            "connected": bool(self._is_connected()),
            "estopped": self.control.estopped,
            "last": self.last,
        }
