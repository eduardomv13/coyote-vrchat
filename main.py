"""Coyote x VRChat - entry point.

Usage:
  python main.py                opens the window
  python main.py --simulate     opens the window with a FAKE Coyote (to try the interface without the device)
  python main.py --connect      tries to connect to the Coyote right away
  python main.py --headless     no window (OSC + AI API only); Ctrl+C to quit
  python main.py --settings C:\\path\\settings.json   use a different settings file
  python main.py --selftest     checks that everything the program needs is present (and Bluetooth), then exits
  python main.py --mcp          runs as the MCP server for an AI (Claude starts this by itself; not for typing by hand)
  python main.py --version

The packaged CoyoteVRChat.exe takes the same options (without "python main.py").
"""
import argparse
import os
import sys
import time


def _enable_hidpi():
    """On Windows, avoids a blurry window on displays scaled to 125%/150%."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _set_app_id():
    """Gives the taskbar its own identity, so it shows the program's logo instead of grouping it with Python."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("eduardomv13.coyote-vrchat")
    except Exception:
        pass


_FILE_TYPE_DISK, _FILE_TYPE_PIPE = 1, 3


def _is_redirect(file_type: int) -> bool:
    """GetFileType() of the standard output: a file (`> out.txt`) or a pipe (`| more`) must be left exactly as it is."""
    return file_type in (_FILE_TYPE_DISK, _FILE_TYPE_PIPE)


def _ancestor_pids(limit: int = 4) -> list:
    """The process ids of the parent, grandparent... of this process (Windows). The one-file .exe runs the program in a
    CHILD of the process the terminal started, so the terminal's shell is the grandparent, not the parent."""
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)                      # TH32CS_SNAPPROCESS
    parents = {}
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    found, pid = [], os.getpid()
    for _ in range(limit):
        pid = parents.get(pid)
        if not pid:
            break
        found.append(pid)
    return found


def _attach_parent_console():
    """The packaged .exe has no console of its own (so double-clicking it shows only the window). When it is started from
    a terminal with an option that prints (--help, --selftest, --headless, --version), print into that terminal -- unless
    the output is already going to a file or a pipe (`CoyoteVRChat.exe --version > v.txt`, `... | more`, an MCP client)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.GetFileType.argtypes = [wintypes.HANDLE]
        if _is_redirect(kernel32.GetFileType(kernel32.GetStdHandle(-11))):    # STD_OUTPUT_HANDLE
            return
        # ATTACH_PARENT_PROCESS (-1) is tried first; then the ancestors, because of the one-file layout described above
        if not any(kernel32.AttachConsole(pid) for pid in [-1] + _ancestor_pids()):
            return
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stderr = sys.stdout
    except Exception:
        pass


_PRINTING_OPTIONS = ("--help", "-h", "--selftest", "--headless", "--version")


def main(argv=None) -> int:
    from coyote_vrc.resources import is_frozen

    args_in = sys.argv[1:] if argv is None else list(argv)
    if is_frozen() and any(a in _PRINTING_OPTIONS for a in args_in):
        _attach_parent_console()
    if sys.version_info < (3, 10):
        print("This program needs Python 3.10 or newer (you have %d.%d)." % sys.version_info[:2])
        return 2

    ap = argparse.ArgumentParser(description="DG-LAB Coyote 3.0 control from VRChat OSC")
    ap.add_argument("--simulate", action="store_true", help="use a simulated Coyote (no Bluetooth)")
    ap.add_argument("--connect", action="store_true", help="connect on startup")
    ap.add_argument("--headless", action="store_true", help="no window")
    ap.add_argument("--settings", default=None, help="path to settings.json")
    ap.add_argument("--selftest", action="store_true", help="check the installation and Bluetooth, then exit")
    ap.add_argument("--mcp", action="store_true", help="run as the MCP server for an AI (started by Claude)")
    ap.add_argument("--version", action="store_true", help="print the version and exit")
    args = ap.parse_args(argv)

    if args.version:
        from coyote_vrc import __version__

        print(f"Coyote x VRChat {__version__}")
        return 0
    if args.selftest:
        from coyote_vrc import selftest

        return selftest.run()
    if args.mcp:
        from coyote_vrc.mcp_server import main as mcp_main

        mcp_main()
        return 0

    from coyote_vrc.ble import SimulatedTransport
    from coyote_vrc.engine import Engine

    engine = Engine(settings_path=args.settings, transport=SimulatedTransport() if args.simulate else None)
    if args.simulate:
        engine.control.log("SIMULATED MODE: no real device is being used")
    engine.start()
    if args.connect:
        engine.connect()

    if args.headless:
        print("Running without a window. Ctrl+C to quit.")
        try:
            while True:
                time.sleep(5)
                link = engine.link.status()
                osc = engine.osc_status()
                print(f"[bluetooth: {link['state']}] [osc: {osc['packets']} packets] "
                      f"[intensity A/B: {engine.control.snapshot()['channels']['A']['output']:.0f}"
                      f"/{engine.control.snapshot()['channels']['B']['output']:.0f}]")
        except KeyboardInterrupt:
            pass
        finally:
            engine.shutdown()
        return 0

    try:
        from coyote_vrc.gui import App
    except ImportError as exc:
        engine.shutdown()
        print("Could not open the window (tkinter missing?):", exc)
        print("On Windows, reinstall Python with the 'tcl/tk and IDLE' option checked, or use --headless.")
        return 1

    _enable_hidpi()
    _set_app_id()
    app = App(engine)
    try:
        app.mainloop()
    finally:
        engine.shutdown()  # idempotent: does nothing if the window already shut it down
    return 0


if __name__ == "__main__":
    sys.exit(main())
