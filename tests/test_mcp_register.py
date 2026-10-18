import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from coyote_vrc import mcp_register as reg

ROOT = Path(__file__).resolve().parent.parent
WIN_ENTRY = {
    "command": r"C:\Users\someone\Downloads\coyote-vrchat\.venv\Scripts\python.exe",
    "args": [r"C:\Users\someone\Downloads\coyote-vrchat\coyote_mcp.py"],
}


class Merge(unittest.TestCase):
    def test_creates_from_nothing(self):
        for text in (None, "", "   \n"):
            new, action = reg.merge_config(text, WIN_ENTRY)
            self.assertEqual(action, "created")
            self.assertEqual(json.loads(new), {"mcpServers": {"coyote": WIN_ENTRY}})

    def test_windows_paths_survive_json_escaping(self):
        new, _ = reg.merge_config(None, WIN_ENTRY)
        self.assertEqual(json.loads(new)["mcpServers"]["coyote"], WIN_ENTRY)
        self.assertIn(r"C:\\Users\\someone", new)       # doubled backslashes in the file, as JSON requires

    def test_keeps_everything_else(self):
        original = {"globalShortcut": "Ctrl+Alt+Space", "mcpServers": {"outro": {"command": "node", "args": ["x.js"]}},
                    "preferences": {"a": [1, 2, {"b": None}]}}
        new, action = reg.merge_config(json.dumps(original), WIN_ENTRY)
        data = json.loads(new)
        self.assertEqual(action, "created")
        self.assertEqual(data["globalShortcut"], "Ctrl+Alt+Space")
        self.assertEqual(data["preferences"], original["preferences"])
        self.assertEqual(data["mcpServers"]["outro"], original["mcpServers"]["outro"])
        self.assertEqual(data["mcpServers"]["coyote"], WIN_ENTRY)

    def test_update_and_idempotent(self):
        old = {"mcpServers": {"coyote": {"command": "old", "args": []}}}
        new, action = reg.merge_config(json.dumps(old), WIN_ENTRY)
        self.assertEqual(action, "updated")
        again, action2 = reg.merge_config(new, WIN_ENTRY)
        self.assertEqual((action2, json.loads(again)), ("unchanged", json.loads(new)))

    def test_bom_is_tolerated(self):
        new, action = reg.merge_config("\ufeff" + json.dumps({"mcpServers": {}}), WIN_ENTRY)
        self.assertEqual(action, "created")

    def test_refuses_weird_files(self):
        for bad in ("{ this is not json", "[1, 2]", '"text"', '{"mcpServers": []}', '{"mcpServers": 3}'):
            with self.assertRaises(reg.ConfigError, msg=bad):
                reg.merge_config(bad, WIN_ENTRY)

    def test_python_for_mcp_swaps_pythonw(self):
        self.assertEqual(reg.python_for_mcp("/x/y/pythonw.exe"), str(Path("/x/y/python.exe")))
        self.assertEqual(reg.python_for_mcp("/x/y/python.exe"), str(Path("/x/y/python.exe")))

    def test_mcp_launch_uses_bundled_exe_when_frozen(self):
        cmd, script = reg.mcp_launch("s.py", frozen=True, exe="/x/CoyoteVRChat.exe")
        self.assertEqual((cmd, script), (str(Path("/x/coyote-mcp.exe")), None))
        self.assertEqual(reg.server_entry(cmd, script), {"command": cmd, "args": []})
        self.assertEqual(reg.mcp_launch("s.py", frozen=False, exe="/x/pythonw.exe"), (str(Path("/x/python.exe")), "s.py"))


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_file_and_parent_folder(self):
        cfg = self.dir / "Claude" / "claude_desktop_config.json"
        res = reg.register_desktop("py", "script.py", [cfg])
        self.assertEqual([r.action for r in res], ["created"])
        self.assertEqual(json.loads(cfg.read_text("utf-8"))["mcpServers"]["coyote"], {"command": "py", "args": ["script.py"]})
        self.assertIsNone(res[0].backup)

    def test_backup_then_idempotent_second_run(self):
        cfg = self.dir / "c.json"
        original = json.dumps({"mcpServers": {"outro": {"command": "x"}}, "k": 1})
        cfg.write_text(original, "utf-8")
        r1 = reg.register_desktop("py", "s.py", [cfg])[0]
        self.assertEqual(r1.action, "created")
        self.assertEqual(r1.backup.read_text("utf-8"), original)          # faithful copy of what was there
        after = cfg.read_text("utf-8")
        r2 = reg.register_desktop("py", "s.py", [cfg])[0]
        self.assertEqual(r2.action, "unchanged")
        self.assertEqual(cfg.read_text("utf-8"), after)
        self.assertEqual(len(list(self.dir.glob("c.json.bak-*"))), 1)     # did not make another copy
        self.assertFalse((self.dir / "c.json.tmp").exists())

    def test_invalid_json_is_left_untouched(self):
        cfg = self.dir / "c.json"
        cfg.write_text("{ broken", "utf-8")
        r = reg.register_desktop("py", "s.py", [cfg])[0]
        self.assertEqual(r.action, "error")
        self.assertIn("JSON", r.error)
        self.assertEqual(cfg.read_text("utf-8"), "{ broken")
        self.assertEqual(list(self.dir.glob("*.bak-*")), [])

    def test_candidate_paths_finds_both_install_styles(self):
        appdata = self.dir / "Roaming"
        local = self.dir / "Local"
        store = local / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
        store.mkdir(parents=True)
        (store / reg.CONFIG_NAME).write_text("{}", "utf-8")
        paths = reg.candidate_paths({"APPDATA": str(appdata), "LOCALAPPDATA": str(local)})
        self.assertEqual(paths, [appdata / "Claude" / reg.CONFIG_NAME, store / reg.CONFIG_NAME])
        self.assertEqual(reg.candidate_paths({}), [])

    def test_default_targets_prefer_existing_files(self):
        appdata, local = self.dir / "Roaming", self.dir / "Local"
        store = local / "Packages" / "Claude_abc" / "LocalCache" / "Roaming" / "Claude"
        store.mkdir(parents=True)
        (store / reg.CONFIG_NAME).write_text("{}", "utf-8")
        orig = reg.candidate_paths
        reg.candidate_paths = lambda env=None: orig({"APPDATA": str(appdata), "LOCALAPPDATA": str(local)})
        try:
            res = reg.register_desktop("py", "s.py")
        finally:
            reg.candidate_paths = orig
        self.assertEqual([r.path for r in res], [store / reg.CONFIG_NAME])   # only what existed
        self.assertFalse((appdata / "Claude").exists())

    def test_default_creates_standard_location_when_none_exists(self):
        appdata = self.dir / "Roaming"
        orig = reg.candidate_paths
        reg.candidate_paths = lambda env=None: orig({"APPDATA": str(appdata)})
        try:
            res = reg.register_desktop("py", "s.py")
        finally:
            reg.candidate_paths = orig
        self.assertEqual(res[0].action, "created")
        self.assertTrue((appdata / "Claude" / reg.CONFIG_NAME).exists())

    def test_no_known_location(self):
        orig = reg.candidate_paths
        reg.candidate_paths = lambda env=None: []
        try:
            res = reg.register_desktop("py", "s.py")
        finally:
            reg.candidate_paths = orig
        self.assertEqual(res[0].action, "error")


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "register_claude_desktop.py"), *args],
                              capture_output=True, text=True, timeout=30, cwd=tempfile.gettempdir())

    def test_print_does_not_write_and_points_to_this_install(self):
        p = self.run_cli("--print")
        self.assertEqual(p.returncode, 0, p.stderr)
        entry = json.loads(p.stdout)["mcpServers"]["coyote"]
        self.assertEqual(Path(entry["args"][0]), ROOT / "coyote_mcp.py")
        self.assertTrue(Path(entry["args"][0]).exists())

    def test_writes_given_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "x" / "cfg.json"
            p = self.run_cli("--config", str(cfg))
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            self.assertIn("created", p.stdout)
            self.assertEqual(json.loads(cfg.read_text("utf-8"))["mcpServers"]["coyote"]["args"],
                             [str(ROOT / "coyote_mcp.py")])

    def test_bad_config_returns_error(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "cfg.json"
            cfg.write_text("not json", "utf-8")
            p = self.run_cli("--config", str(cfg))
            self.assertEqual(p.returncode, 1)
            self.assertEqual(cfg.read_text("utf-8"), "not json")


if __name__ == "__main__":
    unittest.main()
