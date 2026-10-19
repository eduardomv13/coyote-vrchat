"""`--selftest`: checks that the program can run on this computer (without opening the window or touching the device).

It prints one line per check and exits with 0 when everything the program needs is there. A Bluetooth adapter that is
missing or a busy port are reported as warnings, because they can be fixed after the program is installed.
"""
from __future__ import annotations

import asyncio
import platform
import socket
import sys

from . import __version__
from .resources import asset_path, is_frozen
from .settings import default_settings_path


def _line(status: str, text: str) -> None:
    print(f"[{status:<4}] {text}")


def _bluetooth_scan(seconds: float = 3.0):
    """(ok, text): a short passive scan, to see that Windows Bluetooth answers and whether a Coyote is advertising."""
    try:
        from bleak import BleakScanner
    except Exception as exc:                      # pragma: no cover - depends on the packaging
        return False, f"bleak (the Bluetooth library) could not be loaded: {exc!r}"

    async def scan():
        return await BleakScanner.discover(timeout=seconds, return_adv=True)

    try:
        found = asyncio.run(scan())
    except Exception as exc:
        return None, f"Bluetooth scan failed ({type(exc).__name__}: {exc}). Is Bluetooth switched on?"
    coyotes = []
    for _addr, (dev, adv) in found.items():
        name = dev.name or adv.local_name or ""
        if name.startswith("47L") or "coyote" in name.lower():
            coyotes.append(name)
    if coyotes:
        return True, f"Bluetooth works; a Coyote is advertising: {', '.join(coyotes)}"
    return True, (f"Bluetooth works ({len(found)} device(s) seen) but no Coyote is advertising: turn it on, bring it closer, "
                  "and close any other app that holds it (the DG-LAB phone app, OpenShock Desktop)")


def _port_free(port: int, udp: bool = True) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def run(scan_seconds: float = 3.0) -> int:
    failed = False
    _line("info", f"Coyote x VRChat {__version__} | {'packaged .exe' if is_frozen() else 'from source'} | "
                  f"Python {platform.python_version()} | {platform.platform()}")
    _line("info", f"settings file: {default_settings_path()}")

    icon = asset_path("coyote.ico")
    _line("ok" if icon.exists() else "FAIL", f"logo: {icon}")
    failed |= not icon.exists()

    try:
        import tkinter
        _line("ok", f"tkinter {tkinter.TkVersion} (the window)")
    except Exception as exc:
        _line("FAIL", f"tkinter could not be loaded: {exc!r}")
        failed = True

    ok, text = _bluetooth_scan(scan_seconds)
    _line("ok" if ok else ("FAIL" if ok is False else "warn"), text)
    failed |= ok is False

    for port, udp, what in ((9001, True, "VRChat OSC output, the program listens here"), (8765, False, "local API for the AI")):
        free = _port_free(port, udp)
        _line("ok" if free else "warn", f"{'UDP' if udp else 'TCP'} port {port} "
              f"{'is free' if free else 'is in use (another program, or this one is already open)'}: {what}")
    _line("info", "result: " + ("PROBLEM, see the FAIL lines above" if failed else "everything the program needs is present"))
    return 1 if failed else 0
