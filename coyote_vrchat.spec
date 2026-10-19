# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for CoyoteVRChat.exe: ONE file, no console window, with the logo and Windows version information.

Build it with build_exe.bat, or by hand:  pyinstaller coyote_vrchat.spec --noconfirm --clean
The result is dist/CoyoteVRChat.exe.
"""
import os
import re

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
                                                 VarStruct, VSVersionInfo)

ROOT = os.path.abspath(SPECPATH)  # noqa: F821  (SPECPATH is provided by PyInstaller)
with open(os.path.join(ROOT, "coyote_vrc", "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)
nums = tuple(int(p) for p in (VERSION.split(".") + ["0", "0", "0"])[:3]) + (0,)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("FileDescription", "Coyote x VRChat"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "CoyoteVRChat"),
            StringStruct("LegalCopyright", "MIT License"),
            StringStruct("OriginalFilename", "CoyoteVRChat.exe"),
            StringStruct("ProductName", "Coyote x VRChat"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

hidden = collect_submodules("bleak")
try:                                   # the Windows Bluetooth bindings that bleak loads by name
    hidden += collect_submodules("winrt")
except Exception:
    pass

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "assets", "coyote.ico"), "assets"), (os.path.join(ROOT, "assets", "coyote.png"), "assets")],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CoyoteVRChat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                         # UPX-packed programs are flagged by antivirus far more often
    console=False,                     # double-click opens only the window; --selftest/--headless print into the terminal
    icon=os.path.join(ROOT, "assets", "coyote.ico"),
    version=version_info,
)
