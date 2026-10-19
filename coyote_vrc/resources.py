"""Where the program's bundled files (the logo) live: next to the source, or inside the packaged .exe (PyInstaller)."""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when this is the packaged CoyoteVRChat.exe."""
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def asset_path(name: str) -> Path:
    """assets/<name>: the logo (coyote.ico, coyote.png)."""
    return base_dir() / "assets" / name
