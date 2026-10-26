"""Checks on the Unity package in unity/ that do not need Unity.

What these cover: the package metadata, that every asset has a .meta (Unity ignores assets without one when the
package is installed from git), that the panel layout in C# matches the script that draws the plate texture, and that
the offline controller simulator still passes on the example controller export.
What they do NOT cover: that the C# compiles, that the panel builds, or anything that happens in VRChat. That needs
Unity (see unity/README.md, "What has been tested").
"""
import ast
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "unity" / "io.github.eduardomv13.coyote-panel"
LAYOUT_CS = PKG / "Editor" / "PanelLayout.cs"
TEXTURE_PY = PKG / "Tools~" / "make_textures.py"
EXAMPLE = PKG / "Tools~" / "ctrl.example.json"

SCALARS = ["PW", "PH", "ROW_A", "ROW_B", "ROW_F", "BAR_X0", "BAR_X1", "MINUS_X", "PLUS_X",
           "CELL_W", "CELL_H", "BTN_DN_X", "BTN_UP_X"]
ARRAYS = ["DIG_X", "FDIG_X"]


def cs_scalar(src: str, name: str) -> float:
    m = re.search(r"\b%s\s*=\s*(-?\d+(?:\.\d+)?)f" % re.escape(name), src)
    if not m:
        raise AssertionError("constant %s not found in PanelLayout.cs" % name)
    return float(m.group(1))


def cs_int(src: str, name: str) -> int:
    m = re.search(r"\b%s\s*=\s*(\d+)(?![\d.f])" % re.escape(name), src)
    if not m:
        raise AssertionError("integer constant %s not found in PanelLayout.cs" % name)
    return int(m.group(1))


def cs_array(src: str, name: str):
    m = re.search(r"\b%s\s*=\s*\{([^}]*)\}" % re.escape(name), src)
    if not m:
        raise AssertionError("array %s not found in PanelLayout.cs" % name)
    return [float(x.strip().rstrip("f")) for x in m.group(1).split(",") if x.strip()]


def py_constants(path: Path) -> dict:
    """Top-level constant assignments of the texture script, read without running it."""
    out = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            continue
        if isinstance(target, ast.Name):
            out[target.id] = value
        elif isinstance(target, ast.Tuple) and isinstance(value, tuple):
            for t, v in zip(target.elts, value):
                if isinstance(t, ast.Name):
                    out[t.id] = v
    return out


class PackageMetadata(unittest.TestCase):
    def test_package_json(self):
        data = json.loads((PKG / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(data["name"], PKG.name)
        self.assertRegex(data["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(data["license"], "MIT")
        self.assertIn("nadena.dev.modular-avatar", data["vpmDependencies"])
        self.assertIn("com.vrchat.avatars", data["vpmDependencies"])

    def test_asmdef_references_the_sdk_and_modular_avatar(self):
        asm = json.loads((PKG / "Editor" / "CoyotePanel.Editor.asmdef").read_text(encoding="utf-8"))
        self.assertEqual(asm["includePlatforms"], ["Editor"])
        self.assertIn("nadena.dev.modular-avatar.core", asm["references"])
        for dll in ("VRCSDKBase.dll", "VRCSDK3A.dll", "VRC.SDK3.Dynamics.PhysBone.dll", "VRC.SDK3.Dynamics.Contact.dll",
                    "VRC.SDK3.Dynamics.Constraint.dll"):
            self.assertIn(dll, asm["precompiledReferences"])


class MetaFiles(unittest.TestCase):
    """Unity ignores an asset that has no .meta when the package is immutable (git URL / PackageCache)."""

    def assets(self):
        for p in PKG.rglob("*"):
            rel = p.relative_to(PKG)
            if any(part.endswith("~") or part.startswith(".") for part in rel.parts):
                continue  # hidden by Unity: Tools~, Documentation~ ...
            if p.suffix == ".meta":
                continue
            yield p

    def test_every_asset_has_a_meta(self):
        missing = [str(p.relative_to(PKG)) for p in self.assets() if not Path(str(p) + ".meta").exists()]
        self.assertEqual(missing, [], "assets without a .meta file")

    def test_no_orphan_metas_and_unique_guids(self):
        guids = {}
        for meta in PKG.rglob("*.meta"):
            rel = meta.relative_to(PKG)
            if any(part.endswith("~") for part in rel.parts):
                self.fail("meta inside a hidden folder: %s" % rel)
            self.assertTrue(Path(str(meta)[:-5]).exists(), "orphan meta: %s" % rel)
            m = re.search(r"^guid: ([0-9a-f]{32})$", meta.read_text(encoding="utf-8"), re.M)
            self.assertIsNotNone(m, "no guid in %s" % rel)
            self.assertNotIn(m.group(1), guids, "duplicate guid in %s and %s" % (rel, guids.get(m.group(1))))
            guids[m.group(1)] = rel

    def test_texture_import_settings_are_shipped(self):
        for name in ("CoyotePlate.png", "CoyoteDigits.png"):
            meta = (PKG / "Textures" / (name + ".meta")).read_text(encoding="utf-8")
            self.assertIn("enableMipMap: 0", meta, name)       # no mipmaps: thin digits stay sharp
            self.assertIn("wrapU: 1", meta, name)              # clamp
            self.assertIn("nPOTScale: 0", meta, name)          # do not rescale to a power of two
            self.assertRegex(meta, r"buildTarget: DefaultTexturePlatform\s+maxTextureSize: 2048\s+resizeAlgorithm: 0\s+textureFormat: -1\s+textureCompression: 0", name)


class LayoutMatchesTextureScript(unittest.TestCase):
    def test_constants_match(self):
        cs = LAYOUT_CS.read_text(encoding="utf-8")
        py = py_constants(TEXTURE_PY)
        for name in SCALARS:
            self.assertIn(name, py, "%s missing from make_textures.py" % name)
            self.assertAlmostEqual(cs_scalar(cs, name), float(py[name]), places=6, msg=name)
        for name in ARRAYS:
            self.assertEqual(cs_array(cs, name), [float(x) for x in py[name]], name)


class BoostCap(unittest.TestCase):
    """The +30 cap of the slider is a safety feature. The simulator replays a frozen export of the controller, and Python cannot
    run the C# builder, so these tie the two together: change a boost constant in PanelLayout.cs and forget to re-export the
    controller (or to redraw the plate) and one of them fails."""

    @classmethod
    def setUpClass(cls):
        cls.cs = LAYOUT_CS.read_text(encoding="utf-8")
        cls.boost_max = cs_int(cls.cs, "BOOST_MAX")
        cls.step = cs_int(cls.cs, "BOOST_STEP")
        cls.hyst = cs_scalar(cls.cs, "BOOST_HYST")
        cls.smin = cs_scalar(cls.cs, "STR_SRC_MIN")
        cls.smax = cs_scalar(cls.cs, "STR_SRC_MAX")
        cls.export = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def states(self, channel):
        layer = next(l for l in self.export["layers"] if l["layer"] == "CoyotePad_Track" + channel)
        return {s["name"]: s for s in layer["states"]}

    def test_the_cap_is_30(self):
        # deliberately hard-coded: raising the cap must be a conscious edit of this test as well as of PanelLayout.cs
        self.assertEqual(self.boost_max, 30)
        self.assertEqual(self.boost_max % self.step, 0)

    def test_the_export_has_exactly_the_boost_chain_of_the_constants(self):
        steps = self.boost_max // self.step
        span = self.smax - self.smin
        for ch in "AB":
            states = self.states(ch)
            base, val, stretch = "CoyotePad/Base" + ch, "CoyotePad/Val" + ch, "CoyotePad/Pb%s_Stretch" % ch
            boosts = sorted(int(n.split("+")[1]) for n in states if n.startswith("Boost +"))
            self.assertEqual(boosts, [k * self.step for k in range(steps + 1)], "Boost states of channel " + ch)
            for k in range(steps + 1):
                st = states["Boost +%d" % (k * self.step)]
                drivers = [(d["type"], d["name"], d.get("src") or None, d["value"]) for d in st["drivers"]]
                expected = [("Copy", val, base, 0)] + ([("Add", val, None, k * self.step)] if k else []) + \
                           [("Set", "CoyotePad/Boost%s_f" % ch, None, k * self.step)]
                self.assertEqual(drivers, expected, "%s Boost +%d" % (ch, k * self.step))
                ups = [t for t in st["transitions"] if t["to"] == "Boost +%d" % ((k + 1) * self.step)]
                self.assertEqual(len(ups), 1 if k < steps else 0, "%s Boost +%d: up transitions" % (ch, k * self.step))
                for t in ups:
                    conds = {(c["p"], c["mode"]): c["thr"] for c in t["conds"]}
                    self.assertAlmostEqual(conds[(stretch, "Greater")], self.smin + span * ((k + 1) - 0.5 + self.hyst) / steps, places=4)
                    # the boost stops where base + boost would pass 200
                    self.assertEqual(conds[(base, "Less")], 201 - self.step * (k + 1))

    def test_zero_and_stop_latch_a_held_grip_and_a_one_frame_grab_changes_nothing(self):
        for ch in "AB":
            states = self.states(ch)
            grabbed, posed = "CoyotePad/Pb%s_IsGrabbed" % ch, "CoyotePad/Pb%s_IsPosed" % ch
            for name, st in states.items():
                if name != "Hold" and not name.startswith("Boost +"):
                    continue
                latch = sorted(c["p"] for t in st["transitions"] if t["to"] == "Latched" for c in t["conds"] if c["mode"] == "If")
                self.assertEqual(latch, ["CoyotePad/Zero", "CoyoteStop"], "%s %s: Zero and STOP must latch" % (ch, name))
            hold = states["Hold"]["transitions"]
            self.assertEqual(hold[0]["to"], "Idle", "Hold: letting go again comes first")
            self.assertEqual(sorted((c["p"], c["mode"]) for c in hold[0]["conds"]), sorted([(grabbed, "IfNot"), (posed, "IfNot")]))
            self.assertTrue(hold[-1]["exit"] and hold[-1]["to"] == "Boost +0", "Hold: the exit-time transition comes last")
            leave = states["Latched"]["transitions"]
            self.assertEqual([t["to"] for t in leave], ["Idle"])
            self.assertEqual(sorted((c["p"], c["mode"]) for c in leave[0]["conds"]), sorted([(grabbed, "IfNot"), (posed, "IfNot")]))

    def test_the_printed_scale_is_the_cap(self):
        src = TEXTURE_PY.read_text(encoding="utf-8")
        labels = re.findall(r'\((\d), "(\+?\d+)"\)', src)
        self.assertEqual(len(labels), 4, "four labels under each bar")
        self.assertIn("for i in range(4)", src, "four ticks under each bar")
        for i, text in labels:
            expected = "0" if int(i) == 0 else "+%d" % (self.boost_max * int(i) // 3)
            self.assertEqual(text, expected, "label %s of the bar scale" % i)


class ControllerSimulator(unittest.TestCase):
    def test_simulator_passes_on_the_example_export(self):
        sim = PKG / "Tools~" / "simulate_controller.py"
        res = subprocess.run([sys.executable, "-I", str(sim), str(EXAMPLE)], capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stdout[-3000:] + res.stderr[-1000:])
        self.assertIn("FAILURES: 0", res.stdout)
        self.assertGreaterEqual(res.stdout.count("PASS "), 137)      # 55 before the boost slider (0.3.0), 99 before the Latched state, 128 before the ceiling was checked on both channels


if __name__ == "__main__":
    unittest.main()
