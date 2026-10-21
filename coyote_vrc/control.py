"""Shared control state (GUI, OSC and AI write here; the BLE loop reads from here every 100 ms).

Safety rules implemented in this module:
  * A single ceiling `max_intensity` for every source; the AI has its own ceiling (`ai_cap`) and only
    acts if `ai_enabled` is switched on in the GUI (it always starts off).
  * Rise limit (`ramp_up_per_s`): intensity rises at most X units/s; lowering is immediate.
  * LATCHED emergency stop: zeroes everything and ignores new commands until re-enabled from the GUI.
  * On (re)connect, intensities start at zero.
  * Optional watchdog: zeroes OSC-driven channels if VRChat goes silent.
  * A timed shock (the contact trigger) is only a temporary MINIMUM level, with its own level and its own end time for
    each channel: it never lowers what the window/VRChat/AI ask for, lasts at most 30 s, follows the ceiling and the rise
    limit, and the emergency stop cancels it.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from . import patterns, protocol
from .settings import Settings


SHOCK_MAX_SECONDS = 30


class ControlError(Exception):
    """Invalid request (HTTP 400)."""


class ControlForbidden(ControlError):
    """Request refused by a safety rule (HTTP 403)."""


def channels_from(ch) -> tuple[int, ...]:
    if isinstance(ch, bool):
        raise ControlError(f"invalid channel: {ch!r}")
    if isinstance(ch, int) and ch in (0, 1):
        return (ch,)
    if isinstance(ch, (list, tuple)) and ch and all(isinstance(x, int) and not isinstance(x, bool) and x in (0, 1) for x in ch):
        return tuple(sorted(set(ch)))
    if isinstance(ch, str):
        s = ch.strip().upper().replace(" ", "")
        if s in ("A", "0"):
            return (0,)
        if s in ("B", "1"):
            return (1,)
        if s in ("AB", "BA", "A+B", "BOTH"):
            return (0, 1)
    raise ControlError(f"invalid channel: {ch!r} (use 'A', 'B' or 'AB')")


def _number(value, what: str = "value") -> float:
    if isinstance(value, bool):
        raise ControlError(f"invalid {what}: {value!r}")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ControlError(f"invalid {what}: {value!r}") from None
    if not math.isfinite(v):
        raise ControlError(f"invalid {what}: {value!r}")
    return v


def _names(chans) -> str:
    return "+".join("AB"[i] for i in chans)


@dataclass
class ChannelState:
    target: float = 0.0      # requested intensity (0..ceiling)
    output: float = 0.0      # after the rise limiter
    freq_hz: float = 50.0
    width: float = 100.0     # pulse width 0..100 ("wave intensity")
    actual: Optional[int] = None  # last intensity reported by the device (B1)


@dataclass
class Frame:
    intensity: tuple[int, int]
    freq: tuple[list[int], list[int]]
    width: tuple[list[int], list[int]]


class Controller:
    _RANGES = {
        "max_intensity": (0, 200),
        "ramp_up_per_s": (0, 400),
        "ai_cap": (0, 200),
        "osc_timeout_s": (0, 3600),
    }

    def __init__(self, settings: Settings, clock=time.monotonic):
        self.settings = settings
        self._clock = clock
        self._lock = threading.RLock()
        self.ch = [
            ChannelState(freq_hz=float(settings.default_freq_hz), width=float(settings.default_width))
            for _ in range(2)
        ]
        self.last_source = ["", ""]
        self.estopped = False
        self.pattern = patterns.DEFAULT_PATTERN
        self.pattern_speed = 1.0
        self.pattern_channels: tuple[int, ...] = (0, 1)
        self.pattern_alternate = False
        self._pclock = 0.0
        self._seed = [1, 2]
        self.last_osc: Optional[float] = None
        self.osc_values: list[Optional[float]] = [None, None]
        self.ai_last_action = ""
        # Shock overlay: until `shock_until[i]`, channel i never goes below shock_level[i] (see start_shocks)
        self.shock_level: list[float] = [0.0, 0.0]
        self.shock_until: list[float] = [0.0, 0.0]
        self._log: deque = deque(maxlen=400)
        self._log_n = 0

    # ------------------------------------------------------------------ log
    def log(self, msg: str) -> None:
        with self._lock:
            self._log_n += 1
            self._log.append((self._log_n, time.strftime("%H:%M:%S") + "  " + msg))

    def log_since(self, after: int):
        with self._lock:
            items = [(i, t) for i, t in self._log if i > after]
            return (items[-1][0] if items else after), [t for _, t in items]

    # ------------------------------------------------------------------ limits
    def cap(self, source: str) -> int:
        c = self.settings.max_intensity
        return min(c, self.settings.ai_cap) if source == "ai" else c

    def _guard_ai(self, source: str) -> None:
        if source == "ai" and not self.settings.ai_enabled:
            raise ControlForbidden("AI control is disabled — the user has to enable it in the GUI")

    def apply_limits(self) -> None:
        with self._lock:
            for i, c in enumerate(self.ch):
                limit = self.cap("ai" if self.last_source[i] == "ai" else "gui")
                c.target = min(c.target, limit)
                c.output = min(c.output, limit)

    # ------------------------------------------------------------------ commands
    def set_intensity(self, ch, value, source: str = "gui") -> dict:
        chans = channels_from(ch)
        v = _number(value, "intensity")
        with self._lock:
            self._guard_ai(source)
            if self.estopped:
                raise ControlForbidden("EMERGENCY STOP active — re-enable it from the GUI")
            limit = self.cap(source)
            applied = max(0.0, min(float(limit), v))
            for i in chans:
                self.ch[i].target = applied
                self.last_source[i] = source
            if source == "ai":
                self.ai_last_action = f"intensity {_names(chans)} = {applied:.0f}"
            return {"channels": _names(chans), "applied": applied, "clamped": applied != v, "limit": limit}

    def set_fraction(self, ch, fraction, source: str = "osc") -> dict:
        f = max(0.0, min(1.0, _number(fraction, "fraction")))
        return self.set_intensity(ch, f * self.cap(source), source)

    def set_frequency(self, ch, hz, source: str = "gui") -> dict:
        chans = channels_from(ch)
        v = _number(hz, "frequency")
        with self._lock:
            self._guard_ai(source)
            applied = max(protocol.MIN_HZ, min(protocol.MAX_HZ, v))
            for i in chans:
                self.ch[i].freq_hz = applied
            if source == "ai":
                self.ai_last_action = f"frequency {_names(chans)} = {applied:.0f} Hz"
            return {"channels": _names(chans), "applied": applied, "clamped": applied != v}

    def set_width(self, ch, width, source: str = "gui") -> dict:
        chans = channels_from(ch)
        v = _number(width, "width")
        with self._lock:
            self._guard_ai(source)
            applied = max(0.0, min(float(protocol.WIDTH_MAX), v))
            for i in chans:
                self.ch[i].width = applied
            if source == "ai":
                self.ai_last_action = f"pulse width {_names(chans)} = {applied:.0f}"
            return {"channels": _names(chans), "applied": applied, "clamped": applied != v}

    def set_pattern(self, name=None, speed=None, channels=None, alternate=None, source: str = "gui") -> dict:
        with self._lock:
            self._guard_ai(source)
            if name is not None and name not in patterns.PATTERNS:
                raise ControlError(f"unknown pattern: {name!r}. Options: {', '.join(patterns.PATTERNS)}")
            new_speed = None if speed is None else max(0.25, min(4.0, _number(speed, "speed")))
            new_chans = None if channels is None else channels_from(channels)
            if alternate is not None and not isinstance(alternate, bool):
                raise ControlError("'alternate' must be true/false")
            if new_speed is not None:
                self.pattern_speed = new_speed
            if new_chans is not None:
                self.pattern_channels = new_chans
            if alternate is not None:
                self.pattern_alternate = alternate
            if name is not None:
                self.pattern = name
                self._pclock = 0.0
                self.log(f"Pattern: {patterns.PATTERNS[name].label} ({source})")
                if source == "ai":
                    self.ai_last_action = f"pattern {patterns.PATTERNS[name].label}"
            return self._pattern_state()

    def _pattern_state(self) -> dict:
        p = patterns.PATTERNS[self.pattern]
        return {
            "name": self.pattern, "label": p.label, "speed": self.pattern_speed,
            "channels": _names(self.pattern_channels), "alternate": self.pattern_alternate,
        }

    # ------------------------------------------------------------------ shock (a timed minimum level)
    def _channel_shocking(self, i: int, now: float) -> bool:
        return now < self.shock_until[i] and self.shock_level[i] > 0

    def _shock_running(self, now: float) -> bool:
        return any(self._channel_shocking(i, now) for i in (0, 1))

    def _clear_shock_locked(self) -> None:
        self.shock_level = [0.0, 0.0]
        self.shock_until = [0.0, 0.0]

    def _expire_shock(self, now: float) -> None:
        """Clears the channels whose shock time is up (the caller holds the lock)."""
        for i in (0, 1):
            if self.shock_until[i] and now >= self.shock_until[i]:
                self.shock_until[i] = 0.0
                self.shock_level[i] = 0.0
                self.log(f"Shock ended on {'AB'[i]}")

    def shock_active(self, ch=None) -> bool:
        """True while a shock runs on any channel, or on one of `ch` ("A", "B", "AB") when it is given."""
        chans = (0, 1) if ch is None else channels_from(ch)
        with self._lock:
            now = self._clock()
            self._expire_shock(now)
            return any(self._channel_shocking(i, now) for i in chans)

    def start_shocks(self, plan: dict, source: str = "osc") -> dict:
        """Starts timed shocks, each channel with its own level and its own duration: `plan` is
        {"A": (level, seconds), "B": (level, seconds)} (one or both). For its `seconds` a channel never goes below its
        `level`. It is a MINIMUM, so it never lowers what the window, VRChat or the AI already ask for. The ceiling, the rise
        limit and the emergency stop apply. All or nothing: it refuses if any of the channels is already shocking."""
        if not isinstance(plan, dict) or not plan:
            raise ControlError("no shock requested")
        wanted = {}
        for ch, (level, seconds) in plan.items():
            (i,) = channels_from(ch)
            wanted[i] = (_number(level, "intensity"), _number(seconds, "seconds"))
        with self._lock:
            if self.estopped:
                raise ControlForbidden("EMERGENCY STOP active — re-enable it from the GUI")
            now = self._clock()
            self._expire_shock(now)
            busy = [i for i in wanted if self._channel_shocking(i, now)]
            if busy:
                raise ControlError("a shock is already running on " + _names(busy))
            result, parts = {}, []
            for i in sorted(wanted):
                v, secs = wanted[i]
                applied = max(0.0, min(float(self.cap("gui")), v))
                duration = max(0.0, min(float(SHOCK_MAX_SECONDS), secs))
                self.shock_level[i] = applied
                self.shock_until[i] = now + duration
                result["AB"[i]] = {"applied": applied, "seconds": duration, "clamped": applied != v or duration != secs}
                parts.append(f"{'AB'[i]} at {applied:.0f} for {duration:.0f} s")
            self.log(f"SHOCK ({source}): " + ", ".join(parts))
            return result

    def start_shock(self, ch, level, seconds, source: str = "osc") -> dict:
        """The same level and duration on one or both channels (see start_shocks)."""
        chans = channels_from(ch)
        per = self.start_shocks({"AB"[i]: (level, seconds) for i in chans}, source)
        first = per["AB"[chans[0]]]
        return {"channels": _names(chans), "applied": first["applied"], "seconds": first["seconds"],
                "clamped": any(v["clamped"] for v in per.values())}

    def stop_shock(self, reason: str = "") -> bool:
        """Cancels every running shock at once. Returns True if there was one."""
        with self._lock:
            was = self._shock_running(self._clock())
            self._clear_shock_locked()
            if was:
                self.log("Shock stopped" + (f": {reason}" if reason else ""))
            return was

    def emergency_stop(self, source: str = "gui") -> None:
        with self._lock:
            self.estopped = True
            self._clear_shock_locked()
            for c in self.ch:
                c.target = 0.0
                c.output = 0.0
            self.log(f"EMERGENCY STOP ({source}) — intensities zeroed and commands blocked")

    def resume(self, source: str = "gui") -> None:
        if source != "gui":
            raise ControlForbidden("the emergency stop can only be cleared from the GUI")
        with self._lock:
            if self.estopped:
                self.estopped = False
                self.log("Emergency stop cleared — commands enabled")

    def reset_on_connect(self) -> None:
        with self._lock:
            self._clear_shock_locked()
            for c in self.ch:
                c.target = 0.0
                c.output = 0.0
                c.actual = None
            self.log("Intensities zeroed for safety on connect")

    def configure(self, **kw) -> set:
        """Changes limits at runtime. Returns the keys that actually changed."""
        changed: set = set()
        with self._lock:
            for key, value in kw.items():
                if key == "ai_enabled":
                    new = bool(value)
                elif key in self._RANGES:
                    lo, hi = self._RANGES[key]
                    new = int(max(lo, min(hi, round(_number(value, key)))))
                else:
                    raise ControlError(f"unknown setting: {key}")
                if getattr(self.settings, key) != new:
                    setattr(self.settings, key, new)
                    changed.add(key)
            if "ai_enabled" in changed:
                on = self.settings.ai_enabled
                self.log("AI control " + ("ENABLED" if on else "disabled"))
                if not on:  # also revoke access for whatever the AI had already turned on
                    for i, c in enumerate(self.ch):
                        if self.last_source[i] == "ai" and c.target > 0:
                            c.target = 0.0
                            self.log(f"Channel {'AB'[i]} zeroed: AI disabled")
            if changed & {"max_intensity", "ai_cap", "ai_enabled"}:
                self.apply_limits()
        return changed

    # ------------------------------------------------------------------ OSC
    def note_osc_packet(self) -> None:
        self.last_osc = self._clock()

    def record_osc_value(self, idx: int, fraction: float) -> None:
        self.osc_values[idx] = fraction

    def set_actual(self, a: int, b: int) -> None:
        with self._lock:
            self.ch[0].actual = a
            self.ch[1].actual = b

    # ------------------------------------------------------------------ 100 ms step
    def _watchdog(self, now: float) -> None:
        timeout = self.settings.osc_timeout_s
        if timeout > 0 and self.last_osc is not None and now - self.last_osc > timeout:
            for i, c in enumerate(self.ch):
                if self.last_source[i] == "osc" and c.target > 0:
                    c.target = 0.0
                    self.log(f"OSC watchdog: VRChat silent for more than {timeout}s — channel {'AB'[i]} zeroed")

    def step(self, dt: float) -> Frame:
        """Called every 100 ms by the BLE loop: applies the ramp and produces the 4 slices of 25 ms per channel."""
        dt = max(0.0, min(dt, 0.5))
        with self._lock:
            now = self._clock()
            self._watchdog(now)
            self._expire_shock(now)
            cap = self.settings.max_intensity
            up = self.settings.ramp_up_per_s
            intens: list[int] = []
            for i, c in enumerate(self.ch):
                target = c.target
                if self._channel_shocking(i, now) and not self.estopped:
                    target = max(target, min(self.shock_level[i], float(cap)))  # a minimum, never a reduction
                if self.estopped:
                    c.target = 0.0
                    c.output = 0.0
                elif up > 0 and target > c.output:
                    c.output = min(target, c.output + up * dt)
                else:
                    c.output = target
                c.output = min(c.output, float(cap))
                intens.append(int(round(c.output)))

            speed = self.pattern_speed
            half = patterns.PATTERNS[self.pattern].period / 2.0
            freqs: list[list[int]] = []
            widths: list[list[int]] = []
            for i, c in enumerate(self.ch):
                hz_l: list[float] = []
                w_l: list[float] = []
                for k in range(4):
                    t = self._pclock + k * 0.025 * speed
                    if self.pattern != "const" and i in self.pattern_channels:
                        if self.pattern_alternate and i == 1:
                            t += half
                        hz, w = patterns.sample(self.pattern, t, c.freq_hz, c.width, self._seed[i])
                    else:
                        hz, w = c.freq_hz, c.width
                    hz_l.append(hz)
                    w_l.append(w)
                fb, wb = protocol.sanitize_slices(hz_l, w_l)
                freqs.append(fb)
                widths.append(wb)
            self._pclock += dt * speed
            return Frame((intens[0], intens[1]), (freqs[0], freqs[1]), (widths[0], widths[1]))

    # ------------------------------------------------------------------ reading
    def snapshot(self) -> dict:
        with self._lock:
            now = self._clock()
            self._expire_shock(now)
            shock_on = self._shock_running(now)
            remaining = [max(0.0, self.shock_until[i] - now) if self._channel_shocking(i, now) else 0.0 for i in (0, 1)]
            return {
                "channels": {
                    "AB"[i]: {
                        "target": round(c.target, 1),
                        "output": round(c.output, 1),
                        "actual": c.actual,
                        "freq_hz": round(c.freq_hz, 1),
                        "width": round(c.width, 1),
                        "source": self.last_source[i],
                    }
                    for i, c in enumerate(self.ch)
                },
                "estopped": self.estopped,
                "pattern": self._pattern_state(),
                "limits": {
                    "max_intensity": self.settings.max_intensity,
                    "ai_cap": self.settings.ai_cap,
                    "ramp_up_per_s": self.settings.ramp_up_per_s,
                    "ai_enabled": self.settings.ai_enabled,
                    "osc_timeout_s": self.settings.osc_timeout_s,
                },
                "osc": {
                    "last_packet_age_s": None if self.last_osc is None else round(now - self.last_osc, 1),
                    "A": self.osc_values[0],
                    "B": self.osc_values[1],
                },
                "ai_last_action": self.ai_last_action,
                "shock": {
                    "active": shock_on,
                    "remaining_s": round(max(remaining), 1),
                    "remaining": {"A": round(remaining[0], 1), "B": round(remaining[1], 1)},
                    "level": {"A": round(self.shock_level[0], 1), "B": round(self.shock_level[1], 1)},
                },
            }
