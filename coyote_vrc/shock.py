"""Shock trigger: someone touches a contact on the avatar -> timed shocks, each channel with its own random power and duration.

The avatar has contact receivers whose parameters ("ShockOsc/_all" by default; more can be added) are bools that are true
while the contact is touched; the default name comes from the ShockOSC / OpenShock avatar prefabs. VRChat sends them over OSC
like any other avatar parameter. Every trigger fires the channels it is set for (the default one fires both). When one turns
on, this module draws, for each of its channels, a random power and a random duration between the limits the user set for
that channel, asks the controller to hold the channel at that level for that long, and says the result in the VRChat chatbox
(and clears the chatbox again a few seconds later).

Safety (the device delivers shocks, and here OTHER PLAYERS pull the trigger):
  * it is off every time the program starts and has to be switched on in the window;
  * one shock per touch: a contact that stays on does not repeat, and a touch while a shock is running on one of its channels
    is ignored;
  * the power is a percentage of the intensity ceiling, and the controller applies the ceiling, the rise limit and the
    latched emergency stop exactly as for every other source (see control.py: a shock is only a temporary MINIMUM level);
  * a shock is only ever delivered with the Coyote connected and the emergency stop not active. With the Coyote NOT
    connected a touch still puts the message in the chatbox (the user asked for that), but nothing is delivered and the
    window says so; with the emergency stop active nothing happens and nothing is announced.

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
CHANNELS = "AB"


def describe(plan: dict) -> str:
    """{"A": (37, 5), "B": (20, 3)} -> "A 37% for 5 s, B 20% for 3 s" (percent, seconds per channel)."""
    return ", ".join(f"{ch} {int(plan[ch][0])}% for {int(plan[ch][1])} s" for ch in CHANNELS if ch in plan)


def render_text(template: str, plan: dict) -> str:
    """Fills the chatbox template from {"A": (percent, seconds), "B": (...)} (only the channels that fire). Plain replacement:
    a stray brace cannot break it.

      {shock}                         A 37% for 5 s, B 20% for 3 s
      {percent} / {seconds}           the highest power / the longest duration of the channels that fire
      {a_percent} {a_seconds}         one channel's numbers (0 when that channel does not fire)
      {b_percent} {b_seconds}
    """
    values = {"{shock}": describe(plan)}
    if plan:
        values["{percent}"] = str(max(int(p) for p, _ in plan.values()))
        values["{seconds}"] = str(max(int(s) for _, s in plan.values()))
    else:
        values["{percent}"] = values["{seconds}"] = "0"
    for ch in CHANNELS:
        percent, seconds = plan.get(ch, (0, 0))
        values["{%s_percent}" % ch.lower()] = str(int(percent))
        values["{%s_seconds}" % ch.lower()] = str(int(seconds))
    text = str(template)
    for token, value in values.items():
        text = text.replace(token, value)
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
        self._prev_on: dict = {}         # contact name (lower case) -> was it on at the last value
        self._last_send = -1e9           # when the last chatbox message of ANY kind went out
        self._chat_gen = 0               # bumped for every message we put on screen: a stale clear must do nothing
        self._chat_visible = False       # our message is (as far as we know) still on screen
        self._clear_handle = None
        self._last_touch: Optional[float] = None      # when a contact last turned on (whatever happened next)
        self._last_touch_param = ""
        self._ignored: Optional[tuple] = None         # (time, reason) of the last touch that did not fire
        self._ignored_n = 0
        self._announced: Optional[tuple] = None       # (time, "A 37% for 5 s, ...") of the last touch only announced
        self._announced_n = 0
        self._virtual_until = {"A": 0.0, "B": 0.0}    # an announced-only "shock" counts as running on a channel until then
        self.last = ""   # description of the last shock (shown in the window)

    # ------------------------------------------------------------------ from VRChat
    def _trigger_for(self, name: str) -> Optional[dict]:
        low = str(name).lower()
        for trigger in self.settings.shock_triggers:
            if trigger["param"].lower() == low:
                return trigger
        return None

    def handles(self, name: str) -> bool:
        """True when `name` (an avatar parameter) is one of the contacts."""
        return self._trigger_for(name) is not None

    def on_param(self, name: str, on: bool) -> Optional[dict]:
        """Called with every value of a contact parameter. Only a change from off to on counts as a touch, so a contact that
        stays on (or that is already on when the trigger is switched on) never fires by itself."""
        trigger = self._trigger_for(name)
        if trigger is None:
            return None
        key = trigger["param"].lower()
        with self._lock:
            rising = bool(on) and not self._prev_on.get(key, False)
            self._prev_on[key] = bool(on)
            if rising:
                self._last_touch = self._clock()
                self._last_touch_param = trigger["param"]
        if not rising:
            return None
        return self.fire("osc", ("A" if trigger["a"] else "") + ("B" if trigger["b"] else ""))

    # ------------------------------------------------------------------ one touch
    def _draw(self, chans: str) -> dict:
        """{"A": (percent, seconds), ...}: a random power and a random duration inside each channel's limits."""
        plan = {}
        for ch in chans:
            lo, hi, slo, shi = self.settings.shock_limits(ch)
            plan[ch] = (self._rng.randint(lo, hi), self._rng.randint(slo, shi))
        return plan

    def fire(self, source: str = "osc", channels: str = "AB") -> dict:
        """Draws the powers and durations and starts the shocks on `channels`, or says why not.
        Returns {"fired": True, ...} or {"fired": False, "reason": ...}."""
        s, ctl = self.settings, self.control
        chans = "".join(c for c in CHANNELS if c in str(channels).upper()) or CHANNELS

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
            return self._announce_only(chans, refuse)
        busy = [c for c in chans if ctl.shock_active(c)]
        if busy:
            return refuse("a shock is already running on " + "+".join(busy))
        cap = ctl.cap("gui")
        if cap <= 0:
            return refuse("the intensity ceiling is 0")

        plan = self._draw(chans)
        levels = {c: (max(1, int(round(plan[c][0] * cap / 100.0))), plan[c][1]) for c in chans}
        try:
            res = ctl.start_shocks(levels, source)
        except ControlError as exc:
            return refuse(str(exc))
        real = {c: (plan[c][0], int(res[c]["seconds"])) for c in chans}
        self.last = ", ".join(f"{c} {plan[c][0]}% ({res[c]['applied']:.0f} of {cap}) for {res[c]['seconds']:.0f} s"
                              for c in chans)
        ctl.log("Shock trigger: drew " + describe(real))
        self._announce(real)
        return {"fired": True, "channels": chans, "text": describe(real),
                "shocks": {c: {"percent": plan[c][0], "level": res[c]["applied"], "seconds": res[c]["seconds"]}
                           for c in chans}}

    # ------------------------------------------------------------------ chatbox
    def _announce_only(self, chans: str, refuse) -> dict:
        """The Coyote is not connected, so nothing can be delivered. The message is shown in the chatbox anyway, as if the
        shock had happened, and each channel counts as shocking for its drawn duration (so a second touch on the same
        channels is not announced on top of it)."""
        now = self._clock()
        with self._lock:
            busy = any(now < self._virtual_until[c] for c in chans)
        if busy:
            return refuse("the Coyote is not connected, and the message of the previous touch is still running")
        plan = self._draw(chans)
        if not self._announce(plan):
            return refuse("the Coyote is not connected, and no chatbox message was sent "
                          "(the message is off or empty, or came too soon after another)")
        text = describe(plan)
        with self._lock:
            for c in chans:
                self._virtual_until[c] = now + plan[c][1]
            self._announced = (now, text)
            self._announced_n += 1
        self.last = f"{text}: shown in the chatbox only, the Coyote is not connected"
        self.control.log(f"Shock trigger: the Coyote is not connected, so {text} was only announced in the chatbox; "
                         "no shock was delivered")
        return {"fired": False, "announced": True, "channels": chans, "text": text,
                "shocks": {c: {"percent": plan[c][0], "seconds": float(plan[c][1])} for c in chans},
                "reason": "the Coyote is not connected: the message was shown in the chatbox, no shock was delivered"}

    def _announce(self, plan: dict) -> bool:
        """Puts the message in the chatbox. True when a message really went out."""
        s = self.settings
        if not s.chatbox_enabled:
            return False
        text = render_text(s.chatbox_text, plan)
        if not text:
            return False
        with self._lock:
            if self._clock() - self._last_send < CHATBOX_MIN_INTERVAL_S:
                too_fast = True
            else:
                too_fast = False
        if too_fast:
            self.control.log("Chatbox: message skipped (VRChat drops messages that come too fast)")
            return False
        return self.show(text)

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
            self._virtual_until = {"A": 0.0, "B": 0.0}
        if visible:
            self._send_empty()

    # ------------------------------------------------------------------ for the window
    def status(self) -> dict:
        snap = self.control.snapshot()["shock"]
        now = self._clock()
        with self._lock:
            touch_age = None if self._last_touch is None else round(now - self._last_touch, 1)
            touch_param = self._last_touch_param
            ignored, ignored_n = self._ignored, self._ignored_n
            announced, announced_n = self._announced, self._announced_n
        return {
            "touch_age_s": touch_age,                      # None = no contact has been touched since the program started
            "touch_param": touch_param,                    # which contact it was
            "ignored_reason": ignored[1] if ignored else "",
            "ignored_age_s": None if ignored is None else round(now - ignored[0], 1),
            "ignored_count": ignored_n,
            "announced_text": announced[1] if announced else "",     # a touch shown in the chatbox without a shock
            "announced_age_s": None if announced is None else round(now - announced[0], 1),
            "announced_count": announced_n,
            "enabled": self.settings.shock_enabled,
            "active": snap["active"],
            "remaining_s": snap["remaining_s"],
            "remaining": snap["remaining"],
            "level": snap["level"],
            "connected": bool(self._is_connected()),
            "estopped": self.control.estopped,
            "last": self.last,
        }
