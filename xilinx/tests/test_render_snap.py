import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.helpers import REPO, make_project, update_config

spec = importlib.util.spec_from_file_location("render_snap", REPO / ".workshop/snap/lib/render_snap.py")
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

TEMPLATE = REPO / ".workshop/snap/snapcraft.yaml.in"


class RenderSnapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = make_project(self.tmp)
        self.kernel = self.tmp / "out/kernel"
        (self.kernel / "metadata").mkdir(parents=True)
        (self.kernel / "metadata/build.json").write_text(json.dumps(
            {"kver": "6.8.0-1036-xilinx", "version": "6.8.0-1036.37+workshop1"}))
        self.out = self.tmp / "snapproj"

    def render(self):
        rs.render(self.proj, self.kernel, TEMPLATE, self.out)
        return yaml.safe_load((self.out / "snapcraft.yaml").read_text())

    def test_kernel_part_uses_kernel_plugin_binary_path(self):
        doc = self.render()
        kernel = doc["parts"]["kernel"]
        self.assertEqual(kernel["plugin"], "kernel")
        self.assertIs(kernel["kernel-ubuntu-binary-package"], True)
        self.assertEqual(kernel["kernel-ubuntu-kconfigflavour"], "xilinx")
        self.assertEqual(kernel["kernel-ubuntu-abinumber"], "6.8.0-1036")
        self.assertNotIn("kernel-ubuntu-debian-package", kernel)

    def test_snap_metadata(self):
        doc = self.render()
        self.assertEqual(doc["name"], "kv260-kernel")
        self.assertEqual(doc["type"], "kernel")
        self.assertEqual(doc["build-base"], "core24")
        self.assertEqual(doc["version"], "6.8.0-1036.37+workshop1")
        self.assertEqual(doc["platforms"], {"arm64": {"build-on": ["amd64"], "build-for": ["arm64"]}})

    def test_initrd_part_after_kernel(self):
        doc = self.render()
        self.assertEqual(doc["parts"]["initrd"], {"plugin": "initrd", "after": ["kernel"]})

    def test_shell_variables_survive_rendering(self):
        doc = self.render()
        script = doc["parts"]["kernel"]["override-build"]
        self.assertIn('"$CRAFT_PART_INSTALL/kernel.img"', script)
        self.assertIn("craftctl default", script)

    def test_kernel_yaml_declares_dtbs_asset(self):
        self.render()
        doc = yaml.safe_load((self.out / "kernel.yaml").read_text())
        self.assertEqual(doc, {"assets": {"dtbs": {"update": True, "content": ["dtbs/"]}}})

    def test_template_error_is_a_render_error(self):
        bad = self.tmp / "bad.yaml.in"
        bad.write_text("name: @{nosuch}\nemail: user@@example\n")
        with self.assertRaises(rs.RenderError) as ctx:
            rs.render(self.proj, self.kernel, bad, self.out)
        self.assertIn("bad.yaml.in", str(ctx.exception))

    def test_snap_version_over_32_characters_rejected(self):
        (self.kernel / "metadata/build.json").write_text(json.dumps(
            {"kver": "6.8.0-1036-xilinx", "version": "6.8.0-1036.37+workshop1.local.build.extra"}))
        with self.assertRaises(rs.RenderError) as ctx:
            self.render()
        self.assertIn("32 characters", str(ctx.exception))

    def test_dtbs_are_moved_not_duplicated(self):
        script = self.render()["parts"]["kernel"]["override-build"]
        self.assertNotIn("cp -a", script)
        self.assertIn('mv "$CRAFT_PART_INSTALL"/firmware/*/device-tree', script)

    def test_check_name_needs_no_build_outputs(self):
        shutil.rmtree(self.kernel)
        rs.check_name(self.proj)
        update_config(self.proj, lambda c: c["silicon"].update(board="KV260"))
        with self.assertRaises(rs.RenderError):
            rs.check_name(self.proj)

    def test_invalid_board_name_rejected(self):
        update_config(self.proj, lambda c: c["silicon"].update(board="KV260"))
        with self.assertRaises(rs.RenderError) as ctx:
            self.render()
        self.assertIn("silicon.board", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
