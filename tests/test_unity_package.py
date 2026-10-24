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

SCALARS = ["PW", "PH", "ROW_A", "ROW_B", "ROW_F", "BAR_X0", "BAR_X1", "MINUS_X", "PLUS_X",
           "CELL_W", "CELL_H", "BTN_DN_X", "BTN_UP_X"]
ARRAYS = ["DIG_X", "FDIG_X"]


def cs_scalar(src: str, name: str) -> float:
    m = re.search(r"\b%s\s*=\s*(-?\d+(?:\.\d+)?)f" % re.escape(name), src)
    if not m:
        raise AssertionError("constant %s not found in PanelLayout.cs" % name)
    return float(m.group(1))


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


class ControllerSimulator(unittest.TestCase):
    def test_simulator_passes_on_the_example_export(self):
        sim = PKG / "Tools~" / "simulate_controller.py"
        example = PKG / "Tools~" / "ctrl.example.json"
        res = subprocess.run([sys.executable, "-I", str(sim), str(example)], capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stdout[-3000:] + res.stderr[-1000:])
        self.assertIn("FAILURES: 0", res.stdout)
        self.assertGreaterEqual(res.stdout.count("PASS "), 55)


if __name__ == "__main__":
    unittest.main()
