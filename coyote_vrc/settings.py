"""Persistent settings (JSON in %APPDATA%\\CoyoteVRChat\\settings.json)."""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, fields
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
    # --- shock trigger: someone touches the avatar's ShockOSC contact -> a timed shock at a random power
    osc_param_shock: str = "ShockOsc/_all"  # bool contact on the avatar (compared ignoring upper/lower case)
    shock_enabled: bool = False       # NOT persisted: always starts off
    shock_min_pct: int = 10           # the power is drawn at random between these two, in % of the intensity ceiling
    shock_max_pct: int = 30
    shock_seconds: int = 3            # how long one shock lasts (1..30)
    shock_channels: str = "AB"        # "A", "B" or "AB"
    chatbox_enabled: bool = True      # say the power in the VRChat chatbox when a shock starts
    chatbox_host: str = "127.0.0.1"
    chatbox_port: int = 9000          # VRChat listens for OSC input here (its output goes to 9001)
    chatbox_text: str = "Shock {percent}%"   # {percent} and {seconds} are replaced
    chatbox_clear_s: int = 3          # remove the message from the chatbox after this many seconds (0 = leave it to VRChat)
    # --- AI
    ai_enabled: bool = False          # NOT persisted: always starts off
    ai_cap: int = 50                  # maximum intensity the AI may request
    api_port: int = 8765
    api_token: str = ""
    # --- initial defaults for each channel
    default_freq_hz: float = 50.0
    default_width: int = 100

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
        self.shock_min_pct = _clamp_int(self.shock_min_pct, 1, 100, 10)
        self.shock_max_pct = _clamp_int(self.shock_max_pct, 1, 100, 30)
        if self.shock_min_pct > self.shock_max_pct:
            self.shock_min_pct, self.shock_max_pct = self.shock_max_pct, self.shock_min_pct
        self.shock_seconds = _clamp_int(self.shock_seconds, 1, 30, 3)
        letters = "".join(c for c in "AB" if c in str(self.shock_channels).upper())
        self.shock_channels = letters or "AB"
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
        for name in ("osc_param_a", "osc_param_b", "osc_param_stop", "osc_param_freq", "osc_param_shock"):
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


def load_settings(path: Optional[Path] = None) -> Settings:
    if path is None and not default_settings_path().exists():
        _import_store_python_settings(default_settings_path())
    path = Path(path) if path else default_settings_path()
    settings = Settings()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            known = {f.name for f in fields(Settings)}
            for key, value in raw.items():
                if key in known:
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
