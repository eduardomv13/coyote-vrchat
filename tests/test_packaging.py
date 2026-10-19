"""The packaged-program support: logo files, --version / --selftest / --mcp, the MCP command of the .exe, the one-time import
of the settings of a Store-Python copy, and the build recipe.

What these do NOT cover: that PyInstaller really produces a working CoyoteVRChat.exe. That is checked by building it and running
it (see README, "Building the .exe yourself").
"""
import contextlib
import importlib
import io
import json
import os
import re
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coyote_vrc import __version__, mcp_register, resources, selftest
from coyote_vrc.settings import default_settings_path, load_settings

ROOT = Path(__file__).resolve().parent.parent


def run_main(*argv):
    main = importlib.import_module("main")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main.main(list(argv))
    return code, out.getvalue()


class Logo(unittest.TestCase):
    def test_ico_has_every_size_windows_needs(self):
        data = (ROOT / "assets" / "coyote.ico").read_bytes()
        reserved, kind, count = struct.unpack_from("<HHH", data, 0)
        self.assertEqual((reserved, kind), (0, 1))
        sizes = set()
        for i in range(count):
            width, height = data[6 + 16 * i], data[7 + 16 * i]
            sizes.add((width or 256, height or 256))
        self.assertEqual(sizes, {(n, n) for n in (16, 24, 32, 48, 64, 128, 256)})

    def test_png_is_square_and_big_enough(self):
        data = (ROOT / "assets" / "coyote.png").read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual(width, height)
        self.assertGreaterEqual(width, 256)

    def test_assets_are_found_from_source(self):
        self.assertFalse(resources.is_frozen())
        self.assertTrue(resources.asset_path("coyote.ico").exists())
        self.assertTrue(resources.asset_path("coyote.png").exists())

    def test_assets_are_found_inside_the_bundle(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", tmp, create=True):
            self.assertTrue(resources.is_frozen())
            self.assertEqual(resources.asset_path("coyote.ico"), Path(tmp) / "assets" / "coyote.ico")


class Options(unittest.TestCase):
    def test_version_option(self):
        code, out = run_main("--version")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), f"Coyote x VRChat {__version__}")

    def test_selftest_passes_when_everything_is_there(self):
        with mock.patch.object(selftest, "_bluetooth_scan", return_value=(True, "Bluetooth works (fake)")):
            code, out = run_main("--selftest")
        self.assertEqual(code, 0)
        self.assertIn(__version__, out)
        self.assertIn("everything the program needs is present", out)
        self.assertIn("tkinter", out)

    def test_selftest_fails_when_the_logo_or_bluetooth_library_is_missing(self):
        with mock.patch.object(selftest, "_bluetooth_scan", return_value=(True, "fake")), \
                mock.patch.object(selftest, "asset_path", return_value=Path("does-not-exist.ico")):
            code, out = run_main("--selftest")
        self.assertEqual(code, 1)
        self.assertIn("[FAIL]", out)
        with mock.patch.object(selftest, "_bluetooth_scan", return_value=(False, "bleak could not be loaded")):
            code, _ = run_main("--selftest")
        self.assertEqual(code, 1)

    def test_selftest_only_warns_about_a_scan_that_failed(self):
        with mock.patch.object(selftest, "_bluetooth_scan", return_value=(None, "Is Bluetooth switched on?")):
            code, out = run_main("--selftest")
        self.assertEqual(code, 0)
        self.assertIn("[warn]", out)

    def test_mcp_option_runs_the_mcp_server(self):
        with mock.patch("coyote_vrc.mcp_server.main") as server:
            code, _ = run_main("--mcp")
        self.assertEqual(code, 0)
        server.assert_called_once_with()


class ConsoleOfTheExe(unittest.TestCase):
    def test_a_file_or_a_pipe_is_never_replaced_by_the_console(self):
        main = importlib.import_module("main")
        self.assertTrue(main._is_redirect(1))      # FILE_TYPE_DISK: > out.txt
        self.assertTrue(main._is_redirect(3))      # FILE_TYPE_PIPE: | more
        self.assertFalse(main._is_redirect(2))     # FILE_TYPE_CHAR: a console
        self.assertFalse(main._is_redirect(0))     # FILE_TYPE_UNKNOWN: no usable output at all (a GUI start from a terminal)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_the_ancestors_start_with_the_parent(self):
        main = importlib.import_module("main")
        pids = main._ancestor_pids()
        self.assertTrue(pids)
        self.assertTrue(all(isinstance(p, int) and p > 0 for p in pids))
        self.assertEqual(pids[0], os.getppid())
        self.assertNotIn(os.getpid(), pids)
        self.assertLessEqual(len(pids), 4)


class McpCommandOfTheExe(unittest.TestCase):
    def test_from_source_it_is_python_and_the_script(self):
        command, args = mcp_register.mcp_launcher("C:/app/coyote_mcp.py")
        self.assertEqual((command, args), (mcp_register.python_for_mcp(), ["C:/app/coyote_mcp.py"]))

    def test_the_exe_runs_itself_with_mcp(self):
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", r"C:\Apps\CoyoteVRChat.exe"):
            command, args = mcp_register.mcp_launcher("ignored.py")
        self.assertEqual((command, args), (str(Path(r"C:\Apps\CoyoteVRChat.exe")), ["--mcp"]))

    def test_registering_the_exe_in_claude_desktop(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "claude_desktop_config.json"
            cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "node"}}}), encoding="utf-8")
            res = mcp_register.register_desktop(r"C:\Apps\CoyoteVRChat.exe", "", [cfg], args=["--mcp"])
            self.assertEqual(res[0].action, "created")
            data = json.loads(cfg.read_text(encoding="utf-8"))
            again = mcp_register.register_desktop(r"C:\Apps\CoyoteVRChat.exe", "", [cfg], args=["--mcp"])
            self.assertEqual(again[0].action, "unchanged")
            moved = mcp_register.register_desktop(r"D:\Tools\CoyoteVRChat.exe", "", [cfg], args=["--mcp"])
            self.assertEqual(moved[0].action, "updated")      # the .exe was moved: the entry follows it
        self.assertEqual(data["mcpServers"]["coyote"], {"command": r"C:\Apps\CoyoteVRChat.exe", "args": ["--mcp"]})
        self.assertEqual(data["mcpServers"]["other"], {"command": "node"})


class ImportOfTheStorePythonSettings(unittest.TestCase):
    """The Microsoft-Store Python hides %APPDATA% in a private folder; the .exe cannot see it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.appdata, self.local = base / "Roaming", base / "Local"
        self.store = (self.local / "Packages" / "PythonSoftwareFoundation.Python.3.12_abc" / "LocalCache" / "Roaming"
                      / "CoyoteVRChat" / "settings.json")
        self.store.parent.mkdir(parents=True)
        self.store.write_text(json.dumps({"max_intensity": 137, "ramp_up_per_s": 400, "api_token": "old-token"}), encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"APPDATA": str(self.appdata), "LOCALAPPDATA": str(self.local)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_the_limits_and_the_token_come_along_once(self):
        self.assertFalse(default_settings_path().exists())
        s = load_settings()
        self.assertEqual((s.max_intensity, s.ramp_up_per_s, s.api_token), (137, 400, "old-token"))
        self.assertTrue(default_settings_path().exists())

    def test_existing_settings_are_never_overwritten(self):
        default_settings_path().parent.mkdir(parents=True)
        default_settings_path().write_text(json.dumps({"max_intensity": 90, "api_token": "mine"}), encoding="utf-8")
        s = load_settings()
        self.assertEqual((s.max_intensity, s.api_token), (90, "mine"))

    def test_an_explicit_path_is_not_touched(self):
        s = load_settings(Path(self.tmp.name) / "other.json")
        self.assertEqual(s.max_intensity, 200)
        self.assertFalse(default_settings_path().exists())

    def test_nothing_to_import_gives_the_defaults(self):
        self.store.unlink()
        self.assertEqual(load_settings().max_intensity, 200)


class BuildRecipe(unittest.TestCase):
    def test_the_spec_builds_one_windowed_file_with_the_logo(self):
        spec = (ROOT / "coyote_vrchat.spec").read_text(encoding="utf-8")
        self.assertIn("console=False", spec)             # double-click opens only the window
        self.assertIn("upx=False", spec)                 # UPX-packed programs are flagged by antivirus much more often
        self.assertIn("coyote.ico", spec)
        self.assertIn('name="CoyoteVRChat"', spec)
        init = (ROOT / "coyote_vrc" / "__init__.py").read_text(encoding="utf-8")
        self.assertEqual(re.search(r'__version__\s*=\s*"([^"]+)"', init).group(1), __version__)

    def test_the_build_script_exists_and_uses_its_own_environment(self):
        bat = (ROOT / "build_exe.bat").read_text(encoding="utf-8")
        self.assertIn(".venv-build", bat)
        self.assertIn("PyInstaller", bat)
        self.assertIn(".venv-build/", (ROOT / ".gitignore").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
