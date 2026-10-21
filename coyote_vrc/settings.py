"""Persistent settings (JSON in %APPDATA%\\CoyoteVRChat\\settings.json)."""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "CoyoteVRChat"


def default_settings_path() -> Path:
    return config_dir() / "settings.json"


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


DEFAULT_CONTACT = "ShockOsc/_all"      # the contact of the ShockOSC / OpenShock avatar prefabs
DEFAULT_CHATBOX_TEXT = "Shock {shock}"
MAX_SHOCK_TRIGGERS = 8
SHOCK_CHANNELS = ("a", "b")            # the two channels have their own random power and duration


def default_triggers() -> list:
    """One trigger, on the standard contact, that fires BOTH channels."""
    return [{"param": DEFAULT_CONTACT, "a": True, "b": True}]


def normalize_triggers(value) -> list:
    """A clean list of {"param", "a", "b"}: names stripped, empty ones and repeats (ignoring upper/lower case) dropped, at
    most MAX_SHOCK_TRIGGERS, and every trigger fires at least one channel. Anything that is not a list gives the default."""
    if not isinstance(value, (list, tuple)):
        return default_triggers()
    out, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            continue
        param = str(item.get("param") or "").strip()
        if not param or param.lower() in seen:
            continue
        a, b = bool(item.get("a", True)), bool(item.get("b", True))
        if not a and not b:
            a = b = True
        seen.add(param.lower())
        out.append({"param": param, "a": a, "b": b})
        if len(out) >= MAX_SHOCK_TRIGGERS:
            break
    return out


@dataclass
class Settings:
    # --- Bluetooth
    device_address: str = ""
    auto_reconnect: bool = True
    # --- limits (apply to every source)
    max_intensity: int = 200          # soft limit written to the device (BF) and the ceiling for everything
    ramp_up_per_s: int = 100          # max rise in units/s (0 = unlimited); lowering is always immediate
    # --- balance (BF) — see docs: 0..255
    freq_balance_a: int = 160
    freq_balance_b: int = 160
    width_balance_a: int = 100
    width_balance_b: int = 100
    # --- VRChat OSC (VRChat SENDS on 9001 by default)
    osc_enabled: bool = True
    osc_host: str = "127.0.0.1"
    osc_port: int = 9001
    osc_param_a: str = "CoyoteA"
    osc_param_b: str = "CoyoteB"
    osc_param_stop: str = "CoyoteStop"
    osc_param_freq: str = "CoyoteFreq"   # Int in Hz (1..100) -> frequency of BOTH channels
    osc_timeout_s: int = 0            # 0 = off; >0 zeroes the OSC channels if VRChat goes silent
    # --- shock trigger: someone touches a contact on the avatar -> a timed shock at a random power, per channel
    shock_enabled: bool = False       # NOT persisted: always starts off
    # each channel draws its own power (% of the intensity ceiling) and its own duration (1..30 s) between these limits
    shock_a_min_pct: int = 10
    shock_a_max_pct: int = 30
    shock_a_min_s: int = 3
    shock_a_max_s: int = 5
    shock_b_min_pct: int = 10
    shock_b_max_pct: int = 30
    shock_b_min_s: int = 3
    shock_b_max_s: int = 5
    # contacts (bool avatar parameters, compared ignoring upper/lower case) and the channels each one fires
    shock_triggers: list = field(default_factory=default_triggers)
    chatbox_enabled: bool = True      # say the power in the VRChat chatbox when a shock starts
    chatbox_host: str = "127.0.0.1"
    chatbox_port: int = 9000          # VRChat listens for OSC input here (its output goes to 9001)
    chatbox_text: str = DEFAULT_CHATBOX_TEXT   # {shock} = "A 37% for 5 s, B 20% for 3 s"; see shock.render_text
    chatbox_clear_s: int = 3          # remove the message from the chatbox after this many seconds (0 = leave it to VRChat)
    # --- AI
    ai_enabled: bool = False          # NOT persisted: always starts off
    ai_cap: int = 50                  # maximum intensity the AI may request
    api_port: int = 8765
    api_token: str = ""
    # --- initial defaults for each channel
    default_freq_hz: float = 50.0
    default_width: int = 100

    def shock_limits(self, ch: str) -> tuple:
        """(min %, max %, min s, max s) of one channel, "A" or "B"."""
        c = str(ch).lower()
        return (getattr(self, f"shock_{c}_min_pct"), getattr(self, f"shock_{c}_max_pct"),
                getattr(self, f"shock_{c}_min_s"), getattr(self, f"shock_{c}_max_s"))

    def validate(self) -> "Settings":
        self.max_intensity = _clamp_int(self.max_intensity, 0, 200, 200)
        self.ramp_up_per_s = _clamp_int(self.ramp_up_per_s, 0, 400, 100)
        for name in ("freq_balance_a", "freq_balance_b", "width_balance_a", "width_balance_b"):
            setattr(self, name, _clamp_int(getattr(self, name), 0, 255, 100))
        self.osc_port = _clamp_int(self.osc_port, 1, 65535, 9001)
        self.api_port = _clamp_int(self.api_port, 1, 65535, 8765)
        self.osc_timeout_s = _clamp_int(self.osc_timeout_s, 0, 3600, 0)
        self.ai_cap = _clamp_int(self.ai_cap, 0, 200, 50)
        self.default_width = _clamp_int(self.default_width, 0, 100, 100)
        for ch in SHOCK_CHANNELS:
            for kind, lo, hi, d_lo, d_hi in (("pct", 1, 100, 10, 30), ("s", 1, 30, 3, 5)):
                low, high = f"shock_{ch}_min_{kind}", f"shock_{ch}_max_{kind}"
                a = _clamp_int(getattr(self, low), lo, hi, d_lo)
                b = _clamp_int(getattr(self, high), lo, hi, d_hi)
                setattr(self, low, min(a, b))
                setattr(self, high, max(a, b))
        self.shock_triggers = normalize_triggers(self.shock_triggers)
        self.chatbox_port = _clamp_int(self.chatbox_port, 1, 65535, 9000)
        self.chatbox_host = str(self.chatbox_host or "127.0.0.1").strip() or "127.0.0.1"
        self.chatbox_text = str(self.chatbox_text if self.chatbox_text is not None else "")[:100]
        self.chatbox_clear_s = _clamp_int(self.chatbox_clear_s, 0, 60, 3)
        if 0 < self.chatbox_clear_s < 2:      # VRChat drops messages that follow each other faster than ~1.6 s
            self.chatbox_clear_s = 2
        self.shock_enabled = bool(self.shock_enabled)
        self.chatbox_enabled = bool(self.chatbox_enabled)
        try:
            self.default_freq_hz = max(1.0, min(100.0, float(self.default_freq_hz)))
        except (TypeError, ValueError):
            self.default_freq_hz = 50.0
        self.osc_host = str(self.osc_host or "127.0.0.1")
        for name in ("osc_param_a", "osc_param_b", "osc_param_stop", "osc_param_freq"):
            setattr(self, name, str(getattr(self, name) or "").strip())
        self.ai_enabled = bool(self.ai_enabled)
        self.osc_enabled = bool(self.osc_enabled)
        self.auto_reconnect = bool(self.auto_reconnect)
        return self


def _import_store_python_settings(target: Path) -> None:
    """The Microsoft-Store Python keeps %APPDATA% in a private folder, so a copy of the program started from it has its
    settings (ceiling, rise limit, API token...) somewhere the packaged .exe cannot see. Copy them once, so that
    switching to the .exe does not silently put the safety limits back to their defaults."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return
    try:
        found = sorted(Path(base).glob("Packages/PythonSoftwareFoundation.Python.*/LocalCache/Roaming/CoyoteVRChat/settings.json"))
        if found and found[0].is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(found[0].read_bytes())
    except OSError:
        pass


# The old default messages only said one power (and, from 1.2.1, one duration). A settings file that still holds exactly
# one of them was not edited on purpose (the program saves every field), so it takes the new default, which says the power
# and the duration of each channel.
_OLD_DEFAULT_CHATBOX_TEXTS = ("Shock {percent}%", "Shock {percent}% for {seconds} s")


_OLD_SHOCK_KEYS = ("osc_param_shock", "shock_min_pct", "shock_max_pct", "shock_seconds", "shock_channels")


def _migrate_single_shock(raw: dict) -> None:
    """Versions up to 1.2.1 had ONE power range, ONE duration, one channel choice and one contact for the whole trigger.
    The same numbers become the starting point of both channels and of a single trigger (the shock behaves as before)."""
    if not isinstance(raw, dict) or "shock_triggers" in raw or not any(k in raw for k in _OLD_SHOCK_KEYS):
        return
    try:
        lo, hi = int(raw.get("shock_min_pct", 10)), int(raw.get("shock_max_pct", 30))
        secs = int(raw.get("shock_seconds", 3))
    except (TypeError, ValueError):
        lo, hi, secs = 10, 30, 3
    for ch in SHOCK_CHANNELS:
        raw.setdefault(f"shock_{ch}_min_pct", lo)
        raw.setdefault(f"shock_{ch}_max_pct", hi)
        raw.setdefault(f"shock_{ch}_min_s", secs)
        raw.setdefault(f"shock_{ch}_max_s", secs)
    letters = str(raw.get("shock_channels", "AB")).upper()
    param = str(raw.get("osc_param_shock") or DEFAULT_CONTACT).strip() or DEFAULT_CONTACT
    raw["shock_triggers"] = [{"param": param, "a": "A" in letters or "B" not in letters,
                              "b": "B" in letters or "A" not in letters}]


def load_settings(path: Optional[Path] = None) -> Settings:
    if path is None and not default_settings_path().exists():
        _import_store_python_settings(default_settings_path())
    path = Path(path) if path else default_settings_path()
    settings = Settings()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            known = {f.name for f in fields(Settings)}
            _migrate_single_shock(raw)
            for key, value in raw.items():
                if key in known:
                    if key == "chatbox_text" and value in _OLD_DEFAULT_CHATBOX_TEXTS:
                        continue
                    setattr(settings, key, value)
        except (OSError, ValueError):
            try:  # corrupted file: keep a copy and start over from the defaults
                path.replace(path.with_suffix(".json.bak"))
            except OSError:
                pass
            settings = Settings()
    settings.ai_enabled = False  # safety: AI control always starts off
    settings.shock_enabled = False  # safety: the shock trigger (other players can fire it) always starts off
    settings.validate()
    if not settings.api_token:
        settings.api_token = secrets.token_urlsafe(24)
        save_settings(settings, path)
    return settings


def save_settings(settings: Settings, path: Optional[Path] = None) -> None:
    path = Path(path) if path else default_settings_path()
    data = asdict(settings)
    data["ai_enabled"] = False
    data["shock_enabled"] = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # settings are "best effort"; never bring the app down
